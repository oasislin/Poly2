# 【预注册统一规格】P5 逐概率段可靠性与校准对账检验统一修复规格书

- **文档编号**: `specs/preregistration-p5-verification-spec.md`
- **文档版本**: `v2.0 Final (Preregistered)`
- **任务定位**: 生产级决策面可靠性对账与诊断检验引擎（ADR-0017 Gate 2 展开视图）
- **覆盖范围**: 生产全维度（Active 10 站 × TMAX/TMIN 双温标 × 全 lead time）与先导验证集
- **效力声明**: 本规格书即日起作为 P5 线的唯一有效法定技术规格。旧规格 `spec-reliability-001` 及 14 题自查令中凡与本规格抵触的条款，一律废止，以本规格书为准。

---

## 一、 顶层架构与三模式状态机

检验工具必须维持严格的三模式状态机，杜绝数据泄漏与证据效力混淆：

1. **`--mode insample`（全样本自评分模式）**:
   - 定位：仅供工具代码自检与工程干跑，不具备任何校准或能力证明效力；
   - 输出头强制打标：`# mode: IN-SAMPLE SELF-GRADE — 无校准证据效力`。
2. **`--mode cv`（块交叉验证模式）**:
   - 定位：内部诊断模式，用于评估泛化可靠性并暴露模型拟合病灶；
   - 规格：30 天连续块、20 轮、每轮 10% 验证留出 / 90% 补集拟合、`seed=20260923`；
   - 输出头强制打标：`# mode: INTERNAL CV DIAGNOSTIC — 受迭代选择影响，仅供方向参考`。
3. **`--mode blind`（2019 样本外盲测模式）**:
   - 定位：法定终局独立复算门禁；
   - 空气隔离闸门：执行前**强制**校验授权凭证 [`evidence/preregistered_2019_authorization.flag`](../evidence/preregistered_2019_authorization.flag)；
   - 若凭证文件不存在、为空、或未内嵌完整的法定门禁阈值，抛出 `PermissionError` 终止，严禁碰触 2019 数据。

---

## 二、 四项核心裁定技术规格

### 2.1 双轨混合分箱机制 (Dual-Track Hybrid Binning)
为兼顾“各段横向可比性”与“统计小样本退化”，检验引擎采用双轨输出：
1. **判定层（主轨，用于超带与覆盖率判定）**:
   - 起始分档：从 20 个等宽概率档位 $[0.00, 0.05), [0.05, 0.10), \dots, [0.95, 1.00]$ 开始；
   - 自适应合并迭代：若某档样本量 $n < 30$，将其与平均预测概率 $\bar{p}$ 最接近的相邻非空档位合并；
   - 迭代终止条件：全部分箱样本量均满足 $n \ge 30$（若全域总样本不足 30 则整表打标 `NO_DATA`）；
   - 合并留痕：记录合并映射关系与每档包含的子段；
   - 降级旗标：若合并后任一分箱宽度 $\Delta p > 0.15$，该分箱自动打标 `WIDE-BIN`，并在报告中显式披露。
2. **对照层（辅轨，用于全局模型横向对比）**:
   - 维持固定 20 等宽分箱，计算基础 ECE 指标；
   - 该层不进行单格超带与统计检验判定，仅供跨版本 ECE 横向比较。

### 2.2 Benjamini-Hochberg (BH) 多重检验与 FDR 控制
针对多网格、多概率段的联合检验，废除单点机械比较，引入假发现率（FDR）控制：
1. **PIT K-S 检验门禁**:
   - 对检验单元的 K-S 检验计算原始 $p$ 值序列 $p_{(1)} \le p_{(2)} \le \dots \le p_{(m)}$；
   - 施加 Benjamini-Hochberg 校正计算 $q$ 值：
     $$q_{(i)} = \min_{k \ge i} \left( \frac{m \cdot p_{(k)}}{k} \right)$$
   - 显著性门禁要求：BH 校正后 $q \ge 0.05$。
