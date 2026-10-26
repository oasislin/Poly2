# P8-CLASS1-LAUNCH-CHK-09 · Ticket 01 交付复核单（契约 Schema + 双轴 Code Review 汇报）

> **日期**：2026-10-22
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-09`
> **复核对象**：
> 1. `src/contract/parameter_contract.py`（交付代码本体）
> 2. `src/contract/__init__.py`、`tests/unit/contract/test_parameter_contract.py`
> 3. `docs/audit/P8-CLASS1-LAUNCH-TICKET01_交付与双轴CodeReview验收汇报_20261022.md`
> **复核人**：技术审核 Agent（只读代码级核验；测试未重跑，边界见 §三）

---

## 一、 复核结论

**Ticket 01（#134）验收：通过**。ADR-0019 §三 必须消费字段、零硬编码/零默认值重构、22 格组织、版本锚点均在代码中逐一落实；测试文件与汇报声明一致。

## 二、 代码级核验明细（逐项对照）

| 验收点 | 代码证据（原始观测） | 判定 |
| :-- | :-- | :-- |
| 零默认值（Zero Defaults） | `CellCalibrationRecord`/`PhysicalForecastOutput`/`PhysicalParamContract` 全部纯类型声明、无字段默认值；缺参构造直接 TypeError | **通过** |
| Fail-Closed 反序列化 | `from_dict()` 全部直接索引 `data["..."]`，无 `.get(default)`；缺法定字段抛 KeyError（test L87 覆盖） | **通过** |
| 外层键与内层标识一致性强校验 | `from_dict` 逐格比对 `expected_key` vs `f"{station}_{lead}h"`，不符抛 ValueError（L204-211；test L269 覆盖） | **通过** |
| 零门限判定（契约层） | 契约内无任何业务/统计数值比较；`validate_cells_coverage` 注释明示"Pure structure check; ZERO numerical threshold checks"；`fstd_in`/`v1_coverage_90_pass`/`reject_uniform` 作为上游布尔事实原样搬运 | **通过** |
| 22 格组织与防全局均值化 | `AUTHORIZED_STATIONS=(KORD,KMIA)`、`AUTHORIZED_LEAD_HOURS=12~72（11 档）`、`TOTAL=22`；字典按 `(station, lead)` 键组织（test L202 防全局均值化覆盖） | **通过** |
| 必须消费字段（静态） | `s_oos/fstd_lo/fstd_hi/fstd_in/ece_2f/v1_coverage_90/v1_coverage_90_pass/pit_mean/pit_var/reject_uniform` 全部在 `CellCalibrationRecord` | **通过** |
| 必须消费字段（动态） | `mu_calib/sig_eff/distribution_family/p_j` 在 `PhysicalForecastOutput`；`p_j: Dict[str, Decimal]` 全链路 Decimal | **通过** |
| 间接消费字段 | `neff/cvm_stat/cvm_p/ece_range` 齐备 | **通过** |
| 版本锚点 | `contract_version/manifest_sha256/model_weights_sha256/created_at` 在 `PhysicalParamContract`（供 Ticket 02 看门狗引用） | **通过** |
| 不可变与序列化 | `@dataclass(frozen=True)`；`to_dict/from_dict` roundtrip（test L74/L239 覆盖） | **通过** |
| 专属单测 | 测试文件含 **12** 个 `test_` 函数，名称与汇报 §四.1 输出逐项一致 | **通过** |

## 三、 复核边界（诚实披露）

1. **测试未由复核方重跑**：本地复核环境未装 pytest，12 passed / 125 passed 以开发端实测输出为准（命令+输出片段+通过数+两步判定齐全，形式合规）；复核方不做重跑通过声明。
2. **远端 Git 无法本地验证**：本副本非 git 仓库；push（`dc0b963..cec8bf8`，提交链 2a3af76/e9b9f87/cec8bf8）依用户明确指令执行，以开发端输出为准。push 纪律（凭指令）已满足。
3. GEFS 真实网络测试豁免理由成立（纯离线契约，不触网络路径）。

## 四、 次要观察（不阻塞验收，建议带入后续票）

- `validate_cells_coverage()` 仅校验 22 格**均在**，不拒绝**额外格**（第 23 格可混入）。若需"恰好 22 格"强约束，建议落在 **Ticket 03** 的转换器校验（其测试已断言恰好 22 格），本票不阻塞。

## 五、 下一步建议

依依赖拓扑，当前仅依赖 Ticket 01 的解锁票为 **02（#135）/ 03（#136）/ 06（#139）**，三者无相互依赖：

- **主推 02（版本戳看门狗）**：直接消费本票 `manifest_sha256/model_weights_sha256` 锚点，是 ADR-0019 §二.6 启动期防御的落地点，并解除 Ticket 04（重测流水线）；
- **可并行 03（CSV→22 格 JSON 导出）**：为 S_conf/ψ 提供客观输入，同时落实"恰好 22 格"强校验（承接 §四 观察项）；
- **可并行 06（Q7 双轨）**：定价层首票，与 03 无冲突。

建议波次：`02 主推 + 03/06 并行`；契约链 04/05 随后。是否按此推进由您/开发端排程。

## 六、 红线重申

不代跑 gh、push 凭指令；不重训、不改 EMOS 参数、不落定值（F-2 锁）；观测值以原件为准。
