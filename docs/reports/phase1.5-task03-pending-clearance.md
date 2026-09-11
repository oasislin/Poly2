# Phase 1.5 Task 03: 历史挂账清账与特报语义综合验收报告

> **生成时间**：2026-09-11  
> **责任团队**：量化研究与工程质控组  
> **依据规范**：《Phase 1.5 执行文件 v1.1》§2 Task 03 与 §4.5 验收标准  
> **前置依赖**：Task 01（基线封存）、Task 02（IEM 管道正式化）、ADR-0007、ADR-0009  
> **交付状态**：**8 项历史挂账全部清零闭环（零游离项）**

---

## 1. 任务背景与核心使命

在 Phase 1 原型与审计阶段，为确保不阻断整体流程推进，建立了挂账台账（`PENDING-01 ~ PENDING-08`，归档于 `docs/frozen/phase1/station-audit-comprehensive-report-v1.1.md` §5）。
根据《Phase 1.5 执行文件 v1.1》，在进入 Task 04 全量重取（11 站 × 2000–2026）与 Task 05/06 语料重建之前，必须**全面清零一切假设兜底值（ASSUMED）与待决项（PENDING）**，锁定特报语义规则，杜绝下游模型训练和复刻器受到未决概念的干扰。

---

## 2. 挂账逐项清零证据链与状态翻转矩阵

| 挂账编号 | 标的站点 | 原始状态 | 终审状态 | 处置结论与核心事实证据 | 闭环依据 / 验收点 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **PENDING-01** | 全站点通用 | `PENDING` | **`ATTACHED_PHASE2`** | **X.50 临界边界判例验证**：属于结算复刻器审计扫描范围，当前已明确挂接至 Phase 2 验收点，不阻塞 Phase 1.5 数据管道重建。 | 显式挂接 Phase 2 §4.2 |
| **PENDING-02** | 丹佛民航 (`KDEN`) | `PENDING` | **`CLOSED_NO_MARKET`** | **无盘口站注销**：Denver 官方日盘结算站已由 ADR-0007 裁定 100% 结算于 Buckley SFB (`KBKF`)，KDEN 无对应交易标的，正式关闭该挂账。 | ADR-0007 D3 |
| **PENDING-03** | 纽约/芝加哥 | `ASSUMED (Provisional)` | **`PARAMETER_LOCKED`** | **Era 1 先验分布固化**：基于 IEM RMK T 组复验，确证旧版 Wunderground 历史日表存在 -2.0°F ~ -5.1°F 系统性负偏差。Phase 1.5 彻底废弃 WU 作为真值，该经验参数正式固化为 $N(-2.8, 1.5^2)$，仅用于 Era 1 压力测试（`usage=stress-test-only`），不再进行正向校准。 | ADR-0007 D1/D4 |
| **PENDING-04** | 迈阿密 (`KMIA`) | `PENDING` | **`VERIFIED`** | **判例扩样与探针清洗**：清洗 Synoptic API 整数摄氏度伪影后，KMIA 历史判例达到 **4/4 (100% 确证吻合)**（03-29 78.08°F 命中 78-79°F，04-01 78.98°F 命中 78-79°F，09-02 89.60°F 进位命中 90-91°F）。首发展期顺利完成。 | `settlement-station-mapping-v1.0.md` §6 |
| **PENDING-05** | 奥斯汀 (`KAUS`) | `ASSUMED (95.0%)` | **`VERIFIED`** | **19 年历史覆盖率全量实测**：调用 IEM 探针实测 KAUS 2000–2018 逐年数据，**19/19 年全活跃（100% 连续性）**，实测综合覆盖率 **`99.2%`**，超额通过 $\ge 95.0\%$ 准入门禁，兜底值已翻转为实测值。 | `scripts/probe_iem_coverage.py` 实测输出 |
| **PENDING-06** | 华盛顿 (`KDCA`) | `ASSUMED (95.0%)` | **`RETIRED_DECOMMISSIONED`** | **退役站点正式注销**：KDCA 仅存 2025 就职日单次盘且无常态日盘，已依据 Task 01 与交接文件彻底从 11 站核心宇宙剥离退役，挂账正式核销。 | Task 01 交付清单、交接文档 §1.3 |
| **PENDING-07** | 奥斯汀 (`KAUS`) | `PENDING` | **`ADMITTED`** | **盘口准入确认**：KAUS 具备稳定活跃日盘与优秀发报密度（625 报/48h），元数据状态更新为 `ADMITTED_TIER_2`，正式准入活跃交易站池。 | `src/data_processing/constants.py` |
| **PENDING-08** | 芝加哥 (`KORD`) | `PENDING` | **`RESOLVED`** | **特报（SPECI）结算效力裁决**：2026-08-31 实证确证 Polymarket 官方结算采信 13:44 强雷暴特报（86.0°F），正式出具 **ADR-0009** 固化特报法定结算地位，Task 02 管道默认拉取 `report_type=["1", "2"]`。 | **ADR-0009** 核心裁决 |

