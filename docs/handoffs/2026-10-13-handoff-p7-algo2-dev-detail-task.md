<!-- 供开发端读取 | 日期: 2026-10-13 | 发送方: 主导方（经用户确认推进） -->
# P7-ALGO-2 落档细化任务单（开发端）

> **任务性质**：P7-ALGO-2 流程第 4 步——开发端（执行端）落档细化
> **输入**：规格书 v0.3 + 算法描述文档 v0.3（一致终稿 Final Draft，用户已确认继续推进）
> **产出要求**：将一致终稿细化为**可落地工程设计**（接口签名、数据模型、状态机、模块结构、核心算法实现草案），交主导方审阅 + 用户确认

---

## 一、任务输入（均已落盘 docs/audit/，可直接读取）

| 文件 | 角色 |
| :--- | :--- |
| `P7-ALGO-2_规格书.md` v0.3 | 流程/模块/门禁/接口/挂锁（一致终稿） |
| `P7-ALGO-2_算法描述文档.md` v0.3 | 数学公式完备版（一致终稿） |
| `P7-ALGO-VERDICT.md` v0.3 | 判决书（M-1~M-8 已签署 = 立法输入） |
| `P7-ALGO-2_M6_coverage_verification.md` | M-6 覆盖性验证（已通过） |
| `P7-ALGO-2_素材盘点.md` / `P7-ALGO-2_代码盘点.md` | 素材三清册 / 归档代码盘点 |
| `docs/archive/trading_modules/` | 归档代码（src 16 在档 + tests 20 契约 + scripts 5） |

## 二、细化任务清单（逐项产出）

1. **模块接口签名定稿**（M1~M8 + M-G）：以规格书模块契约为唯一基准，定稿函数签名、数据类、枚举（含你已建议的 `optimize(...)` / `route_orders(...)` 方向；决策快照 Frozen Dataclass/NamedTuple 设计）；
2. **数据模型与状态机**：四桶资金状态机、台站生命周期（ACTIVE/SUSPENDED/INVALIDATED/EMERGENCY_HALT）、残差状态机（CLEAN/RESOLVED_BALANCED/LIQUIDATED）、订单状态（IOC）、僵尸分级（R_z 四档）；
3. **核心算法实现草案**：多项凯利 SLSQP（含凹目标 + 内层贪心投影 O(K log K) + Σp_L>1 退化分支）、Delta Method 不确定集（高斯族闭式灵敏度）、VWAP→费率时序、保护价 + safe_capacity（含 `SKIPPED_INSUFFICIENT_PROTECTED_DEPTH`）、套利判定式（Taker/Maker 双式）；
4. **门禁布尔下沉**：G1~G7 全部实现为 `pass = value >= threshold` 布尔判定（含 G4 两维风控、G5 带旗禁投、G7 Fail-Closed）；
5. **精度守恒**：SLSQP 浮点输出 → 执行路由 `quantize(Decimal("0.000001"), ROUND_DOWN)`；
6. **日志/审计标记规范**：`SKIPPED_INSUFFICIENT_PROTECTED_DEPTH`、`FLAGGED_ASSET_BLOCKED`（带旗禁投观测）、SLSQP 连续失败上报等；
7. **模块/文件结构规划**：新实现落位规划（不迁旧代码、不恢复缺失文件），与现役 `src/` 隔离，标注挂锁点。

## 三、硬约束（不得违反）

- **F-2 挂锁**：θ、η、δμ、δσ、margin_dutch、min_edge **不填实值**，一律标注 `[F-2 LOCKED]` / `[待标定]`；base/β 标 `[待核实]`；
- **宪法**：只买不卖、严禁市价单、决策快照冻结、fail-closed（未收敛/NaN → 全零）、Decimal 全链路、70% 全局利用率不豁免；
- **判词 M-1~M-8**：立法输入，细化不得违反（不确定集宽度 = EMOS CDF 参数派生；Shrinkage/阶梯投注/φ=1.3 等已废弃机制不得回流）；
- **缺失代码**：归档区 bankroll/execution 11 个源文件已废止（用户裁决），**不重写旧代码、不恢复**，一切以规格书新定义为准；
- **实证纪律**：任何"通过/达标"声明须附命令/脚本 + 输出末尾原始片段 + 判定阈值与逻辑；未执行不得表述为"通过"。

## 四、流程约定

1. 开发端落档细化产出落盘 `docs/audit/`（命名：`P7-ALGO-2_dev_detail_YYYYMMDD.md` 或按工程结构分模块落盘）；
2. 主导方审阅（对齐规格书 §4 模块规格 + §6 门禁 + 附录 A 判词对照表）；
3. 用户最终确认；
4. **代码实现在 F-2 概率层绿灯后启动**（本阶段只落档细化，不落地运行代码）。

*本任务单为流程交接件；细化产出未经验收前不视为完成。*
