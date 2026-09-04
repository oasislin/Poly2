# 附录 A：Polymarket 温度市场结算语义与量化边界备忘录（完整版）

> **生成时间**：`2026-09-03 18:29:36 UTC`  
> **核心定位**：提供法律与工程级结算边界规则，作为结算复刻器（Settlement Replicator）的唯一规范源。

---

## §1 夏令时（DST）日界划分语义
- **时区基准**：Polymarket 结算日期严格以**标的站点本地日历日（00:00:00 至 23:59:59 Local Time）**定义，严禁使用 UTC 切片；
- **春季跳跃日（Spring Forward, 23 小时日）**：01:59:59 跳至 03:00:00，质控逻辑自适应适配 23 小时预期发报量；
- **秋季回拨日（Fall Back, 25 小时日）**：01:00 重复两次，所有数据结构必须严格带本地时区偏移（如 `-04:00`/`-05:00`）。

## §2 三级 Fallback 降级链与避险状态机
- **三级降级路径**：
  1. **主源 (Primary)**：NOAA NWS WRH 离散时序表 (`site=<stid>`)；
  2. **一级降级 (Secondary)**：Weather Underground 日历日汇总表；
  3. **二级降级 (Tertiary)**：全日缺测判定进入最低阶梯（Lowest Bracket）；
- **避险风控门禁**：若本地时间 15:00 发生持续缺测超 2 小时，执行系统自动撤单并套保平仓，杜绝最低阶梯黑天鹅结算。

## §3 NWS CLI 气候日报 vs METAR 离散时序表口径冲突
- **口径偏差**：CLI 硬件最高温度计与整点离散报文在历史上有 $15\% \sim 25\%$ 概率出现 $\pm 1^\circ\text{F}$ 偏差；
- **法定口径**：Polymarket 规则明文定义结算值取自 *"highest reading under the 'Temp' column for all times on this day... WRH timeseries"*；
- **工程结论**：**法定口径为 WRH 离散报文极值，非 NWS CLI 日报！** 历史标签重采样必须从 METAR 报文流推导日极值。

## §4 'Show Hourly Data' 按钮的离散过滤机制
- **规则条款**：*"This market will resolve off of the Hourly Data provided using the 'Show Hourly Data' button."*
- **实测实证**：2026-09-02 芝加哥（KORD），13:30 高频 5 分钟 SPECI 突发峰值达 96.8°F，但 13:51 整点报为 95.0°F；市场最终以 **94-95°F** 获胜区间结算；
- **工程实现**：复刻器必须严格按正点窗口（`:50-:55` 及 `:00`）筛选整点报文，过滤高频毛刺。

## §5 四舍五入悬崖效应（Rounding Cliff）与舍入规则状态说明
- **规则条款**：*"measures temperatures to whole degrees Fahrenheit (eg, 21°F)... rounded to nearest whole degree"*；
- **舍入机制与边界状态审计**：
  - `status: ASSUMED` (实现选择正确，两判例自洽) | `evidence: 2026-09-01 (80.60->81°F), 2026-09-02 (73.94->74°F)`；
  - **论证修正**：实测 WRH 时序表页面原样显示两位小数（如 73.94°F、88.88°F），页面展示层并未发生 JS 舍入，舍入系 UMA 决议人依据规则文本（"rounded to nearest whole degree"）人工/算法执行；
  - **工程实现选择**：系统按标准 Half-Up 假设实现（`np.floor(x + 0.5)`），与上述真实判例完全自洽；收回此前"100% 数学定论"措辞；
  - `status: PENDING` (边界行为待验) | `evidence: 挂账待验，由结算复刻器开发时检索 X.49~X.51 历史极值判例补验`；
  - **风控保护**：在 $X.50$ 边界行为完成实证前，RSK-06 核密度平滑按边界不确定性做对称保护处理，严禁在 .50 边缘满仓下注。

## §6 开口档位（Open-Ended Brackets）语义映射
- **单边极值档位**：如 `84°F or higher`、`73°F or below`；
- **概率积分模型**：在最高档位采用累积分布补集 $1 - F(83.5)$ 计算期望胜率；在最低档位采用 $F(73.5)$ 计算期望胜率。
