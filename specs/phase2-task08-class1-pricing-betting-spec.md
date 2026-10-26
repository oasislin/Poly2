# Phase 2 Task 08 · 第一类投注定价算法与只读纸面盘落地 Spec

> **任务标识**：`Phase 2 Task 08`  
> **GitHub Spec 主 Issue**：[#133](https://github.com/oasislin/Poly2/issues/133)  
> **治理工单（B 线）**：`P8-CLASS1-LAUNCH` / `CHK-01` ~ `CHK-11`  
> **法定 ADR**：`docs/adr/ADR-0019：物理模型参数向投注算法消费契约与解耦架构.md`  
> **宪法与裁决依据**：P7-ALGO-VERDICT（M-1/M-2/M-4/F-2）、P7-ALGO-2 DR-2026-1014-01~04  
> **状态**：**APPROVED / READY_FOR_DEV**

---

## 一、 问题陈述 (Problem Statement)

1. **上游连续校准量断层**：2019 独立样本外盲测（V2.0 尺子）产出了丰富的连续校准量（$s_{\text{oos}}$、$\text{ECE}_{\text{2F}}$、$\text{Cov}_{90}$、$\text{PIT}_{\text{var}}$），但历史交易系统仅有粗暴的 0/1 硬门禁，导致 $s_{\text{oos}} = 1.149$ 满仓而 $1.151$ 归零的抽样阶跃断崖（Q1）；
2. **覆盖率口径模糊（Q7）**：未分清精确经验分位 `exact` 与对称正态代理 `gaussian_proxy` 的职责分工；
3. **物理与财务耦合风险**：缺乏机器级受控参数消费契约，下游可能引用非受控变量或全局均值化；模型重训更新后缺乏版本戳强校验看门狗，陈旧参数可能污染实盘；
4. **历史实现缺陷**：旧版多项凯利优化器为点估计、违背 M-1 稳健闭式结构；旧风控为后置乘法折剪、违背 DR-2026-1014-02 预算前置原则；旧残差状态机包含违宪的反向对冲与卖出。

---

## 二、 解决方案架构 (Solution Architecture)

1. **ADR-0019 物理参数消费契约与解耦**：
   - 气象物理模型层对交易完全无感知；交易层通过受控契约只读消费；
   - 参数按 22 时间×城市格（time × city）显式组织，严禁全局均值化；
   - 内嵌模型文件与 manifest SHA256 版本戳，启动期强校验，陈旧抛出 `StaleModelParametersError` 阻断交易；
   - 编写 `scripts/trigger_model_retest.py` 封装重测流水线，绑定版本审计；
2. **Q1 连续可信度得分与无悬崖软折减**：
   - G-1 信号正交化：$\psi(s_{\text{oos}})$ 独占方差偏离维度，$S_{\text{conf}}$ 剔除 $x_s$，仅由 $\text{ECE}_{\text{2F}}$、$\text{Cov}_{90}$、$\text{PIT}_{\text{var}}$ 组成；
   - 构造四级平滑软折减曲线 $\psi(s_{\text{oos}})$，彻底消除 1.11 与 1.15 的断崖效应；
   - G-2 双处理防守纵深：欠自信时 $\sigma_{\text{adj}} = \sqrt{\max(1.0, s_{\text{oos}})} \cdot \sigma_{\text{eff}}$ 定价端防虚报 Edge，$\psi(s_{\text{oos}})$ 资金端压降预算 $C_{\max}$ 防资本回撤；过自信格在宽 $F_{\text{std}}$ 带内不人为缩窄方差（$\sigma_{\text{adj}} = \sigma_{\text{eff}}$）；
3. **Q7 覆盖率双轨分工与探针定价**：
   - `exact`（经验 5/95 分位）用于事后审计与盲测体检；`gaussian_proxy` 用于在线实时定价区间；严格遵守三不混用条款；
   - 承接 Task 04 未完成的交易 EV 引擎：注入 M-2 动态费率契约 $q = p[1+\text{base}(1-p)]$；按 DR-2026-1014-01 达标深度 $S_{\text{target}}$ 穿透计算保护均价 $\bar{P}$；
4. **稳健凯利与唯一折剪点**：
   - 依据 DR-2026-1014-03，统一利用率分母为 $B_{\text{eff}} = \text{Free} + \text{Active}$；
   - 依据 DR-2026-1014-02，折减系数 $\tau_{\text{conf}}$ 唯一前置并入 S2 预算上限公式 $C_{\max}$；
   - 落实 M-1，重构多项凯利为基于 EMOS 闭式 CDF 不确定集 $\mathcal{P}$ 的稳健凸优化求解器；
5. **风控下沉与精简状态机**：
   - 依据 DR-2026-1014-04，两维阶梯风控残差阈值改为无量纲标准化 $z = |\Delta T| / \sigma_{\text{EMOS}}$；
   - S3 下单前门禁重塑为纯布尔放行体系，消除后置物料折剪；
   - 落实“只买不卖”最高宪法，精简残差状态机仅保留补单评估与资金释放；
6. **48h 只读纸面盘集成与两步标定闭环**：
   - 装配 S1~S5 纸面盘事件驱动调度器，实现全流程闭环；
   - 实时机械校验资金守恒 $\sum \text{Buckets} == \text{Initial}$；
   - 搭建 F-2 锁参数网格搜索与两步标定离线分析脚手架（M-5 判词落地）。

---

## 三、 切片 Tickets 官方发布清单（24 票全景）

| Ticket 标识 | GitHub Issue 链接 | 标题全拼 | 状态 / Blocked by |
| :--- | :--- | :--- | :--- |
| **Ticket 01** | [#134](https://github.com/oasislin/Poly2/issues/134) | `Phase 2 Task 08 - Ticket 01: feat(contract): 定义物理模型参数消费契约数据模型与格级配置 Schema` | **✅ 已完成 (Closed / CHK-09 通过)** |
| **Ticket 02** | [#135](https://github.com/oasislin/Poly2/issues/135) | `Phase 2 Task 08 - Ticket 02: feat(contract): 实现物理模型与 manifest SHA256 版本戳强校验看门狗` | **Frontier 就绪** / 依赖 #134 已解除 |
| **Ticket 03** | [#136](https://github.com/oasislin/Poly2/issues/136) | `Phase 2 Task 08 - Ticket 03: feat(contract): 实现从 V2 盲测 CSV 自动导出 22 格静态参数表的转换器与校验器` | **Frontier 就绪** / 依赖 #134 已解除 |
| **Ticket 04** | [#137](https://github.com/oasislin/Poly2/issues/137) | `Phase 2 Task 08 - Ticket 04: feat(contract): 实现物理模型重测触发与契约更新审计流水线` | Blocked by #135, #136 |
| **Ticket 05** | [#138](https://github.com/oasislin/Poly2/issues/138) | `Phase 2 Task 08 - Ticket 05: test(contract): 编写参数契约、版本戳校验与防污染契约测试集` | Blocked by #137, Ticket 26 |
| **Ticket 06** | [#139](https://github.com/oasislin/Poly2/issues/139) | `Phase 2 Task 08 - Ticket 06: feat(pricing): 实现 Q7 覆盖率双轨分工与 exact / gaussian_proxy 计算解耦` | **Frontier 就绪** / 依赖 #134 已解除 |
| **Ticket 07** | [#140](https://github.com/oasislin/Poly2/issues/140) | `Phase 2 Task 08 - Ticket 07: feat(pricing): 实现基于 s_oos 的定价端方差自适应膨胀 σ_adj 计算引擎` | Blocked by #136, #139 |
| **Ticket 08** | [#141](https://github.com/oasislin/Poly2/issues/141) | `Phase 2 Task 08 - Ticket 08: feat(pricing): 承接 Task 04 交易 EV 引擎并实现 S1 盘口穿透探针计算 (DR-2026-1014-01)` | Blocked by #140 |
| **Ticket 09** | [#142](https://github.com/oasislin/Poly2/issues/142) | `Phase 2 Task 08 - Ticket 09: test(pricing): 覆盖率双轨三不混用与探针定价单测集` | Blocked by #141 |
| **Ticket 10** | [#143](https://github.com/oasislin/Poly2/issues/143) | `Phase 2 Task 08 - Ticket 10: feat(bankroll): 实现基于 ECE/Cov/PIT 正交三特征的连续可信度得分 S_conf 引擎` | Blocked by #136 |
| **Ticket 11** | [#144](https://github.com/oasislin/Poly2/issues/144) | `Phase 2 Task 08 - Ticket 11: feat(bankroll): 实现平滑无悬崖的三段式方差软折减曲线 ψ(s_oos) 映射器` | Blocked by #136 |
| **Ticket 12** | [#145](https://github.com/oasislin/Poly2/issues/145) | `Phase 2 Task 08 - Ticket 12: feat(bankroll): 实现综合可信度折减因子 τ_conf 组合计算与硬准入熔断逻辑` | Blocked by #143, #144 |
| **Ticket 13** | [#146](https://github.com/oasislin/Poly2/issues/146) | `Phase 2 Task 08 - Ticket 13: test(bankroll): Q1 连续可信度平滑性与断崖消除特性测试集` | Blocked by #145 |
| **Ticket 14** | [#147](https://github.com/oasislin/Poly2/issues/147) | `Phase 2 Task 08 - Ticket 14: feat(bankroll): 四桶资金账务统一 B_eff 分母与资金守恒审计机制 (DR-2026-1014-03)` | Blocked by #134 |
| **Ticket 15** | [#148](https://github.com/oasislin/Poly2/issues/148) | `Phase 2 Task 08 - Ticket 15: feat(bankroll): 实现风控折剪前置并入 S2 预算上限 C_max 唯一折剪点 (DR-2026-1014-02)` | Blocked by #145, #147 |
| **Ticket 16** | [#149](https://github.com/oasislin/Poly2/issues/149) | `Phase 2 Task 08 - Ticket 16: feat(bankroll): 重构多项凯利优化器为基于 EMOS 闭式 CDF 的稳健结构 (M-1 判词落地)` | Blocked by #148 |
| **Ticket 17** | [#150](https://github.com/oasislin/Poly2/issues/150) | `Phase 2 Task 08 - Ticket 17: test(bankroll): 稳健凯利预算前置集中性测试集` | Blocked by #149 |
| **Ticket 18** | [#151](https://github.com/oasislin/Poly2/issues/151) | `Phase 2 Task 08 - Ticket 18: feat(risk): 两维阶梯风控残差阈值无量纲标准化 z 化改造 (DR-2026-1014-04)` | Blocked by #140 |
| **Ticket 19** | [#152](https://github.com/oasislin/Poly2/issues/152) | `Phase 2 Task 08 - Ticket 19: feat(risk): 重塑 S3 下单前门禁为纯布尔放行体系 (消除后置物料折剪)` | Blocked by #148, #151 |
| **Ticket 20** | [#153](https://github.com/oasislin/Poly2/issues/153) | `Phase 2 Task 08 - Ticket 20: feat(execution): 精简 IOC 残差状态机 (只买不卖模式下的补单与预算释放)` | Blocked by #141 |
| **Ticket 21** | [#154](https://github.com/oasislin/Poly2/issues/154) | `Phase 2 Task 08 - Ticket 21: feat(simulation): 装配端到端 S1~S5 只读纸面盘事件驱动调度器` | Blocked by #141, #149, #152, #153 |
| **Ticket 22** | [#155](https://github.com/oasislin/Poly2/issues/155) | `Phase 2 Task 08 - Ticket 22: feat(simulation): 集成纸面盘实时资金守恒与连续净 EV 观测看门狗` | Blocked by #154 |
| **Ticket 23** | [#156](https://github.com/oasislin/Poly2/issues/156) | `Phase 2 Task 08 - Ticket 23: feat(calibration): 搭建 F-2 参数两步标定脚手架 (M-5 判词落地)` | Blocked by #149, #154 |
| **Ticket 24** | [#157](https://github.com/oasislin/Poly2/issues/157) | `Phase 2 Task 08 - Ticket 24: test(simulation): 纸面盘端到端 48h 仿真验收测试集` | Blocked by #155, #156 |
| **Ticket 25** | [#158](https://github.com/oasislin/Poly2/issues/158) | `Phase 2 Task 08 - Ticket 25: fix(contract): 修订物理参数契约数据模型缺陷并加固不可变与严格解析` | **✅ 已完成 (Closed / CHK-14 通过)** |
| **Ticket 26** | [#159](https://github.com/oasislin/Poly2/issues/159) | `Phase 2 Task 08 - Ticket 26: feat(contract): 建立物理参数受控域治理模块（两级域声明、消费影响域登记与算法解耦）` | **Frontier 就绪** / 依赖 Ticket 01/25 已解除 |

---

## 四、 实施纪律与红线

1. **绝对不重训物理模型**：严禁修改 $a, b, c, d$ 与 $c_{\text{train}}$ 参数，严禁向 `data/models/` 写入任何新权重；
2. **严守 F-2 优先律**：所有评分权重、折减曲线参数、$\sigma_{\text{adj}}$ 幂次全部标记为 `[F-2 LOCKED]`，禁止在标定完成前擅自注入生产定值；
3. **TDD 测试驱动开发**：每张 Ticket 必须先写测试用例，提供实际运行命令与输出证据；
4. **两步分离判定**：所有判定下沉到代码布尔表达式，报告固定输出 `原始观测值 = <原样值>；判定阈值 = <目标值>；结论 = 通过/不通过`。
