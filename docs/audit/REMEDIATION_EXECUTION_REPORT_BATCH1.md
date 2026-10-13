# REMEDIATION_PLAN 本地执行落地报告（批次一）

**执行时间**：2026-10-13  
**执行基准**：严格遵循《REMEDIATION_PLAN.md》（v1.1 / v1.2）最高裁决与《AGENTS.md》审计纪律。  
**报告定位**：供用户、管理委员会及三方审查独立 Review 与对账。

---

## 一、 批次一执行任务清单与状态核验

| 整改项编号 | 任务领域 | 裁决要求与目标 | 实际执行动作与落地路径 | 验收结果 |
| :--- | :--- | :--- | :--- | :---: |
| **R-06** | ADR 命名治理 | 统一为 `ADR-XXXX：中文主题.md` 单文件规范，消除中英文混编与散乱命名 | 重命名完成：<br>- `0001` ~ `0006` 全部统一为标准前缀与中文主题名<br>- `ADR-0018` 重命名为 `ADR-0018：小样本分档断崖裁定与门禁分层口径规范.md` | ✅ **通过** |
| **R-07 & R-08** | 缺失与废止 ADR | 确认删除 ADR-0016 缺失占位；正式废止引用已删 0016 的 ADR-0017 | - 清理全部对 ADR-0016 的无效关联；<br>- `ADR-0017` 移入 `docs/archive/ADR-0017：期望校准误差 (ECE) 统计口径规范、尖锐度概念纠偏与双层门禁仲裁（已废止）.md` 归档 | ✅ **通过** |
| **R-04 & R-05** | 命名基线纠偏 | 撤销非法的 "Phase 4~7" 描述，确立四层命名体系（阶段/工单/波次/任务） | 修订完成：<br>- [`docs/项目方案和执行文档/项目方案 (v2.8).md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/%E9%A1%B9%E7%9B%AE%E6%96%B9%E6%A1%88%E5%92%8C%E6%89%A7%E8%A1%8C%E6%96%87%E6%A1%A3/%E9%A1%B9%E7%9B%AE%E6%96%B9%E6%A1%88%20%28v2.8%29%EF%BC%9APolymarket%20%E6%B8%A9%E5%BA%A6%E5%B8%82%E5%9C%BA%E9%87%8F%E5%8C%96%E6%8A%95%E6%B3%A8%E7%B3%BB%E7%BB%9F.md)：§1 与 §7 路线图图表纠偏<br>- [`docs/项目方案和执行文档/Phase 2 执行文件 v2.1.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/%E9%A1%B9%E7%9B%AE%E6%96%B9%E6%A1%88%E5%92%8C%E6%89%A7%E8%A1%8C%E6%96%87%E6%A1%A3/Phase%202%20%E6%89%A7%E8%A1%8C%E6%96%87%E6%A1%A3%20v2.1%EF%BC%9A%E7%9B%98%E5%8F%A3%E5%AE%9A%E4%BB%B7%E3%80%81%E5%A5%97%E5%88%A9%E4%B8%8E%E6%89%A7%E8%A1%8C%E5%BC%95%E6%93%8E.md)：版本变更第 8 条纠偏 | ✅ **通过** |
| **R-13** | 历史文档归档 | 历史版本文档（方案 v2.2~v2.7、执行文件旧版等）移入存档，根目录留指针 | 归档完成：<br>- 21 份历史方案与执行文件移至 `docs/archive/项目方案和执行文档/`<br>- 5 份早期英文设计文档移至 `docs/archive/early_english_docs/`<br>- 建立权威索引指南 [`docs/archive/README.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/archive/README.md) | ✅ **通过** |
| **R-18** | 代码卫生 (Wunderground) | 标记后存档，不删除，注明可能复用；清除生产包根无效导出 | - 移出历史爬虫脚本至 [`docs/archive/wunderground_scripts/`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/archive/wunderground_scripts/) 并附带说明；<br>- 清理 `src/data_acquisition/__init__.py` 废弃导入；<br>- 回归单测 `pytest tests/unit/data_acquisition/`：**157 passed, 4 skipped** | ✅ **通过** |
| **台账同步** | 治理台账登记 | 记录判决书 M-1~M-8 签署闭环与 C-1~C-3 解锁状态 | [`docs/audit/DECISION_LEDGER.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/audit/DECISION_LEDGER.md) 新增第五节，登记本批次全部执行细节与 C 类解锁依据 | ✅ **通过** |

