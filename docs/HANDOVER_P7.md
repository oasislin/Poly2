# 新会话冷启动交接清单 (docs/HANDOVER_P7.md)

> **文档性质**：新会话冷启动唯一交接引导包 (Handover Package)  
> **适用对象**：开启新会话的 Antigravity / Claude Agent 及项目维护者  
> **生效基准**：主干 `main` 严格锁定于 `5c4a4c9`（PR #132 合流线，包含 P7-W1-POOLPHASE 6h 池化相位重训与 Max 衰减补齐闭环，拔除运行旗 2）  
> **签发依据**：工单 `P7-W1-POOLPHASE` 与裁决书 `P7-W1-B-CLOSURE-VERDICT-R1`（技术裁决委员会终审结项裁决与拔旗令 P7-FLAG2-REMOVAL-R1）  

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
| **主干提交基准** | `main` 固化于 **`5c4a4c9`** | PR #132 合流提交，零未授权变更 |
| **全库测试基线** | **`1006 passed, 10 skipped, 0 failed`** | W1-A 衰减补齐 + W1-B 相位重训全量回归测试无退化 (634.74s) |
| **生效运行旗 (Flag 1)** | 🚩 `KMIA_12h`: `COMPLETED_ECE_FLAGGED` | 加权 ECE = `0.018318` 越线 0.0100，触发器计数 1/2 |
| **生效运行旗 (Flag 2)** | 🟢 `6h 池化回退层`: **`UNFLAGGED` (已拔除)** | 依据裁决令 `P7-FLAG2-REMOVAL-R1` 拔除：晨谷 ECE = `0.005977` 击穿 0.0100，膨胀比 `1.0000` |
| **后向议题全景** | **1 项已封卷 + 5 项注册中** | • `P6-POOL-PHASE`: `COMPLETED_SEALED` (工单 P7-W1-POOLPHASE 执结封卷)<br>• `P6-CALM-OUTLIER`: `REGISTERED` (防删条款维持)<br>• `P6-RESEARCH-NO-GATE-BIC`: `REGISTERED`<br>• `P6-RESEARCH-DIURNAL-PHASE`: `REGISTERED`<br>• `P6-TMIN-CV-LOCK`: `REGISTERED`<br>• `P7-STA-SURVEY`: `REGISTERED` |
| **W1 当前位次** | **已全量封卷 (COMPLETED_SEALED)** | PR #132 合流至 main，拔旗令生效，测试基线 1006 passed |
| **W2 开工条件** | **未就绪 (准备中)** | 须经委员会审批签署《Phase 2 短闭环预注册规格书》 |

---

## 三、 新会话当前唯一合法动作 (The Next Single Action)

> ⛔ **最高禁令**：在委托人下达明确指令前，**禁止执行任何未授权代码修改、禁止预分析任何新站、禁止静默实施任何 Backlog 议题**！

### 当前唯一标准动作：
**向委员会呈报 W1 全量结项封卷（P7-W1-POOLPHASE: COMPLETED_SEALED），合流入 main，准备开启 W2 短闭环预注册。**

---

## 四、 核心红线纪律重申 (Ironclad Rules)

1. **生产代码编辑须令（最高铁律）**：任何触碰 `src/` 与 `scripts/` 的动作，必须且仅能凭借委员会签发的正式工单，零令零改动；
2. **主干改动须新裁决令**：GitHub `main` 分支除委员会签发的合流裁决外，禁止任何直接 commit 或未经授权的 PR 合流；
3. **挂旗资产强制带旗引用**：下游调用 `KMIA_12h` 资产时，日志、报告与配置必须显式声明带旗，严禁脱旗裸用（原 `6h 池化回退层` 已依令拔旗解禁）；
4. **测试基线护航铁律**：任何代码交付必须输出全量自动化测试全绿执行凭证。

---

**交接包编制完成。请遵照本规程执行。**
