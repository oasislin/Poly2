# P8-PARAMETER-LIFECYCLE-REGISTRY：参数生命周期登记册（`v1.0` · `2026-11-27`）

> **制度原则（`EXEC18` 业主入册 Doctrine）**：**系统不应存在无生命周期的静态常量**——任何在线/校准/风控阈值均须明确 **初值（`initial_value`）+ 来源（`provenance`）+ 再标定触发条件（`re_estimation_trigger`）+ 再标定方法（`re_estimation_method`）+ 签发权限（`authority`）**；数学推导优先，无严格封闭解者以初值入册并绑定持续再标定路径。

---

## §1 在册参数生命周期总表

| 参数分组 / 名称 | 初值 (`initial_value`) | 来源 (`provenance`) | 再标定触发条件 (`re_estimation_trigger`) | 再标定方法 (`re_estimation_method`) | 生效权限 (`authority`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`S3-16` 概率分箱数与换挡门 (`AUTO_BINNING_UPGRADE`)** | 过渡 `10` 桶；<br>换挡门 = **`200`** 已结算站日（切 `20` 桶）；<br>算术下限 = **`55`** 站日 | 算术下限 $\lceil 20 \times 30 / 11 \rceil = 55$；实证偏斜 `358` 份 `P17` 分布（`[0.0,0.1)` 占 `64.65%`）需 `200` 站日使有效覆盖充分（`MC P(>0.020) = 4.1%`）；[`ece_evaluator.py`](../../src/calibration/ece_evaluator.py) | 已结算站日数达到 `200` 时程序自动触发；或站点新增/档梯宽度变化（不再是 11 档）时人工重算 | 按新分箱下实测 `P17 p_model` 分位密度评估每桶理论 `n >= 30` 与空桶噪声底，重设 `auto_upgrade_markets` | **`10->20` 换挡执行 = 自动（写日志事件）**；变更 `200/55` 门槛本身 = **业主签发** |
| **`S3-16` 成熟区分界站日数 (`mature_zone_markets`)** | **`300`** 已结算站日（`3,300` 档观测） | 实证 `358` 份 `P17` 多项式抽样模拟（`20` 桶下 `N=300` 时 `E[ECE]=0.01129`, `p95=0.01569 < 0.020`, `P(>0.020)=0.002`） | `S4-01` 首月及后续每次 `p_model` 分布/模型换代（`B` 类破冻） | 基于最新 `1,000` 次多维多项式 bootstrap 噪声曲线求解 $\mathbb{P}_{\text{cal}}(\widehat{\text{ECE}} > \text{GREEN}) \le 1\%$ 最小 $N$ | **业主签发**（候本单 `EXEC18` 裁定生效） |
| **`S3-16` 每桶最小样本数 (`min_bin_samples`)** | **`30`**（低于 `30` 标 `WARNING_LOW_N`，不剔除不合并） | [`standalone_reliability_check.py#L668`](../../scripts/standalone_reliability_check.py#L668) 既有工程惯例；在 $p=0.20,n=30$ 下二项 SE $= 0.073$ | 进入 `MATURE_ZONE`（`>=300` 站日）或 `S4-01` 月度复检发现 `δ=0.10` 检出力不足 | 按检测目标偏差 $\delta_{\text{detect}}=0.10$、$\alpha=0.05$ 解二项样本公式：$50\%$ 检出力/`p=0.20` Wilson 半宽 $\implies n \approx 61.5$；双侧 $80\%$ 检出力 $\implies n \approx 156.3$（`p=0.25`）–`193.8`（`p=0.50`） | **业主签发** |
| **`S3-16` 评估语料最小门 (`min_settled_markets` / `mature_review_markets`)** | **`30`** 已结算站日（`>=330` bin-outcome）；<br>月检成熟门 **`60`** 站日（`>=660` 档） | [`P8-D6-POLICY-CLOSURE §三/§五/§八`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#八-定标规则最小样本量门槛与-11-26-后-s2-02-实测绑定口径) | 当分站季节覆盖（跨 `2` 周周期以上）或市场结构（每站日档数 $\neq 11$）变化时于 `S4-01` 复核 | 联合核查 `ramp_zone` `CI` 覆盖宽度与多站代表性（要求覆盖 $\ge 4$ 站） | **业主签发** |
| **`ECE` 三级制度锚（公式化绑定 `σ_Δ`）** | `YELLOW = 1.0 * σΔ_frozen`（当前 **`0.020`**）；<br>`GATE-LIVE = 0.025`；<br>`RED = k0 * σΔ_frozen`（当前 **`0.040`**） | [`P8-D6 §三/§四`](P8-D6-POLICY-CLOSURE_制度合龙与标定规范_v1.0.md#四-ece-临界锚议程第-4-项) + 边际净收益归零边界（`k0 * σΔ = 0.040` 为统计学缓冲总宽） | **`S4-01` 或任何 `P6.sigma_delta_frozen` / `k0` 重签换版时** | 由 [`derive_ece_anchors_from_policy`](../../src/calibration/ece_evaluator.py) **自动重推导候选锚**，随月度提案单呈审；`policy_ledger.json` 严禁旁路写入 | 候选重推导 = **自动**；生效入 `P6` = **业主签发** |
| **`m_threshold` 构成四元组（`M4` 入场边际门）** | `k0_threshold_coef = 2.0`；<br>`sigma_delta_frozen = 0.020`（`2019_OFFLINE_PRIOR`）；<br>`m_floor = 0.020`；<br>`friction_median = 0.07164475764557077`（当前 `m_threshold = 0.111645`） | [`configs/policy_ledger.json`](../../configs/policy_ledger.json) + `EXEC15` Layer-2 签发（`S2-02 YES_ONLY` `9,387` 切片） | `S4-01` 每 `30` 日历日（`00:15Z`）月度复检触发（`friction_median` 换源 `>=30` 笔 `P3`；`σ_Δ` 换源 `>=60` 站日） | 读 `P8 CalibrationAggregateBatch`：`median(P3.slippage_vs_best_ask)` 替换 `friction_median`；`IQR/1.349`（`P17.sigma_delta_sample`）替换 `sigma_delta_frozen` | 提案计算 = **自动**；写入新 `config_hash` = **业主签发**（超期走 `B6 is_overdue=True`） |
| **`w(τ)` 资金时间曲率与站日预算参数** | `w0_intent = 0.10`, `min_order_usd_eff = 1.0`, `p = 1.5`, `tau_max_h = 24.0`, `concurrent_days = 2`, `station_cap_usd = 500.0` | [`P8-CAPITAL-CONFIG v1.0 §7`](P8-CAPITAL-CONFIG_资金参数配置_v1.0.md#7-参数账本全案占位参数统一登记表--2026-11-17) | `S4-01` 月度复检且 `edge >= m` 过线扫描 `>= 100` 次（覆盖早中晚三时段每段 `>= 20` 次） | 按 `idle_rate_by_tau` 与早/晚下单实证归因重拟 `p` 与 `w0_intent` | 提案 = **自动**；改版 `P6` = **业主签发** |
| **`PhiPolicy` 盘口吃深与黄灯乘子参数** | `rho_0 = 0.30`, `k_slope = 0.0`, `rho_min = 0.10`, `rho_max = 0.50`, `yellow_multiplier = 0.50` | [`configs/policy_ledger.json`](../../configs/policy_ledger.json) + `D-6 §六` | `S4-01` 月度复检且 `P3` 实成交 `>= 30` 笔 | 对齐 `P3.slippage_vs_est_vwap` 与 `P3.fill_rate` 评估 `rho_0` 与是否开启 `k_slope > 0` | **业主签发**（`yellow_multiplier` 纳入 `config_hash v2`） |
| **机会缩放器 (`OpportunityScaler`)** | `scaler_policy_id = "provisional_identity_v0"`, `scaler_provisional = True`, `scale = 1.0 if edge >= m else 0.0` | [`src/decision/engine.py`](../../src/decision/engine.py) (`v0.3 §3.2`) + `PROVISIONAL_UNTIL_D6` | `S3-11` 积累足量 `P1/P3/P9` 后立项非线性 `s(edge)` 专题研究单 | 分 `edge - m_threshold` 区间评估净期望回报弹性后设计连续非降映射 | **业主签发**（须随 `P6` 换版与接口升版） |

---

## §2 延期候单清单（不入 `EXEC18`）

- **全仓硬编码常量普查（低优先级候单）**：对 `src/` 既有非本单模块内遗留字面常量（如 `eta_calibration` 降级常数、历史测试/脚手架默认超时等）开展只读 AST/文本扫描与生命周期补登——**不纳入 `EXEC18` 变更面**，列作低优先级治理候单另行排队。
