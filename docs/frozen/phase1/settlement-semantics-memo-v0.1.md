<!-- FROZEN ARTIFACT / 只读冻结产物 -->
> **[FROZEN ARTIFACT / 只读冻结产物]**
> 本文档系 Phase 1 阶段（M0' 结算站点审计与评估）交付之基线冻结产物，内容严格只读。
> 任何修改、修订或废止必须通过正规 ADR 裁决流程推进，禁止直接变更既有文本。

# 📝 Polymarket 温度市场结算语义与边界取证备忘录（v0.1 - 已废止归档）

> [!WARNING]
> **DEPRECATED / 已废止归档**：本文档为早期初稿草案，已被 [`docs/reports/appendix-a-settlement-semantics-memo.md`](./appendix-a-settlement-semantics-memo.md) 正式替代并确立为唯一规范源。所有状态字段与实现决策均以附录 A 为准，本文档仅作历史存档保留。

> **生成时间**：`2026-09-03 18:29:36 UTC`  
> **历史使命**：对夏令时（DST）、缺测降级、以及 ASOS CLI vs 离散 METAR 口径冲突进行早期法律与工程级取证。

---

## §1 夏令时（DST）日界划分语义取证
- **时区基准**：Polymarket 规则中结算日期严格按**标的站点本地日历日（00:00:00 至 23:59:59 Local Time）**定义，非 UTC 日；
- **春季跳跃周（Spring Forward, 23 小时日）**：01:59:59 跳至 03:00:00，质控自适应适配 23 小时预期发报量；
- **秋季回拨周（Fall Back, 25 小时日）**：01:00 重复两次，时间戳严密附带 ISO 8601 本地时区偏移（如 `-04:00`/`-05:00`）。

## §2 缺测断流与 Fallback 降级语义取证
- **三级降级路径**：主源 NWS WRH -> 一级降级 Weather Underground 日表 -> 二级降级判入最低阶梯 (Lowest Bracket)；
- **极端违约风险**：整日无数据判入最低阶梯构成黑天鹅，若日内 15:00 缺测超 2 小时自动触发平仓与套保防线。

## §3 NWS CLI 气候日报 vs 离散 METAR 口径冲突取证
- **硬件与算法冲突**：CLI 内置硬件最高温度计连续极值与离散 METAR 有约 $15\% \sim 25\%$ 概率出现 $\pm 1^\circ\text{F}$ 偏差；
- **Polymarket 法定口径**：规则明文规定以 *"highest reading under the 'Temp' column for all times on this day... WRH timeseries"* 为准；
- **裁决结论**：**Polymarket 严格采信 NWS WRH 网页时序表中的离散发报值，非 NWS CLI 日报！** 模型定价与回测必须以 WRH 离散 METAR 序列为基准。

## §4 'Show Hourly Data' 按钮的离散过滤效应（实证关键）
- **规则条款**：*"This market will resolve off of the Hourly Data provided using the 'Show Hourly Data' button."*
- **实测实证**：2026-09-02 芝加哥（KORD），13:30 高频 5 分钟报曾录得 96.8°F，但 13:51 整点报仅为 95.0°F；市场最终以 **94-95°F** 获胜结算；
- **风控铁律**：定价系统与结算复刻器必须严格复刻“Show Hourly Data”筛选（仅保留正点前后的整点 METAR），严禁盲目采用全量 5 分钟 SPECI 突发峰值，否则将在高频毛刺上发生方向性误判。

## §5 四舍五入悬崖效应（The Rounding Cliff）与离散积分
- **规则条款**：*"measures temperatures to whole degrees Fahrenheit (eg, 21°F)... rounded to nearest whole degree"*；
- **微小扰动跃迁**：$87.49^\circ\text{F}$ 舍入为 87°F（落在 86-87°F 区间），而 $87.50^\circ\text{F}$ 进位为 88°F（落在 88-89°F 区间）；
- **期权定价风险**：$0.01^\circ\text{F}$ 的传感器测量本底噪音将导致二元期权 Payoff 发生 0% 至 100% 的阶跃突变。模型在区间临界点必须通过核密度平滑积分（Kernel Smoothing）控制下注敞口，严禁在 .50 边缘满仓下注。