2. **效应量自律兜底**:
   - 为防止大样本下“微小偏差显著拒绝”或平滑下“明显偏态通过”，每格必须输出效应量 $D_{\text{effect}}$：
     $$D_{\text{effect}} = \max_{j} \left| \hat{F}_{\text{PIT}}(u_j) - u_j \right|$$
   - 效应量超标（$D_{\text{effect}} > 0.08$）强制打标 `EFFECT-SIZE-ALERT`。

### 2.3 平滑滑动窗口气候基线 (Smoothed LOYO Climatology)
为杜绝月度阶跃伪缺陷，并与均值层 $b_{30}$ 滑动口径同源，Brier Skill Score (BSS) 的基线概率计算统一重构：
1. **样本池定义**:
   - 针对目标站 $s$、目标日期 $t$（属于季节 $S$、年份 $Y$、日历日 $d$）；
   - 严格留出年份 $Y$（LOYO 规则）；
   - 提取历史其余 18 年中，日历日在 $[d - 7, d + 7]$ 窗口（共 15 天滑动窗）内的实测气温集合 $\mathcal{P}_{s, d}$；
2. **基线概率解析**:
   - 针对档位 $[lb, ub]$，基线概率为该历史气温集合落入区间的经验频率（结合 $\pm 0.05^\circ\text{F}$ 抖动）；
   - 彻底消除“模型采用 30 天滑动偏差、基线却采用粗糙阶梯月均”导致的技能分虚高。

### 2.4 全维度输入适配器与坚固防御 (Robust Input Adapter)
1. **数据资产适配**:
   - 适配器负责读取标准化 GHCN-Daily 实测真值与多时效模型预报底账；
   - 支持 Active 10 站全量代号、支持 `target_type ∈ {"Max", "Min"}`、支持全部 10 个标准 lead time 节点。
2. **人话错误防御**:
   - 严禁出现裸 Python `KeyError` 崩溃；
   - 缺列检查：输入缺失 `obs_tmin_f` 或 `obs_tmax_f` 时，抛出明确错误：
     `DataAssetError: Input arrays missing required column '{col}'. Available columns: [...]`
   - 缺站检查：输入不包含指定站点时，抛出明确错误：
     `DataAssetError: Requested station '{st}' not found in input dataset. Available stations: [...]`

---

## 三、 既有与新增强制技术规范

### 3.1 拟合折折内重拟镜像 P4 协议 (Refit Protocol Mirroring)
- **绝对禁令**: 严禁在检验工具内使用自制、简化的单起点拟合算法；
- **协议镜像**:
  - `refit_parameters_on_subset` 必须调用与 P4 生产一致的确定性 5 初猜多起点全局网格搜索算法；
  - 似然计算必须采用全实数域积分归一化似然（消除截断漂移）；
  - 分布家族集严格对齐为法定三族：**Johnson SU、高斯 (Gaussian)、EVT 极值厚尾**。彻底删除 Student-t 分支。

### 3.2 小样本分层与功效预警 (Statistical Power Warning)
- 当单个分析格子（Station × Season × Target）的有效样本量 $n < 500$ 时，单格不输出独立放行/拒绝结论，打标 `LOW-POWER`；
- 每格报告预计算并打印“最小可检出失准幅度”：
  $$\Delta_{\text{MDS}} \approx \frac{2.8}{\sqrt{n}}$$
  并在可靠性报告首页总览表格中显式呈现。

### 3.3 ECE 去偏与 Bootstrap 置信区间
- **交叉估计 (Cross-Estimation)**:
  - 档位边界划分与预测均值 $\bar{p}$ 确定于拟合折（或训练半窗）；
  - 真实落桶频率 $\hat{f}$ 统计于独立的验证折；
- **Bootstrap 置信区间**:
  - 采用 1,000 次确定性 Bootstrap（固定种子），输出 ECE 的 95% 置信区间 $[ECE_{\text{lower}}, ECE_{\text{upper}}]$；
  - 点估计禁止单独作为放行依据。

