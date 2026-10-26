# P8-CLASS1-LAUNCH-CHK-15 · Ticket 04 首轮交付复核单

> **日期**：2026-10-26  
> **A 线锚点**：`Phase 2 Task 08 - Ticket 04` / [#137](https://github.com/oasislin/Poly2/issues/137)  
> **工单（B 线）**：`P8-CLASS1-LAUNCH`  
> **核验单**：`P8-CLASS1-LAUNCH-CHK-15`  
> **复核对象**：`d320a18`（feat 契约流水线实现）、`55514c9`（fix M-6/M-7 闭环）  
> **前序单据**：`P8-CLASS1-LAUNCH-CHK-13`（Ticket 03 复验通过）、`P8-CLASS1-LAUNCH-CHK-14`（Ticket 25 复验通过）  
> **复核人**：技术审核 Agent（独立执行，未采信交付端自述）  

---

## 一、 复核结论

**通过**。Ticket 04 成功实现物理模型重测触发、V2 评估尺升级、22 格契约抽取、只读校验器/看门狗门禁与结构化审计留痕全链路流水线；前序结转项 M-3（异常收敛）与 M-5（四层资产口径）完全闭合；交付状态缺陷 M-6 与 M-7 经单一微整改 commit（`55514c9`）彻底闭环；全量测试全绿且零未授权 push，准予结项。

---

## 二、 门禁独立复验（复核方本机实测原始值）

| 门禁 | 命令 / 探针 | 复核方实测原始值 | 判定阈值 | 结论 |
|---|---|---|---|---|
| **G1** | 专属单测套件 | `16 passed in 2.52s`（首轮 `14 passed in 15.44s`） | 全绿（≥14 用例） | 通过 |
| **G2** | 契约层全量单测 | `90 passed in 2.42s`（首轮 `88 passed in 15.37s`） | 全绿（90 用例） | 通过 |
| **G3** | 跨层防污染回归 | `203 passed in 2.70s`（首轮 `201 passed in 17.47s`） | 全绿（203 用例） | 通过 |
| **G4** | AST 函数长度扫描 | `max = 39 lines`（首轮 `max = 32 lines`），超 50 行 = 0 | 严格 `< 50` 行 | 通过 |
| **G5** | 契约只读校验器 | `validate_json = True`，`validate(contract) = True` | True | 通过 |
| **G6** | 看门狗强校验 | `is_valid=True, verified=22, failed=0, skipped_6h=64, bypassed=False` | is_valid=True / failed=0 | 通过 |
| **G7** | M-5 四层资产口径 | `22 / 88 / 144 / 176, all_passed=True`（与审计文件存录一致） | all_passed=True | 通过 |
| **P1** | CLI 无 waiver 探针 | `exit=1`，`[FAIL-CLOSED] ... received: ''` 抛错阻断 | 抛错 + exit 1 | 通过 |
| **P1b** | CLI 占位 waiver 探针 | `--confirm-retest PLACEHOLDER` → `exit=1` 抛错阻断 | 占位符阻断 + exit 1 | 通过 |
| **函数名** | 误用全库排查 | `grep -rn "convert_v2_blindtest_to_contract"` → 0 命中 | 0 命中 | 通过 |
| **异常扫描** | 宽泛异常排查 | `except Exception` / 裸 `except` → 0 处 | 0 处 | 通过（M-3 闭合） |
| **禁区差分** | 禁区文件检查 | `git diff origin/main HEAD -- data/models/ registry.py version_watchdog.py` 为空 | 输出为空 | 通过 |
| **文件范围** | 提交白名单核验 | 严格仅 3 个新建白名单文件（+739 / -0），`physical_param_contract.json` 保持不变 | 仅白名单文件 | 通过 |
| **Push 纪律**| 分支与工作树状态 | `## main...origin/main [ahead 2]`，working tree clean，未 push | clean 且未 push | 通过 |

---

## 三、 修订条款落实核验

1. **函数名统一修正**：
   - 全库统一使用 `convert_csv_to_contract` 与 `export_contract_to_json`；
   - 彻底排查代码库与测试，零 `convert_v2_blindtest_to_contract` 误用。
2. **Fail-Closed 重写保险丝**：
   - 默认采用 `--dry-run` 安全模式（零写操作）；
   - 真实执行必须显式携带 `--confirm-retest <WAIVER_ID>`；
   - 启动期严格校验 `waiver_id` 非空且不得为 `TODO`、`NONE`、`PLACEHOLDER` 等占位符，否则立即抛出 `RetestPipelineError` 并以退出码 1 终止（P1/P1b 实测阻断）。
3. **异常家族收敛（M-3 结转项落地）**：
   - 实现三层异常体系：`RetestPipelineError`（基类）、`RetestExecutionError`（子进程调用）、`RetestAuditError`（转换/校验/M-5 门禁）；
   - 脚本内部实现**零 `except Exception`、零裸 `except:`**；所有底层 `ValueError`、`KeyError`、`CalledProcessError` 等均显式捕获并映射为流水线专属异常，禁止裸异常透传。

---

## 四、 M-5 四层资产口径勘定与留痕

在 `scripts/trigger_model_retest.py` 中内置 `reconcile_m5_asset_counts` 机械断言，且记录于 `evidence/audit_v2/retest_pipeline_audit.json`：

| 口径项 | 观测数值 | 判定标准 | 资产含义 |
|:---|:---:|:---:|:---|
| **法定消费参数格** | **22** | `len(contract.cells) == 22` | 第一类最高温离散参数格（双城 × 11 时效） |
| **法定落盘模型权重** | **88** | `len(contract.model_weights_sha256) == 88` | 2 站 × 11 lead × 4 季 × max（含 16 个 AUX 标签模型） |
| **交易法定主表模型** | **144** | `manifest non-aux models == 144` | 双城 12..72h 排除 32 个 AUX 备用后的主表模型（72 max + 72 min） |
| **看门狗完整性覆盖** | **176** | `manifest 12..72h models == 176` | 双城 12..72h 全量覆盖（88 max + 88 min，含全部 32 个 AUX 备用模型） |

---

## 五、 M-6 / M-7 交付状态缺陷整改记载

| 缺陷项 | 发现事实 | 整改措施与落地点 | 验证结论 |
|:---|:---|:---|:---|
| **M-6** | 运行单测时默认覆写库内审计文件，导致 `git status -sb` 脏污 | 在 `trigger_model_retest.py` 增加 `--audit-output` 支持；在 `test_trigger_model_retest.py` 中将单测产生的审计输出重定向至 `tmp_path` | 彻底切断单测对仓库生产证据目录的污染，全量跑数后工作树实测 100% clean |
| **M-7** | 审计文件中记录的 `git_commit` 在 amend 后变为孤儿悬空提交 | 审计文件采用 `dry-run` 终态（`status = "DRY_RUN_COMPLETED"`, `all_stages_passed = null`）；`git_commit` 严格锚定主历史线基线提交 `d320a18`；代码中显式声明该字段为“执行期基准 HEAD”法定语义 | 消除悬空孤儿引用，在 main 祖先链上完全可达 |

---

## 六、 观察项登记（O-1 ~ O-4）

1. **O-1（高价值可复现性信号）**：
   已提交的审计文件显示开发端曾以 `execute` 模式真实跑过 Stage 1/2，而 `evidence/audit_v2` 的两份 CSV 在 diff 中零变化，证明流水线重跑产出与既有证据高度自洽、确定性一致。
2. **O-2（内存对象端到端锚定）**：
   Stage 4 同时支持内存对象 `PhysicalParamTableValidator.validate(contract)` 与看门狗锚点核验 `ContractVersionWatchdog(contract=contract)`，消除了 dry-run 模式下依赖磁盘陈旧文件的缺陷。
3. **O-3（报告与差分对齐纪律）**：
   交付汇报中的 diffstat 数据必须严格与 `git diff origin/main HEAD --stat` 输出一致，严禁手写估算。
4. **O-4（审计留痕语义与上线流程）**：
   审计留痕文件兼顾执行痕迹与不可变性。当前库内保留规范化的 `dry-run` 完整性校验记录；后续在正式生产上线触发时，通过传入正式生产 waiver 进行一次端到端真实结算审计归档。

---

## 七、 签署与不可变声明

本单由复核方签发，结论：**Ticket 04（#137）首轮交付复核通过，具备关闭条件**。

> **本单为历史审计核验记录，一经签发永久冻结，正文与数值永不改写。**
