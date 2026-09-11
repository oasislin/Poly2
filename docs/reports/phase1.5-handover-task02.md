# Phase 1.5 交接文档：从 Task 01/09 到 Task 02（IEM 管道正式化）

> **生成时间**：2026-09-11  
> **当前阶段**：Phase 1.5 —— 数据管道重建与校准语料库  
> **前序完成**：Task 01（基线封存）、Task 09（GEFS 因子提取与补全）、KDCA 站点退役清理  
> **下步目标**：Task 02（IEM 观测管道正式化）

---

## 1. 系统当前状态与已闭环产物 (Context & Status)

### 1.1 基线封存 (Task 01 交付)
- **Git Annotated Tag**：`phase1-final`，严格锚定在 M0' 审计最终 Commit `53b1024`。
- **历史审计资产归档**：18 份 M0' 审计报告由 `docs/reports/` 迁移至 [`docs/frozen/phase1/`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/frozen/phase1)，头部均附加只读声明。
- **历史污染数据物理隔离**：旧版 Wunderground 爬虫库及衍生特征物理隔离至 `data/legacy-v1-suspect/`，标记 `SUPERSEDED`，严禁接入下游训练。
- **封存盘点报告**：[`docs/reports/phase1-freeze-inventory-v1.0.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/reports/phase1-freeze-inventory-v1.0.md)。

### 1.2 预报特征库 (Task 09 交付)
- **外部冷归档**：`/Volumes/EricSSD/Poly RawData/gefs_reforecast` 存有完整 2000–2019（7,305 天）× 40 GRIB2 文件，位翻转坏道已全面修复。
- **特征长表**：存放在 `data/processed/gefs_factors/`，覆盖 11 个活跃交易站点 × 20 年，共 220 个 Parquet 文件，精确 9,641,830 行（零 Null、零物理越界）。
- **元数据索引**：`data/processed/gefs_factors/manifest.json` 已全部建立校验和与维度索引。
- **QC 报告**：[`docs/reports/gefs_task09_qc_v1.0.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/reports/gefs_task09_qc_v1.0.md)。

### 1.3 站点宇宙体系重铸 (11 站全美活跃交易大池)
- **退役站点**：华盛顿（`KDCA`）因仅存在 2025 就职日单次盘且无常态日盘，已正式废弃并从核心常量 `STATION_METADATA`、提取脚本及因子库中彻底剥离。
- **11 站活跃交易池**：
  1. `KORD`（芝加哥奥黑尔，首发结算站）
  2. `KLGA`（纽约拉瓜迪亚，Tier 1）
  3. `KATL`（亚特兰大哈兹菲尔德，Tier 1）
  4. `KDAL`（达拉斯爱田，Tier 1）
  5. `KSEA`（西雅图塔科马，Tier 2）
  6. `KLAX`（洛杉矶，Tier 2）
  7. `KHOU`（休斯顿霍比，Tier 2）
  8. `KMIA`（迈阿密，微气候重点站）
  9. `KSFO`（旧金山，微气候重点站）
  10. `KBKF`（丹佛巴克利空军基地，特许结算站）
  11. `KAUS`（奥斯汀伯格斯特龙，扩充主力站）

---

## 2. 接下来要在新对话执行的单据：Task 02（IEM 管道正式化）

### 2.1 任务目标与背景
Phase 1 原型阶段在 Round 5 探索了 IEM ASOS 报文解析与 NWS WRH 校验逻辑（位于原型脚本中）。
**Task 02 的核心使命是将其工程化、正式化为生产级模块** `src/pipeline/iem_adapter.py`，为后续 Task 04（全量抓取 19 年观测真值）与 Task 05（气候学 Floor 重建）提供高可靠的数据获取与解析底座。

### 2.2 核心需求与三道质量门禁
根据《Phase 1.5 执行文件 v1.1》§2 任务矩阵：
1. **模块架构**：
   - 生产级接口：`src/pipeline/iem_adapter.py`，承接 IEM ASOS API 请求、缓存分块、故障重试与报文解码。
   - 提取精度：强制解析 METAR 报文尾部 `RMK` 的 `T` 组编码（`T[01]\d{3}[01]\d{3}`），获取精确到 $0.1^\circ\text{C}$（约 $0.18^\circ\text{F}$）的真值温度，彻底杜绝浮点截断伪影。
2. **门禁 ①（T 组覆盖率门禁）**：
   - 日级报文 `RMK T` 组解析成功率必须 $\ge 99\%$；不达标样本必须显式打标降级（`quality_flag: degraded`），不得静默通过。
3. **门禁 ②（双源日极值一致性门禁）**：
   - 将 IEM ASOS 当日推算的 TMAX/TMIN 与 NWS WRH 结算时序表极值进行比对。
   - 若绝对偏差 $> 0.2^\circ\text{F}$，强制记录告警并持久化落盘至审计日志，保留原始报文以备争议仲裁。
4. **门禁 ③（Provenance 溯源四元组落盘）**：
   - 所有输出的数据集与分块文件必须附带 Provenance 四元组：`timestamp`（提取时间）、`git_commit_sha`（当前提交号）、`sha256`（数据哈希）、`source_url`（数据源真实端点）。
5. **工程鲁棒性**：
   - 年度分块存储（`data/raw/iem/{station}/{year}.parquet` 或 csv）。
   - 断点续传机制（按日/按月检查已落盘范围，避免重复拉取）。
   - 针对 IEM 免费 API 的自适应限流、指数退避（Exponential Backoff）与连接重试。

### 2.3 关键依赖文件与参考资料
- 方案与任务定义：[`Phase 1.5 执行文件 v1.1：数据管道重建与校准语料库.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/%E9%A1%B9%E7%9B%AE%E6%96%B9%E6%A1%88%E5%92%8C%E6%89%A7%E8%A1%8C%E6%96%87%E6%A1%A3/Phase%201.5%20%E6%89%A7%E8%A1%8C%E6%96%87%E4%BB%B6%20v1.1%EF%BC%9A%E6%95%B0%E6%8D%AE%E7%AE%A1%E9%81%93%E9%87%8D%E5%BB%BA%E4%B8%8E%E6%A0%A1%E5%87%86%E8%AF%AD%E6%96%99%E5%BA%93.md)
- 历史裁决与依据：[`ADR-0007：数据源重铸与站点宇宙扩展.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/adr/ADR-0007%EF%BC%9A%E6%95%B0%E6%8D%AE%E6%BA%90%E9%87%8D%E9%93%B8%E4%B8%8E%E7%AB%99%E7%82%B9%E5%AE%87%E5%AE%99%E6%89%A9%E5%B1%95%EF%BC%88M0%27%20%20Round%205%20%E7%BB%BC%E5%90%88%E8%A3%81%E5%86%B3%EF%BC%89.md)
- 现存 IEM 探针逻辑参考：[`src/pipeline/nws_wrh_adapter.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/pipeline/nws_wrh_adapter.py)（或历史 Round 5 探针）
- 11 站元数据定义：[`src/data_processing/constants.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/data_processing/constants.py)

---

## 3. 新会话启动指南 (How to Start in New Conversation)

在新起对话后，用户可直接向 Agent 输入以下指令：

> **提示词示例**：  
> 「请阅读 `docs/reports/phase1.5-handover-task02.md`，目前我们已完成 Task 01 与 Task 09，并移除了 KDCA。现在开始执行 **Phase 1.5 Task 02：IEM 管道正式化**。请遵循硬性规则，先给出 Task 02 的详细设计方案与测试计划，待我确认后再进行代码编写。」