### 3.4 种子敏感性自动化检验
- 当任意格子的 PIT K-S 检验 $p \in [0.02, 0.10]$（临界敏感带）时，工具自动运行 5 个固定备用扰动种子（`seeds = [101, 202, 303, 404, 505]`）；
- 自动报告该 5 个种子下的 $p$ 值极差与通过稳定性，替代人工换种子。

### 3.5 纯数学模块单一来源化 (Single Source of EVT Math)
- 全项目 EVT CDF/PDF 纯数学计算唯一指向 [`src/modeling/resampling.py`](../src/modeling/resampling.py) 中的 `evaluate_evt_tail_cdf` 与 `evaluate_evt_tail_pdf`；
- P5 侧禁止保存任何数学副本；
- [`src/verification/resampling.py`](../src/verification/resampling.py) 仅保留时间序列日历切分器，并在模块头明确声明职责边界。

---

## 四、 执行路线图与五项验收门禁

### 4.1 执行顺序
1. **规格落盘**: 本规格书 [`specs/preregistration-p5-verification-spec.md`](preregistration-p5-verification-spec.md) 正式固化落盘；
2. **双 resampling 治理与 EVT 单一法源**: 统一导入源，grep 校验零副本；
3. **refit 协议镜像**: 接入 5 初猜多起点与归一化似然，对齐三族；
4. **全维度输入适配器与防御**: 捕获并转换缺列/缺站异常为显式人话错误；
5. **核心统计件落地**: 双轨分箱、BH-FDR、滑动平滑气候基线、去偏 ECE；
6. **自动化回归测试**: 保持旧 23 项测试全绿，增补防御、一致性与 BH 验证；
7. **交付验收与冒烟报告**: 3 先导站对账与 960 格干跑实测。

### 4.2 五项验收门禁 (Verification Gates)
- [ ] **门禁 1**: 本规格书落盘且 SHA-256 校验码登记录入 `pilot_manifest.json`；
- [ ] **门禁 2**: 全量测试（旧 23 项 + 新增项）无跳过、零幽灵原生全绿；
- [ ] **门禁 3**: 全库 grep 确证 `evaluate_evt_tail_cdf` 仅存在单一实现；
- [ ] **门禁 4**: 先导 3 站 insample/cv 复跑完成，对账数据入表；
- [ ] **门禁 5**: 960 格冒烟完成，记录真实运行时长与内存消耗。

---

## 附注 A：T2 合并规则的实现约定与边界声明

A1（双路径声明）：§2.1 中“p̄ 最接近”判据在两种数据路径下分别生效——合成阶梯路径采用约定 C3（桶中点）+ C2（平局取左）联合确定合并方向；真实数据路径采用样本加权 p̄。
A2（样本不足边界）：总样本 N < min_n 时，合并过程不启动，返回空序列及不足标志。
A3（巨桶合法性）：连环合并产生的宽区间桶为合法终态，须记录其包含子段与合并映射。
A4（min_n 功效待论证）：min_n=30 仅支持粗筛级结论，v3 版须给出功效论证或调整阈值。

---

## 附注 B：规格修订 #4 —— 0.35 标量与流级别退化语义统一声明

- **B1（标量路由语义）**: 孤立单值 $PIT = 0.35$ 为合法分位数输入，依等宽分档 $[0.35, 0.40)$ 正常路由至桶 8（1-indexed），单值路由层不得将其硬编码拦截为退化输入或抛错；
- **B2（流级退化判决）**: 退化检测严格限定在流级别（Stream-level）生效。当且仅当一个输入流的样本量 $N > 1$ 且全部样本为全同常数（即样本方差 $\text{Var}(PIT) = 0$）时，在流分析/流处理层触发退化拦截并抛出显式 `DataAssetError: degenerate: zero variance / collapsed variance stream detected`。

