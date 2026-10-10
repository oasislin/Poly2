# 新会话冷启动交接清单 (docs/HANDOVER_P7.md)

> **文档性质**：新会话冷启动唯一交接引导包 (Handover Package)  
> **适用对象**：开启新会话的 Antigravity / Claude Agent 及项目维护者  
> **生效基准**：主干 `main` 严格锁定于 `122d872`（PR #131 合流线，包含 P7-DOC-RECON 规格对账闭环；锚点之上的 docs-only 修正 9cdd631 不触发指针升版）  
> **签发依据**：工单 `P7-TRANSITION-DOC` 与 `P7-DOC-RECON`（技术裁决委员会立项会终裁与合流批文 P7-DOC-RECON-GO-MERGE）  

---

## 一、 新会话强制有序阅读清单 (Read Order)

新会话启动时，Agent **严禁自由发挥或尝试反向推演历史对话**。必须严格依照以下四步顺序物理读取仓库核心法定文档：

1. **第一步：读取 [`STATUS.md`](../STATUS.md)**  
   - *目的*：明确“我们现在在哪”。确认当前处于 Phase 7 过渡态、主干固化 Hash、活跃工作流与双重运行旗（核心方案已升级至 `v2.8`，执行文件升级至 `v2.1`）。
2. **第二步：读取 [`docs/ROADMAP.md`](ROADMAP.md)**  
   - *目的*：明确“我们要去哪、为什么这么走”。理解由“横向扩展”向“纵向落地”的战略转向逻辑链、三波次路线图（W1 $\to$ W2 $\to$ W3）及治理纪律。
3. **第三步：读取 [`evidence/p6_tmax_methodology_closure.md`](../evidence/p6_tmax_methodology_closure.md)**  
   - *目的*：明确“现役物理地基是什么”。掌握双城 TMax 24 时间格唯一事实层对账表、昼夜谐波机制外推、两段式家族选择披露及已知限制。
4. **第四步：读取 [`docs/HANDOVER_P7.md`](HANDOVER_P7.md)（本文件）**  
   - *目的*：明确“当下唯一可执行动作是什么”。锁定开工前置条件与红线禁令。

---

## 二、 系统当前状态速览卡 (System State Flashcard)

| 核心维度 | 当前法定状态 | 权威核验依据 / 索引指针 |
| :--- | :--- | :--- |
| **主干提交基准** | `main` 固化于 **`122d872`** | PR #131 合流提交，零未授权变更（docs 修正 9cdd631 维持锚点） |
| **全库测试基线** | **`1000 passed, 10 skipped, 0 failed`** | W1-A 补齐衰减后全量回归测试无退化 |
| **生效运行旗 (Flag 1)** | 🚩 `KMIA_12h`: `COMPLETED_ECE_FLAGGED` | 加权 ECE = `0.018318` 越线 0.0100，触发器计数 1/2 |
| **生效运行旗 (Flag 2)** | 🚩 `6h 池化回退层`: `FLAGGED_POOL_PHASE_ISSUE` | 晨谷方差膨胀比 1.45~1.81x，KMIA 晨谷 ECE = `0.019657` 越线 |
| **后向议题全景** | **1 项进行中 + 5 项注册中** | • `P6-POOL-PHASE`: `IN_PROGRESS_W1` (W1-A 完成，W1-B 推进中)<br>• `P6-CALM-OUTLIER`: `REGISTERED` (防删条款维持)<br>• `P6-RESEARCH-NO-GATE-BIC`: `REGISTERED`<br>• `P6-RESEARCH-DIURNAL-PHASE`: `REGISTERED`<br>• `P6-TMIN-CV-LOCK`: `REGISTERED`<br>• `P7-STA-SURVEY`: `REGISTERED` |
| **W1 当前位次** | **串行位次 1/4 结项中** | W1-A 生产代码与测试验收通过，正在执行 P1~P3 落地 |
| **W2 开工条件** | **未就绪 (阻塞中)** | 须经委员会审批签署《Phase 2 短闭环预注册规格书》 |

---

## 三、 新会话当前唯一合法动作 (The Next Single Action)

> ⛔ **最高禁令**：在委托人下达明确指令前，**禁止执行任何未授权代码修改、禁止预分析任何新站、禁止静默实施任何 Backlog 议题**！

### 当前唯一标准动作：
**严格依照串行纪律⑥完成 W1-A 结项落地（P1~P3），随后解锁串行位次 2/4（Rev.3-Addendum）。**

---

## 四、 核心红线纪律重申 (Ironclad Rules)

1. **生产代码编辑须令（最高铁律）**：任何触碰 `src/` 与 `scripts/` 的动作，必须且仅能凭借委员会签发的正式工单，零令零改动；
2. **主干改动须新裁决令**：GitHub `main` 分支在 `122d872` 处已冻结，除委员会签发的合流裁决外，禁止任何直接 commit 或 PR 合流；
3. **挂旗资产强制带旗引用**：下游调用 `KMIA_12h` 或 `6h 池化回退层` 资产时，日志、报告与配置必须显式声明带旗，严禁脱旗裸用；
4. **测试基线护航铁律**：任何代码交付必须输出全量自动化测试全绿执行凭证。

---

**交接包编制完成。请遵照本规程执行。**
