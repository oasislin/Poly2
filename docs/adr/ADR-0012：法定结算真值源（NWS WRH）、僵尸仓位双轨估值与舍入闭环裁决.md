---
created: 2026-09-19 23:45:00
updated: 2026-09-19 23:45:00
---
# ADR-0012：法定结算真值源（NWS WRH）、僵尸仓位双轨估值与舍入闭环裁决

- **状态**：Accepted
- **日期**：2026-09-19
- **裁决人**：量化工程团队
- **影响范围**：Phase 2 执行文件 v1.3（§1、§3、§5.1、§5.2、§6、§7）、结算复刻器（`src/settlement/`）、风控与资金管理模块（`bankroll_manager.py`、`alert_manager.py`）、系统配置规范（`default.yaml`）

---

## 1. 背景与冲突分析 (Context & Problem Analysis)

### 1.1 历史规范中的遗留冲突
在《Phase 2 执行文件 v1.3》中，仍保留着早期未经重铸的数据源学说与陈旧条款：
1. **结算源依赖倒挂**：§1 数据流图与 §5.2 双轨说明仍将 Wunderground 设定为次日结算真值提供方；
2. **Wunderground 系统性负偏差实证**：`ADR-0007` 经严格审计确证 Wunderground 存在 $-2.0^\circ\text{F} \sim -5.1^\circ\text{F}$ 系统性负偏差；Polymarket 在 Era 2 下的官方唯一法定结算源确立为 NWS WRH 官方时序表；
3. **结算时钟与僵尸仓位边界模糊**：原方案仅笼统提及“预期结算时刻宽限 12h”，未对全美三大时区当地自然日闭合、夏令时（DST 23h/25h）伸缩及预言机上链时延建立数学级严密契约；
4. **舍入边界未决（PENDING-01）**：浮点转整华氏度时，临界 .50°F 舍入口径悬而未决，潜藏错档巨亏隐患。

### 1.2 站点宇宙与元数据铁律
本裁决严格限定于 **Active 10 活跃高频交易站点宇宙**：
`KORD, KLGA, KATL, KDAL, KSEA, KLAX, KHOU, KMIA, KSFO, KAUS`（全部为日发报 $\ge 310$ 报的 NWS 原生台站）。
低频特例站 `KBKF`（日发报 25 报，`ADMITTED_TIER_3_WARNING`）忽略不纳入 Phase 2 主力交易；`KDCA` 彻底注销退役，严禁任何代码和接口引入。

---

## 2. 裁决决定 (Decisions)

### D1：确立 NWS WRH 时序表为唯一法定结算真值源与全要素提取规则
1. **法定结算真值地位**：系统正式确立 **NWS WRH 官方时序表（Time Series Tabular）** 为结算复刻器的唯一外部法定真值消费源；
2. **全要素报文提取规则（严格对齐 ADR-0009）**：提取各站当地自然日（00:00:00 至 23:59:59 Local Time）内所有有效温度观测值，**必须全量纳入常规整点报（Routine METAR）与特报（SPECI）**，严禁人为过滤丢弃特报极值：
   $$T_{\text{max\_settle}} = \max_{t \in \text{Day}} T(t), \quad T_{\text{min\_settle}} = \min_{t \in \text{Day}} T(t)$$
3. **备用源角色与自动化红线**：
   - **IEM ASOS 实时原报**：确立为**法医级影子审计底账（Forensic Shadow Audit Ledger）**；
   - **自动化绝对红线**：在 NWS WRH 页面缺失或失联期间，**绝对严禁任何自动化模块依据 IEM ASOS 数据自动向自由资金池（Free USDC）释放流动性或确认已实现盈亏**，彻底杜绝总账破裂（Broken Ledger）与虚假兑付穿仓。

### D2：物理时钟锚点、夏令时守恒与 12h 宽限期门禁
1. **物理时钟锚定点**：
   结算生命周期严格以站点所属 IANA 时区（`America/Chicago`、`America/New_York`、`America/Los_Angeles`）的自然日闭合点为准：
   $$T_{\text{settle\_expected\_utc}} = \text{to\_utc}(\text{date} + 1\text{d},\; 00:00:00,\; \text{tz}=\text{station.timezone})$$
   通过 Python `zoneinfo.ZoneInfo` 自动吸收春季 23 小时与秋季 25 小时的夏令时跳变，保持 UTC 轴单调守恒；
2. **12h 僵尸判定硬红线**：
   $$T_{\text{zombie\_trigger\_utc}} = T_{\text{settle\_expected\_utc}} + 12\text{ hours} \quad (\text{即各站当地次日中午 12:00:00})$$
   若超过该时刻链上仍未完成清算，仓位无条件移入 `Zombie Margin`；
3. **盘口元数据交叉验证**：
   若 Polymarket API 返回的盘口 `end_date_iso` 与物理锚点偏差 $> 24.0\text{h}$，立即触发 `MARKET_METADATA_MISMATCH`（WARNING 级），挂起自动结算并人工介入。

### D3：临界 .50°F 算术四舍五入规范与 PENDING-01 闭环
1. **强制算术四舍五入（Half-Up）**：
   气象学标准与 Polymarket 官方惯例严格遵从算术四舍五入。结算复刻器**严禁使用 Python 原生 `round()`（银行家舍入）**，必须强制使用 `decimal` 模块定点计算：
   ```python
   from decimal import Decimal, ROUND_HALF_UP

   def replicate_nws_temperature_rounding(temp_f: float) -> int:
       d = Decimal(str(temp_f))
       return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
   ```