---

## 二、 物理文件树变更实录

### 1. `docs/adr/` 当前纯净单文件结构（16 份生效 ADR）：
```text
ADR-0001：标准高斯EMOS与气候学方差Floor.md
ADR-0002：时效节点缩减与参数时空插值.md
ADR-0003：两级降级架构与容灾触发规则.md
ADR-0004：GEFS五成员严格对齐与离散度归一.md
ADR-0005：气象变量合并坐标属性覆盖容差.md
ADR-0006：离散区间全概率映射与严禁累积尾部单向交易原则.md
ADR-0007：数据源重铸与站点宇宙扩展（M0'  Round 5 综合裁决）.md
ADR-0008：GEFS 再预报全池采购、源文件冷归档与时区自适应（GEFS-WI-v1.1 综合裁决）.md
ADR-0009：芝加哥 08-31 特报（SPECI）结算语义裁决与截断层规则.md
ADR-0010：气候学方差门禁物理上限（15.0°F）标定与衍生推导规范.md
ADR-0011：双源单调合流架构、TMAX-TMIN对称截断与两维阶梯风控裁决.md
ADR-0012：法定结算真值源（NWS WRH）、僵尸仓位双轨估值与舍入闭环裁决.md
ADR-0013：特报高频截断与异常安全阻断裁决.md
ADR-0014：统一异常仲裁中枢与台站级安全挂起协议（架构原则与站位）.md
ADR-0015：废除高斯EMOS气候方差加法项、确立物理方差底座与离散校准门禁.md
ADR-0018：小样本分档断崖裁定与门禁分层口径规范.md
```

### 2. `docs/项目方案和执行文档/` 当前现行生效法定文件（7 份）：
```text
Phase 1 执行文件：项目执行文件 v5.9.2(细化版).md
Phase 1.5 执行文件 v1.1：数据管道重建与校准语料库.md
Phase 2 执行文件 v2.1：盘口定价、套利与执行引擎.md
Polymarket 温度市场微观结构、玩家画像与 Alpha 边界实证分析.md
天气套利参数标定与联合优化方案.md
工作指导文件：GEFS 数据补全、站点提取与质量验证（GEFS-WI-v1.1）.md
项目方案 (v2.8)：Polymarket 温度市场量化投注系统.md
```

---

## 三、 测试与代码完整性验证证据

- **测试命令**：`pytest tests/unit/data_acquisition/ -q`
- **原始观测值**：
  ```text
  =========== short test summary info ===========
  157 passed, 4 skipped, 3 warnings in 46.28s
  ```
- **判定两步分离**：
  - `原始观测值 = 157 passed, 4 skipped, 0 failed (exit code 0)`
  - `判定阈值 = 0 failed, exit code == 0`
  - `结论 = 通过`

---

## 四、 剩余待处理事项指引

依据 `REMEDIATION_PLAN.md`（v1.2）：
1. **需在 git 工作副本机器执行的项**：
   - **R-02**：按第六节清单执行 8 提交合流、9 提交 revert 退回及剔除 9 个 `_SERLV_` 冲突副本；
   - **R-12**：线上 README 依据已完成修改执行同步推送。
2. **后续本地可规划项**：
   - **R-16**：现役交易模块整体归档至隔离区；
   - **R-17**：正式立项并撰写 **P7-ALGO-2《联合凯利与执行定价算法规格书》**（M-1~M-8 判词与 F-2 优先律为核心骨架）。