---

## 3. 关键裁决与核心技术产物

### 3.1 ADR-0009：芝加哥 08-31 特报语义裁决
- **文件路径**：[`docs/adr/ADR-0009：芝加哥 08-31 特报（SPECI）结算语义裁决与截断层规则.md`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/docs/adr/ADR-0009%EF%BC%9A%E8%8A%9D%E5%8A%A0%E5%93%A5%2008-31%20%E7%89%B9%E6%8A%A5%EF%BC%88SPECI%EF%BC%89%E7%BB%93%E7%AE%97%E8%AF%AD%E4%B9%89%E8%A3%81%E5%86%B3%E4%B8%8E%E6%88%AA%E6%96%AD%E5%B1%82%E8%A7%84%E5%88%99.md)
- **核心论断**：Polymarket 在 Era 2 下的结算采信包含特报（SPECI）在内的所有官方公布观测值，数据获取管道必须维持 `report_type=["1", "2"]`；下游 Task 06 特征库将提供包含特报与纯整点报的双轨极值特征。

### 3.2 KAUS 19 年历史覆盖率全量探针实测
- **实测脚本**：`scripts/probe_iem_coverage.py --station KAUS`
- **采样穿透实证**（2000–2018 逐年数据）：
  ```json
  {
    "station": "KAUS",
    "network": "TX_ASOS",
    "period": "2000-2018",
    "coverage_pct": 99.2,
    "passed_gate": true,
    "status": "COMPLETE"
  }
  ```
- **活跃年份**：19 / 19 年连续活跃，无断代年。

### 3.3 核心元数据同步与状态更新
- **修改文件**：[`src/data_processing/constants.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/data_processing/constants.py)
  - `KAUS` 的 `audit_status` 由 `PENDING_AUDIT` 翻转为 **`ADMITTED_TIER_2`**；
  - `KAUS` 的 `historical_coverage_pct` 由假定值 `95.0` 修正为实测值 **`99.2`**。
- **修改文件**：[`src/data_acquisition/iem_coverage_prober.py`](file:///Users/ericlin/SynologyDrive/Project/Poly%20Way2/src/data_acquisition/iem_coverage_prober.py)
  - 正式将 `KAUS`, `KLAX`, `KHOU`, `KSFO` 纳入校准深度表。

---

## 4. 验收与终审宣言 (Final Sign-off)

根据《Phase 1.5 执行文件 v1.1》§4.5 台账关要求：
> “**台账关**：PENDING-01~08 全部关闭或显式挂接 Phase 2 验收点，无游离项。”

至此：
1. **PENDING-01** 已显式挂接 Phase 2 结算复刻器验收点；
2. **PENDING-02** 明确注销（KDEN 无盘口）；
3. **PENDING-03** 明确固化负偏差压测基准；
4. **PENDING-04** 4/4 判例完成确证；
5. **PENDING-05** 实测覆盖率 99.2% 超额达标；
6. **PENDING-06** 随 KDCA 退役核销注销；
7. **PENDING-07** KAUS 正式转入准入站池；
8. **PENDING-08** 出具 ADR-0009 彻底裁决特报效力。

**全台账 8 项挂账全部闭环，游离项清零，系统获准无障碍推进至 Task 04（全量重取）！**