2. **临界哨兵双向标记（Borderline Sentinel）**：
   若日内极值落在任意整数的 $[X.45, X.55]$ 闭区间内，复刻器自动打上 `BORDERLINE_CRITICAL` 告警标签，并输出进位与舍去双向期望沙盘；
3. **历史挂账闭环**：正式将 Phase 1.5 挂账 **`PENDING-01` 状态翻转为 `CLOSED_RULE_LOCKED`**。

### D4：四桶资金模型与“双轨制会计与风控模型”
四桶资金恒等式保持成立：
$$\text{Total Bankroll} = \text{Free USDC} + \text{Active Locked} + \text{Zombie Margin} + \text{Disputed Margin}$$
架构确立**双轨分离原则**：
1. **轨 1：下注母数轨（Trading & Kelly Sizing Book）—— 严格 0.0x 剔除**：
   在多项联合凯利优化器求解与单市场 10% 硬顶计算中，有效总资金基数 $\text{Bankroll}_{\text{effective}}$ 中，**Zombie Margin 与 Disputed Margin 一律计为 0.0x（完全清零扣除）**：
   $$\text{Bankroll}_{\text{effective}} = \text{Free USDC} + \text{Active Margin} \quad (\text{Zombie} \equiv 0,\; \text{Disputed} \equiv 0)$$
   **风控铁律**：不可流通的冻结资金绝对禁止作为下注安全垫，杜绝母数虚高引发连锁爆仓；
2. **轨 2：财务净值轨（Financial NAV Book）—— 动态期望折价计提**：
   维持账面净值平稳连续，防止虚假回撤熔断：
   - **Zombie Margin 估值**：$V_{\text{zombie\_mtm}} = 0.90 \times \mathbb{E}[V]$（扣除 10% 流动性冻结折价）；
   - **Disputed Margin 估值**：$V_{\text{disputed\_mtm}} = \min(0.50 \times \text{Cost}, \; P_{\text{true\_model}} \times \text{Shares} \times 0.60)$；
3. **流动性水位线分子剔除铁律**：
   全局流动性占用率计算：$\text{Utilization} = \text{Active Locked} / \text{Total Bankroll} \le 0.70$。`Zombie Margin` 与 `Disputed Margin` 坚决从分子中剔除；
4. **阶梯流动性熔断（名义僵尸率 $R_z = \frac{\text{Nominal Zombie} + \text{Nominal Disputed}}{\text{Total Bankroll}}$）**：
   - $R_z > 15\%$：新开仓额度强制折剪 $\times 0.5$；
   - $R_z > 30\%$：暂停新开仓，仅允许残局补单与硬止损；
   - $R_z > 50\%$：系统切入只读 `SAFE_MODE`，发出 CRITICAL 呼叫，人工介入处置。

### D5：Wunderground 遗留资产归档与绝缘防御
1. **代码物理迁移**：所有历史 WU 解析适配器物理迁移至受控隔离区 `src/legacy/wunderground/`，主干生产零依赖；
2. **运行时强力守卫**：类实例化必须显式探测环境变量 `ALLOW_LEGACY_WU_STRESS_TEST=1`，非压测沙盒直接抛出致命异常阻断；
3. **AST 静态扫描门禁**：在 CI 质检中加入静态检查，主干 `src/` 与常规 `tests/` 出现任何 `import wunderground` 立即红灯阻断构建。

---

## 3. 后果与架构收益 (Consequences)

### 3.1 正面收益
1. **彻底消除坏账破裂隐患**：通过封杀自动化 IEM 紧急兑付，杜绝了与链上真实清算脱轨导致的总账破裂；
2. **数学与时空严格守恒**：Decimal 半数进位与 ZoneInfo IANA 时区解析，消除了 Python 原生舍入与夏令时跳变带来的系统性误差；
3. **凯利资本绝对安全**：下注母数 0.0x 剔除切断了外部延迟向内部下注的风险传染链条；
4. **历史台账闭环**：正式彻底销号 `PENDING-01`，清空结算边界悬案。

### 3.2 下游任务与规范修订
1. 《Phase 2 执行文件 v1.3》正式标记吸收 ADR-0011 与 ADR-0012，修订 §1、§3、§5.1、§5.2 与 §7 测试套件；
2. Phase 2 开发任务中新增 `src/settlement/` 结算复刻器规范实现；
3. `BankrollManager` 实现双轨制会计核算逻辑。

---

## 4. 依据链接与事实源 (References)

- 基础裁决：`docs/adr/ADR-0007：数据源重铸与站点宇宙扩展（M0'  Round 5 综合裁决）.md`
- 特报语义：`docs/adr/ADR-0009：芝加哥 08-31 特报（SPECI）结算语义裁决与截断层规则.md`
- 合流风控：`docs/adr/ADR-0011：双源单调合流架构、TMAX-TMIN对称截断与两维阶梯风控裁决.md`
- 挂账闭环：`docs/reports/phase1.5-task03-pending-clearance.md`（PENDING-01）
- 执行规范：`docs/项目方案和执行文档/Phase 2 执行文件 v1.3：盘口定价、套利与执行引擎.md` (§1, §3, §5.1, §5.2)
- 总体方案：`docs/项目方案和执行文档/项目方案 (v2.6)：Polymarket 温度市场量化投注系统.md` (§5, §8.1, §8.2, §9)
