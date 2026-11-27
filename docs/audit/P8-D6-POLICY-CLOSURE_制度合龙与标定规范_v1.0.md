# P8-D6-POLICY-CLOSURE：制度合龙与标定规范（`v1.0` · `2026-11-21` `S2-03` 定版）

- **任务单与治理编号**：`S2-03`（`P8-WO-20261122-S203-D6`）｜归属模块：**`M6`（资金风控）/ `M8`（校准复检）**
- **文件增殖判据核验（[`AGENTS.md`](../../AGENTS.md)）**：全仓此前不存在独立承载 `D-6` 九项制度合龙规则、双轨定标门槛及破冻/灯→钱映射表的正式制度文件；若强制塞入 [`P8-KERNEL-CONSENSUS`](P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md)（战略共识）或 [`P8-CAPITAL-CONFIG`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md)（参数账本）将造成战略定稿、账本配置与月度考核制度职责混杂，故按判据合规单独立档。
- **法定锚点**：
  - [`P8-KERNEL-CONSENSUS §六 G`](P8-KERNEL-CONSENSUS_内核讨论定稿_v1.0_20261116.md#g下一桌-d-6-制度合龙议程登记只登记不开桌--2026-11-17)（`D-6` 九项制度议程清单）
  - [`P8-CAPITAL-CONFIG v1.0`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md)（资金三层结构、升降档、回撤闸与参数账本）
  - [`P8-T4-M4M5-INTERFACE v1.0 §3.1–§3.4`](P8-T4-M4M5-INTERFACE_决策与执行接口规格.md#三-本批正式确立协议正文p7p8p5-v10p6-v10)（`P7 / P8 / P5 v1.1 / P6`）
  - [`P8-RECORDER-NO-SIDE-DESIGN v0.1 §3.3`](P8-RECORDER-NO-SIDE-DESIGN_尾桶单侧与No侧双视角升级设计书_v0.1.md#33-d-6-标定输入升级yes--no-双侧盘口合并视图)（`YES_ONLY` vs `DUAL_MERGED` 双轨对照规范）
- **核心边界声明**：
  1. **本文件仅定版规则、口径、样本量门槛、双轨判定标准与审批程序，不含 `S2-02`（`D-A1` 实测拟合，绑定 `11-26` 后至少 `3–5` 天 `0.01` 时代录盘数据节点）**；
  2. **双冻结区绝对尊重**：严禁触发对 `src/pricing/`（`F-2`）及 `src/data_acquisition/passive_book_recorder.py` 的参数回写；一切在线参数迭代只能由 `M8` 生成建议并经人工签发新版 `P6 ExecutionPolicyBundle`；
  3. **解锁关系**：本卡闭合即满足 **`M6 (S3-06)`** 的全部制度前置依赖（可直接排期实施 `M6`）；**`M8 (S3-08)`** 除本卡外，仍严格以 **`S2-02`（`11-26` 后 `D-A1` 实测 `friction_median`）** 为并列前置。

---

## 一、 合龙主体三段（议程第 1 项 · 含分叉 3 首检收敛）

为解决原“训练→抽检→亮灯”与在线交易决策粒度断点，本制度将考核与灯控完全锚定于 **决策级四元组审计流（`P1 / P3 / P17 / P19`）+ 结算真值（`P9`）**：

### 1.1 抽检定义（决策级对齐与分叉 3 三项首检）

1. **抽检单位**：按 `execution_mode ∈ {"PAPER", "LIVE"}` 严格隔离，统计每个复检窗口（首期固定 **1 个自然月 = 30 天**）内全部已结算与已触发扫描事件：
   - 分母 A（预测校验池）：已结算市场之 `P17` 预测快照，对齐 `P9` 官方 `AWC routine METAR` 结算真值；
   - 分母 B（决策与执行池）：全部 `P1 ScanDecisionEvent`（含 `SKIP_EDGE_BELOW_M`、`IDLE_BUDGET_EXHAUSTED` 等完整负样本）与 `P3 ExecutionAttemptLog`。
2. **分叉 3 最小首检三条（月度复检与切换前必检，明确排除甜点 `lead` 定位与精细失效谱）**：
   - **(i) 校准门级读数**：计算已结算样本之池化 `ECE`（详见 §四 临界锚）、预测区间 95% 覆盖率及 $\sigma_\Delta$ 实测分位数；
   - **(ii) 原子方向性核查**：校验 `HurdleCdfBridge` 实盘/假盘四元组中边界档位 `p_bin_stay == p_model >= p_stay_phys`、死档全零，以及 `edge > m` 下单组的经验胜率相对市场隐含价的定向偏移是否符合先验方向（无系统性倒挂）；
   - **(iii) 日志完整性审计**：统计 `M7` 六条流（`P1/P3/P12/P17/P19/P13`）之 `corrupt_lines == 0`、`forecast_id / decision_id / attempt_id` 外键断链数 `== 0`，以及未明原因长时 `gap_detected` 占比。

### 1.2 亮灯规则（`GREEN / YELLOW / RED` · 三态互不重叠）

| 灯级 | 触发判定条件（采用逻辑“且/或”最严先判：`RED` 优先于 `YELLOW`） | 典型归因方向 |
| :--- | :--- | :--- |
| **`RED`（红灯 · 停止开仓）** | 满足任一：① 月度池化 `ECE > ECE_RED_ANCHOR`（`0.040`，见 §四）；② 触发本地 `$500/站` 亏损闸或 `25%` 全盘回撤硬刹车；③ 审计发现未闭合外键断链、跨 `execution_mode` 污染、或隐蔽静默实盘滑点超出安全垫 `2×`；④ `oracle_compliant == False` 观测污染进入生产决策 | 模型严重失配 / 资金风险越界 / 基础设施破坏性故障 |
| **`YELLOW`（黄灯 · 受限减额）** | 未触 `RED` 且满足 §五 三类黄灯分型任一（① 信息/样本不足型；② 轻度校准偏离型 `ECE ∈ (0.020, 0.040]`；③ 非致命基础设施降级型） | 统计把握不足或轻度偏离，可继续观测但须收缩单注门槛/额度 |
| **`GREEN`（绿灯 · 全额正常运行）** | 当月已完成最小有效样本检验、`ECE <= 0.020`、无未关闭结构性审计故障且资金闸门全绿 | 允许按当前阶梯全额执行，并计入连续两绿灯升档计数 |

### 1.3 灯→钱映射表（双播 `M4 + M6`）

| `P16 LightLevel` | `M4` 决策门限额调整 | `M6` 资金侧行为 | `P19` 记录要求 |
| :--- | :--- | :--- | :--- |
| **`GREEN`** | `yellow_multiplier = 1.0`（全额 $G = B \cdot w(\tau) \cdot [s(\text{edge}) \cdot \lambda(L)]$，$\lambda(\text{GREEN})=1.0$） | 正常 `P7 QuotaSnapshot` 放行；月度绿灯计 `1` 次 | `LIGHT_LEVEL_APPLIED` (`light_status="GREEN"`) |
| **`YELLOW`** | 乘性半额 **`yellow_multiplier = 0.5`**（$G = B \cdot w(\tau) \cdot [s(\text{edge}) \cdot \lambda(L)]$，$\lambda(\text{YELLOW})=0.5$，见 §六） | 正常释放已结算头寸，冻结升档计数并重零起算 | `LIGHT_LEVEL_APPLIED` (`light_status="YELLOW"`) |
| **`RED`** | **`yellow_multiplier = 0.0`**（$G = B \cdot w(\tau) \cdot [s(\text{edge}) \cdot \lambda(L)]$，$\lambda(\text{RED})=0.0$，拦截一切新开仓） | 冻结全部新开仓预冻结 `P14 FREEZE`，禁止新占用 | `LIGHT_LEVEL_APPLIED` (`light_status="RED"`) |

---

## 二、 月度复检例程与三层防遗忘机制（议程第 2 项）

依据 [`P8-CAPITAL-CONFIG §7`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#7-参数账本全案占位参数统一登记表--2026-11-17) “测量自动、换版人工、月度节奏”铁律，确立三层防遗忘流程：

1. **第一层（机器自动定时触发与议程展开）**：每个自然周期（30 天）到期 UTC 次日 `00:15Z`，`M8` 离线例程自动经 **`P8 CalibrationAggregateBatch`** 读取只读四元组日志，按参数账本清单逐项对比实测分布与当前冻结值，生成《月度参数替换与亮灯建议单》（只读提案，不改线上代码）。
2. **第二层（达标样本触发人工签发，双签名入新 `P6`）**：当待调参数均满足 §八 最小样本量门槛且经所有者（人工）审阅签发后，由 `M8` 工厂生成新版本 `P6 ExecutionPolicyBundle`（刷新 `policy_version` 与 `config_hash`，`is_overdue=False`）并通过 `P16` 广播生效。
3. **第三层（超期保守续持 + 强制 `policy_overdue=True` 催办，对齐 `B6`）**：若月度窗口到期后 **未获人工响应**，系统 **严禁静默自动切参、亦严禁自动降额停机**；必须继续原样沿用上一期冻结 `P6` 参数组，但将下发/标记字段置为 **`is_overdue=True`**，同时在 `P1 / P3 / P19` 每条日志写入 `policy_overdue=True` 标记（并在 `P8 CalibrationAggregateBatch.policy_overdue_ratio` 与 `M10` 前台告警条持续置顶催办）。

---

## 三、 `GATE-LIVE` 真盘切换门三条件（议程第 3 项 · 插入 `S3-11` 之后）

从 `T9`（`S3-11` 冻结假盘）切换至实钱 `LIVE` 模式，必须同步通过以下 **全部三项定量检验与人工签发**：

1. **条件 1（物理与执行样本门槛）**：
   - 冻结假盘连续运行 **`>= 14` 个日历日**（或覆盖 **`>= 30` 个已结算站-日市场**），且已录得 **`>= 20` 笔** 经 `P18` 真实延迟帧撮合（`capture_replay_mode="REPLAY_P13"`）的模拟成交记录（`FILLED` 或 `PARTIAL`）；
   - **`RiskGatePolicy.friction_median is not None`**（已完成 `S2-02` `0.01` 时代录盘实测填值），且假盘实测 `median(slippage_vs_best_ask)` 未显著击穿当前冻结 `m_threshold` 安全垫（要求实测滑点中位数 `<= 1.25 ×` 预设 `friction_median`）。
2. **条件 2（模型稳定性与协议无缺陷）**：
   - `P1 / P3 / P12 / P17 / P19` 四元组及旁路日志中，`corrupt_lines == 0`，未捕获跨时区/因果越界/死档非零违规 `== 0`；
   - `P8` 统计之池化校验 `ECE <= 0.025`（放宽于成熟期 `0.020` 红线，但严格守住不进 `RED` 区间），且 `P18` 回放中除明确记录之外网重连外无未知长时间静默间隙。
3. **条件 3（防污染 `A` 类切盘与人工签署）**：
   - 切换真盘严格执行 `A` 类变更语义：**`model_hash` 保持与假盘期完全一致（不破冻）**，`P19` 记录事件 `event_type="GATE_LIVE_SWITCH"`；
   - `S3-12` 须由所有者在审阅 `GATE-LIVE` 检验报告后显式人工批准签发，严禁任何脚本自动切换 `LIVE`。

---

## 四、 `ECE` 临界锚（议程第 4 项）

延续检验 C（`2019-SEALED-001`）口径 `G3c_ece_bridge_inw <= 0.02`，正式建立两级临界锚：

| 锚点名称 | 定量阈值（池化 20 桶 / 反方差加权 `ECE`） | 语义与制度动作 |
| :--- | :---: | :--- |
| **`ECE_GREEN_ANCHOR`** | **`<= 0.020`** | 满足长期校准健康标准（对应 `G3c`）；当样本达标时维持 `GREEN` |
| **`ECE_YELLOW_BAND`** | **`(0.020, 0.040]`** | 轻度校准偏离带；触发 **B 型黄灯（轻度偏离）**，执行 `0.5x` 半额并安排月末重点复核（需结合分叉 3 原子方向性检查确认是否为单边气候漂移） |
| **`ECE_RED_ANCHOR`** | **`> 0.040`** | 严重校准失准红线；立即经 `P16` 切换为 `RED` 阻断新开仓，触发破冻评估流程（§七） |

---

## 五、 黄灯分型（议程第 5 项）

所有 `YELLOW` 状态必须携带明确枚举分型（写入 `P16 LightLevelEvent.reason` 与 `P19`）：

1. **`YELLOW_INSUFFICIENT_SAMPLE`（信息/样本不足型）**：复检窗口内已结算样本不足 §八 最小样本门槛（如 `< 30` 站-日或 `< 15` 笔可校验成交），无法证伪亦无法确证校准完好；
2. **`YELLOW_MILD_CALIBRATION_DRIFT`（轻度校准偏离型）**：`ECE ∈ (0.020, 0.040]` 或 `M_now` 日界截尾偏差落入 `(0.5°F, 1.5°F]` 观察带，但尚未触及 `RED` 阈值或方向倒挂；
3. **`YELLOW_INFRA_DEGRADED`（非致命基础设施降级型）**：例如部分时段发生短期 AWC/WSS 重连导致非致命缺口（`gap` 率超出正常基线如 `> 2%` 但 `< 10%`）、或 `DUAL_MERGED` 单侧偶发断流需退回保守基线，均以半额保护运行同时不彻底停机。

---

## 六、 黄灯半额精确定义与 `yellow_multiplier` 作用点（议程第 6 项）

正式闭合 [`P8-T4-M4M5-INTERFACE v1.0 §3.4`](P8-T4-M4M5-INTERFACE_决策与执行接口规格.md#34-p6-executionpolicybundle-v10m8--m4--m5--m7--由-rc-正式成文) 与 [`src/decision/engine.py`](../../src/decision/engine.py) 预留之 `yellow_multiplier` 作用点：

1. **数值与作用公式（乘在机会缩放因子 `s(edge)` 侧，经门限额 $G$ 统一传导）**：
   $$G = B \cdot w(\tau) \cdot \big[s(\text{edge}) \cdot \lambda(L)\big]$$
   其中灯级乘子 $\lambda(L)$ 定义为：
   - $\lambda(\text{GREEN}) = 1.0$
   - $\lambda(\text{YELLOW}) = 0.5$（当 `P16` 当前有效灯级为 `"YELLOW"` 且 `RiskGatePolicy.yellow_multiplier = 0.5`）
   - $\lambda(\text{RED}) = 0.0$（不参与后续下单，直接触发阻塞/停开仓枚举）
2. **禁止双扣与超门不变性**：
   - 不得同时把 `0.5` 再乘在站限 `station_cap_usd` 或 `B` 上导致双重四分之一缩额（`B` 仍保持 `station_cap / concurrent_days` 供审计对照，`headroom_d = min(G - held_usd, b_eff_headroom_usd)`）；
   - 当灯级从 `GREEN` 切至 `YELLOW` 导致已持有头寸 `held_usd > G_yellow` 时，遵循 **超门不自动平仓原则**（`P8-CAPITAL-CONFIG §6.4`），`headroom_d = 0`（输出 `IDLE_BUDGET_EXHAUSTED`），仅阻止继续加仓而不主动卖出减仓。
3. **现役代码落点提示**：现役 `src/decision/engine.py` 已实现 `RiskGatePolicy.yellow_multiplier` 与 `P16SubscriptionSlot.latest_event.level` 透传字段；待后续编码对齐时（`S3-06` 或轻量对齐单），按上述单一公式落入 `DeterministicDecider._compute_g_cap` 即可。

---

## 七、 破冻程序、 `A` 类可追加性与真盘首期额度确认（议程第 7–9 项）

1. **破冻程序（议程第 7 项）**：
   - 触发场景：遭遇 `RED` 校准红线、`B` 类逻辑越界缺陷或重大外部结算规则变更必须修改模型/门控核心代码或重新拟合已冻结之特征权重；
   - 四步强制程序：**① 立即单向止血**（经 `P16` 发 `RED` 或调用紧急降额，停止新开仓）$\to$ **② 现场封存与故障单归档**（锁定原 `model_hash` 期间全部 `M7` 日志作复盘基准，禁止回改历史日志）$\to$ **③ 离线修改、单测与回归验证**（变更 `model_hash` 并在受控分支通过全量门禁）$\to$ **④ 人工审批破冻重上假盘或复核切真盘**（写入新 `model_hash` 与新冻结周期编号 `freeze_cycle_id`）。
2. **`A` 类变更之可追加性（议程第 8 项）**：
   - `A` 类清单（不破冻可随时热修）允许后续随工程运维演进通过治理登记动态追加条目，但新增条目必须**逐字满足否定检验**：① 不改变 `M2` 物理先验与条件桥数值输出；② 不改变 `M4` 门槛 `m_threshold` / `s(edge)` / `w(τ)` 表达式；③ 不改变 `M5` 切片 `φ` 逻辑与风控硬闸计算；④ 不删减 `P1–P19` 因果与审计必需字段。典型合法追加项：监控脚本 `S3-13`、日志压缩轮转工具、RPC/WSS 断线重连稳健性补丁、只读 UI 视图。
3. **真盘首期额度确认（议程第 9 项）**：
   - 正式确认 [`P8-CAPITAL-CONFIG §2`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#2-升降档规则与首期额度当前决策--2026-11-17) 默认条款：**真盘切换首期（`S3-12` 通过后首月）按当期总部署配置下的默认站点全额执行（单站上限 `$500 / 站`，单市场日预算占位 `$250`）**；不额外硬编码强制减半启动，但所有者保留在签署 `S3-12` 批准单时随时附加单向收紧上限（如初期总部署先开 `$2,000` 覆盖 4 站）之权力。

---

## 八、 定标规则、最小样本量门槛与 `11-26` 后 `S2-02` 实测绑定口径

本节明确后续 **`S2-02`（`11-26` 后启动）** 及 **`S4-01`（月度复检）** 拟合各占位参数时的法定公式、统计口径与最小样本门槛（**本批零拟合**）：

| 待定标对象 | 法定拟合规则与无量纲口径 | 最小样本量门槛（未达标则保持原值 + 必要时标样本不足黄灯） | 数据源流 |
| :--- | :--- | :--- | :--- |
| **`friction_median`**（`D-A1` · **`S2-02` 核心产出**） | 先基于 `2026-11-21` 起 `>=3–5` 天 `0.01` 时代 `P13` 录盘以模拟切片订单按 `P18` 规则走簿计算 `(exec_vwap - best_ask) / best_ask` 之中位数填入首期上线值；首月后替换为实盘/假盘实际 `P3.slippage_vs_best_ask` 中位数（严禁含 spread，统一相对比例） | 离线录盘走簿：`>= 200` 次有效深度模拟切片覆盖至少 `4` 个站、连续 `>= 72h` `0.01` 时代录盘；在线 `P3` 替换：`>= 30` 笔实成交通道样本（`FILLED`/`PARTIAL`） | `S2-01 P13` $\to$ `P3` |
| **`σ_Δ` 与 `k₀`** | 统计 `P17.sigma_delta_sample`（相邻预报更新/日内残差离散度）之稳健离散估计（如 `IQR / 1.349` 或截尾标准差）；首期占位 `k₀ = 2.0`，首次月度复检按实测分布重评门槛有效性 | `>= 60` 个独立 `(station_id, target_date)` 已结算日样本（跨至少 `2` 个周周期） | `P17` + `P9` (`P8`) |
| **`p`（`w(τ)` 曲率）与 `w₀`** | 计算按时段空转率 $\text{idle\_rate}(\tau) = \frac{\#(\text{edge} \ge m \land \text{IDLE\_BUDGET\_EXHAUSTED})}{\#(\text{edge} \ge m)}$ 与早/晚下单盈亏归因；`w₀` 同步绑定 `D-A2` 官方 `min_order_size` 校验 | `>= 100` 次 `edge >= m` 过线扫描事件且覆盖早中晚三时段（每段 `>= 20` 次） | `P1` + `P3` + `P9` (`P8`) |
| **`ρ₀` 与 `k`（`φ` 参数）** | 按 `P3.slippage_vs_est_vwap` 与 `P3.fill_rate` 对齐评估；只有当 `ρ₀` 首期稳定运行且实际吃深完成率显著不足或冲击过低时方可开启 `k > 0` | `>= 30` 笔 `P3` 有效下单尝试 | `P3` (`P8`) |
| **`M_now` 日界/量化补偿** | 执行 `D-A3b` 三闸：采集日内截尾残差中位数，严格单侧钳制 `[0, 2°F]`，人工审阅批准前在线维持 `0` | `>= 30` 个已结算站-日样本对 | `P12/P11` + `P9` |

---

## 九、 `DUAL_MERGED` vs `YES_ONLY` 双轨判定标准（衔接 `NO-SIDE-DESIGN §3.3`）

依据 [`P8-RECORDER-NO-SIDE-DESIGN v0.1 §3.3`](P8-RECORDER-NO-SIDE-DESIGN_尾桶单侧与No侧双视角升级设计书_v0.1.md#33-d-6-标定输入升级yes--no-双侧盘口合并视图)，`S2-02`（`D-A1` 标定）与 `S3-11`（假盘）阶段强制并行统计 **`YES_ONLY`** 与 **`DUAL_MERGED`** 两列视图：

### 9.1 四项并行度量指标

1. **`wing_bin_ask_availability_pct`**：尾桶档位（如模型概率 $p \in [0.02, 0.25]$ 且直盘出现 `single_side="bid_only"` 的合约）上，经 `DUAL_MERGED` (`Ask(YES) ∪ (1 - Bid(NO))`) 回填后有效可卖盘口覆盖率 vs `YES_ONLY` 覆盖率；
2. **`qualified_depth_gain_ratio`**：合格深度增长比 $\frac{\text{qual\_depth}_{\text{DUAL\_MERGED}}}{\max(\text{qual\_depth}_{\text{YES\_ONLY}}, \epsilon)}$（按站与档位分布）；
3. **`friction_median_yes_only` vs `friction_median_dual_merged`**：两轨道走簿滑点中位数及其差值分布（评估并入 `NO_BID_SPLIT_SELL` 对滑点的改善或劣化）；
4. **`complement_spread_tightness`**：统计同期双边均非空帧上 $\text{best\_ask}_{\text{YES}} + \text{best\_bid}_{\text{NO}} - 1$ 分布及 `CROSS_VIEW_INVERTED_SPREAD` 拦截率（验证补集紧密性与行情异步偏斜 `pair_max_skew_sec`）。

### 9.2 轨道启用判定标准（分环境硬隔离）

| 运行环境 | 轨道启用默认与切换判定标准 | 安全护栏与阻塞线 |
| :--- | :--- | :--- |
| **`S2-02`（离线标定基准）** | **强制双轨并行产出报告**；若统计显示 `DUAL_MERGED` 相比 `YES_ONLY` 使尾桶覆盖率绝对提升 `>= +10%` **或** 合格深度中位增益比 `>= 1.25`，但跨侧倒挂告警率 `<= 1%` 且无结构性虚高滑点，则以 `DUAL_MERGED` 作互补潜力参考、以实际可上线交易路径对应的口径填实 `friction_median`（原则上：**若实盘短期不开拆合路由，上线 `P6.friction_median` 必须按实盘真实执业轨道 `YES_ONLY` 取稳健值，严禁拿理想化双边低滑点给仅走单边 `YES` 的实盘定低门槛**） | 严禁“用双边低摩擦定低门槛，却让实盘在 `YES_ONLY` 吃高滑点” |
| **`S3-11`（`PAPER` 假盘）** | 默认并行运行两套对比统计（主账户记 `DUAL_MERGED` 或 `YES_ONLY` 单一口径，镜像流记录另一侧对照 `slippage / depth` 改善量） | `NO_BID_SPLIT_SELL` 帧必须同步通过 `NO` token `P18` 无 gap 检查 |
| **`S3-12 / LIVE`（实盘）** | 默认保持 `enable_cross_side_split_routing=False`（仅走 **`YES_ONLY`** 原生直盘或待接入原子 `BUY NO @ 1-p` 撮合路由）；**仅当**：① Polygon pre-split/原生互补单在 `M5` 实盘网关完整实现并经实测验证 gas/延时预算可接受；② 双轨实测正期望增益扣除链上成本后仍稳健为正；③ 所有者显式批准开关，方可切入 `DUAL_MERGED` 实盘路由 | 在异步链上 `splitPosition` 未原子化前，**绝对禁止在实盘默认打开 `NO_BID_SPLIT_SELL` 拆合路由** |

---

## 十、 对 `M6 (S3-06)` 与 `M8 (S3-08)` 的解锁核对声明

- **对 `M6 (S3-06)`（三层资金风控机与本地硬刹车）**：依据台账，`S3-06` 唯一前置依赖为 `S2-03`。本文件发布并经本次验收闭合后，**`M6 (S3-06)` 开工前提完全解锁**（可直接落实 `$500/站`、`25%` 激活回撤硬刹车、`P7` `b_eff_headroom_usd` 超并发兜底、`P14 / P15 / P16` 消费、`P19` 流水写入及 `yellow_multiplier = 0.5` 到门限额的乘法落实）；
- **对 `M8 (S3-08)`（参数账本与 `P6` 签发器）**：本文件闭合其制度与三层防遗忘例程前置（`§二、§八`），但 **`M8 (S3-08)` 仍并列依赖 `S2-02`（需待 `2026-11-26` 后获取 `>= 3–5` 天 `0.01` 时代录盘实测 `friction_median`）**；`S3-08` 中关于 `friction_median is None` 的阻断门控与 `is_overdue=True` 保守续持代码逻辑可在 `S3-08` 排期时先基于 `None` 阻断门进行离线构建与单测，上线签发严格锁定 `S2-02` 完成之后。
