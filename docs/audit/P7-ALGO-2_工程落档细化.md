<!-- 供主导方审阅与用户最终确认 | 日期: 2026-10-19 | 角色: 开发端 Agent -->
# P7-ALGO-2 交易引擎工程落档细化设计书

> **文档编号**：P7-ALGO-2-ENG-SPEC  
> **版本**：v1.4（已对齐市场特性契约 v1.0 + 外部审计修正 + τ_2D 阶梯补注 + 2026-10-19 套利轨废除修剪与 P0-2 严谨性注记 · 2026-10-19）  
> **编制依据**：
> 1. 《P7-ALGO-2 联合凯利与执行定价算法规格书》v0.6（已对齐套利轨废除修剪）
> 2. 《P7-ALGO-2 算法描述文档》v0.6（数学公式完备版，已对齐套利轨废除修剪与 P0-2 严谨性注记）
> 3. 《Polymarket 市场特性契约》v1.0（2026-10-14，费率、NegRisk、订单类型、Data API v2 与结算规则）
> 4. 外部专家审计报告（2026-10-14）、主导方审核意见 v1.0 与 DR-2026-1014-01~04、DR-2026-1019-01 裁决记录
> 5. 《v1 遗产判决书》v0.3（M-1~M-8 签署判词）
> 6. 关联 ADR 宪法（ADR-0011~0015、ADR-0018）
> 7. 用户 2026-10-13 / 2026-10-14 / 2026-10-19 裁决（缺失文件废止不重写、带旗禁投方案 A、挂锁纪律、暂不做 maker、三轨套利废除、裁决记录留痕）
> 
> **定位**：本文件为未来代码落地的**最高工程实现法案**。严格遵守“本阶段只落档细化，不落地运行”之铁律，将顶层规格细化为可直接编码的强类型接口、数据模型、状态机、算法核心草案与日志规范。

---

## 一、 模块与代码树规划（全新落位，不迁旧代码）

根据用户裁决，原归档中缺失的 11 个源文件已正式废止，本系统将在 `src/trading/` 命名空间下全新实现，完全遵从现代契约：

```
src/trading/
├── __init__.py
├── models/                     # 核心数据模型与不可变快照
│   ├── __init__.py
│   ├── snapshot.py             # 决策快照 DecisionContext (Frozen Dataclass)
│   ├── market.py               # 市场元数据 MarketMeta (含温标与时区) 与 Gamma 契约
│   ├── bankroll.py             # 四桶资金模型、pUSD 6位 Decimal 精度定点量
│   ├── order.py                # CLOB 订单模型、FAK 限价单契约（严格禁市价单）
│   └── lifecycle.py            # 台站与持仓状态机枚举
├── pricing/                    # M1 定价与交易信号
│   ├── __init__.py
│   ├── dynamic_fee.py          # 动态费率计算 (q = P·[1+base·(1-P)], base=0.05)
│   └── ev_engine.py            # VWAP 达标深度穿透 (S_target) 与 EV/Edge 生成
├── bankroll/                   # M2 凯利优化器与 M5 资金账务
│   ├── __init__.py
│   ├── bankroll_manager.py     # 四桶资金状态机与 6 位 Decimal 控制器
│   ├── multinomial_kelly.py    # 稳健多项凯利 (LP 强对偶单层展开 SLSQP + 闭式 Jacobian)
│   ├── uncertainty.py          # Delta Method + η 不确定集构建
│   └── zombie_evaluator.py     # 12h 僵尸判定与 R_z 流动性熔断
├── risk/                       # M3 风险闸门
│   ├── __init__.py
│   ├── risk_limiter.py         # 10% 单市场 / 70% 全局利用率硬顶 (统一 B_eff 分母)
│   ├── two_dim_controller.py   # ADR-0011 无量纲标准化残差 z 与临盘两维风控
│   └── pre_buy_gate.py         # ADR-0014 纯内存买单前双门禁与本地硬阀
├── execution/                  # M4 执行路由与残差自愈
│   ├── __init__.py
│   ├── order_router.py         # 保护价计算、safe_capacity 截断、含费折算、FAK 路由
│   ├── residual_healer.py      # 非原子部分成交残差状态机 (仅限 S4 凯利执行残差，含 max_rehedge_loss)
│   └── clob_interface.py       # CLOB 抽象接口与 py-sdk 网关 (含 RateLimiter)
├── monitor/                    # M6 只读错价监控（原套利通道降级，零发射）
│   ├── __init__.py
│   └── misprice_monitor.py     # 单档互补偏离 + 跨档总和偏离观测（不触发下单）
├── settlement/                 # M7 结算复刻
│   ├── __init__.py
│   └── settlement_simulator.py # NWS WRH 法定结算复刻器与台站当地自然日 23:59:59 闭环
├── calibration/                # M8 标定验证 (F-2 挂锁)
│   ├── __init__.py
│   └── financial_calibrator.py # 两步标定反事实 Sizing 模拟器 [F-2 LOCKED]
├── simulation/                 # 纸面盘与仿真支撑 (原 simulation/ 现代重构)
│   ├── __init__.py
│   ├── paper_engine.py         # 纸面盘事件驱动调度引擎
│   ├── market_maker.py         # 对抗式做市商模拟器
│   ├── clock.py                # 仿真推进时钟
│   └── metrics.py              # PnL / 夏普 / 回撤度量
└── governance/                 # M-G 统一异常治理中枢 (横切层)
    ├── __init__.py
    ├── central_arbiter.py      # 控制面中央异常仲裁中枢
    ├── incident_bus.py         # 标准 IncidentEvent 契约与事件总线
    └── emergency_sentinel.py   # 磁盘拔网线与 EMERGENCY_STOP 哨兵
```

---

## 二、 核心数据模型与状态机契约（全链路 Decimal 与 Frozen 规范）

### 2.1 市场元数据与决策快照（Frozen Dataclass，宪法级防脏读）

```python
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Literal, Optional, Tuple

@dataclass(frozen=True)
class MarketMeta:
    """
    市场静态元数据快照 (来自 Gamma API /markets?condition_id=...)
    开盘前或决策前预拉取并校验，校验失败直接熔断 G6 门禁
    """
    condition_id: str
    question_id: str
    tokens: Tuple[str, ...]                   # 各档 outcome token_id
    rewards_daily_rate: Decimal               # 日常流动性激励率
    minimum_order_size: Decimal               # 最小下单份额 (通常为 5.0 shares)
    tick_size: Decimal                        # 价格最小变动单位 (通常为 0.01 或 0.001)
    lot_size: Decimal                         # 份额最小变动单位 (1.0 或 minimum_order_size)
    neg_risk: bool                            # 是否为 NegRisk 互斥市场 (气温恒为 True)
    fee_rate: Decimal                         # 气温 Taker 费率参数 (0.05, 官方定案)
    temperature_unit: Literal["F", "C"]       # 站点法定温标 (DR-2026-1014-04)
    station_tz: str                           # 站点当地 IANA 时区 (如 "America/New_York", P2-3)
    end_date_iso: str                         # 市场名义到期时间
    game_start_time: Optional[str]            # 事件名义开启时间

@dataclass(frozen=True)
class OrderBookLevelSnapshot:
    """单一档位盘口切片"""
    price: Decimal
    size: Decimal

@dataclass(frozen=True)
class BinOrderBookSnapshot:
    """单档位买卖盘深度快照"""
    bin_index: int
    bin_label: str
    asks: Tuple[OrderBookLevelSnapshot, ...]  # 价格升序
    bids: Tuple[OrderBookLevelSnapshot, ...]  # 价格降序

@dataclass(frozen=True)
class DecisionContext:
    """
    宪法级决策快照 (Frozen Snapshot)：
    在 S1 定价启动瞬间对外部世界切片，决策全链路 (S1~S6) 共享该不可变对象，
    严禁在优化求解或路由中重新拉取盘口或重新生成概率，彻底根除脏读与竞态条件。
    """
    station_id: str
    market_id: str
    snapshot_timestamp_utc: str
    market_meta: MarketMeta                   # 市场静态元数据 (含温标与时区)
    
    # 1. 概率层输入 (F-2 管辖)
    p_hat: Tuple[float, ...]                  # EMOS 截断后点估计 (sum=1.0)
    bin_bounds: Tuple[Tuple[float, float], ...] # 各档华氏度/摄氏度边界 (a_i, b_i)
    emos_mu: float                            # EMOS 预测均值
    emos_sigma: float                         # EMOS 预测标准差
    
    # 2. 盘口与成本
    orderbooks: Dict[int, BinOrderBookSnapshot]
    
    # 3. 账户与持仓快照 (记账货币统一为 pUSD backed by USDC)
    w_free: Decimal                           # 当前自由资金 Free pUSD (刻意设计的内生降杠杆基底)
    b_eff: Decimal                            # 有效资金母数 (Free + Active)
    existing_payouts: Tuple[Decimal, ...]     # 各档既有持仓 N_i (沉没成本常数)
    
    # 4. 风控与台站状态
    t_remain_hours: float                     # 距站点当地自然日 23:59:59 剩余小时
    delta_temp: float                         # 当前气温与预测均值温差 ΔT = T_obs - mu
    std_residual_z: float                     # 无量纲标准化残差 z = |ΔT| / sigma_EMOS (DR-2026-1014-04)
    is_station_active: bool                   # Arbiter 台站生命周期状态
    governance_flag: Optional[str]            # 如 "COMPLETED_ECE_FLAGGED"
```

### 2.2 状态机枚举定义

```python
from enum import Enum

class StationLifeCycleState(str, Enum):
    """台站生命周期状态 (ADR-0014)"""
    ACTIVE = "ACTIVE"                       # 正常报价与交易
    SUSPENDED = "SUSPENDED"                 # 暂时安全挂起 (冷却探针观察)
    INVALIDATED = "INVALIDATED"             # 物理撕裂，当日作废至 00:00:00
    EMERGENCY_HALT = "EMERGENCY_HALT"       # 拔网线或磁盘哨兵硬件级阻断

class LiquidityTier(str, Enum):
    """流动性分级状态 (ADR-0012 R_z 四档熔断)"""
    HEALTHY = "HEALTHY"                     # R_z <= 15% -> 1.0x 正常
    WARNING_HAIRCUT = "WARNING_HAIRCUT"     # 15% < R_z <= 30% -> 0.5x 折剪
    HALT_NEW_POSITIONS = "HALT_NEW_POSITIONS"# 30% < R_z <= 50% -> 0.0x 停开新仓
    CRITICAL_SAFE_MODE = "CRITICAL_SAFE_MODE"# R_z > 50% -> SAFE_MODE 只读停机

class ResidualState(str, Enum):
    """非原子部分成交残差状态机 (ADR-0014 / 规格书 §4)"""
    CLEAN = "CLEAN"                         # 初始或完全成交
    RESIDUAL_DETECTED = "RESIDUAL_DETECTED" # 检测到单腿成交或部分成交暴露
    REHEDGING = "REHEDGING"                 # 正在下发限价单补单重对冲
    RESOLVED_BALANCED = "RESOLVED_BALANCED" # 补单成功，风险敞口闭环平衡
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED" # 超时 30s 或亏损击穿触发止损
    LIQUIDATED = "LIQUIDATED"               # 保持持有至结算或专业通道处理
    FAILED = "FAILED"                       # 致命未决异常

class OrderType(str, Enum):
    """
    订单类型宪法约束 (已对齐 Polymarket CLOB py-sdk):
    - FAK (Fill-and-Kill): 激进限价买单，未立即撮合部分自动取消 (等价原 IOC 限价)
    - POST_ONLY: 做市被动挂单 (预留挂起，用户明确裁决暂不做 maker)
    - 宪法铁律: 严格禁止 MARKET (市价单) 存在于枚举中，从类型系统根除滑点失控风险
    """
    FAK = "FAK"                             # 唯一允许的激进买单类型 (Fill-and-Kill 限价)
    POST_ONLY = "POST_ONLY"                 # 仅做市挂单 (预留挂起)

class OrderSide(str, Enum):
    """订单买卖方向 (宪法级只买不卖约束)"""
    BUY = "BUY"                             # 交易层唯一允许下发之方向
    # 严禁在主动交易链路中调用 SELL
```

### 2.3 四桶资金状态机数据结构（pUSD backed by USDC）

```python
@dataclass(frozen=True)
class FourBucketBalance:
    """四桶资金不可变余额快照 (ADR-0012，记账本位币统一为 pUSD backed by USDC)"""
    free_pusd: Decimal
    active_locked: Decimal
    zombie_margin: Decimal
    disputed_margin: Decimal

    @property
    def free_usdc(self) -> Decimal:
        """向后兼容别名: free_usdc 等价于 free_pusd"""
        return self.free_pusd

    @property
    def total_bankroll(self) -> Decimal:
        """账务总资产恒等式: Total = Free + Active + Zombie + Disputed"""
        return self.free_pusd + self.active_locked + self.zombie_margin + self.disputed_margin

    @property
    def effective_bankroll(self) -> Decimal:
        """Sizing 母数轨: Effective = Free + Active (Zombie/Disputed 严格 0.0x)"""
        return self.free_pusd + self.active_locked

    @property
    def nominal_zombie_ratio(self) -> Decimal:
        """名义冻结率 R_z = (Zombie + Disputed) / Total"""
        total = self.total_bankroll
        if total <= Decimal("0"):
            return Decimal("1.000000")
        return (self.zombie_margin + self.disputed_margin) / total
```

---

## 三、 模块接口规范（M1~M8 + M-G 强类型定义）

### 3.1 M1 定价引擎（`DynamicEVEngine`）

```python
@dataclass(frozen=True)
class EVTradeSignal:
    bin_index: int
    model_probability: float
    effective_price: Optional[Decimal]   # q_eff 含费成本
    net_ev: Decimal                     # p_hat - q_eff
    edge: Decimal                       # net_ev / q_eff
    is_tradable: bool                   # 布尔门禁判定
    rejection_reason: Optional[str] = None

class DynamicEVEngineInterface:
    def evaluate_pricing(
        self,
        ctx: DecisionContext,
        base_fee: Decimal = Decimal("0.05"),  # 官方气温 Taker 费率参数 (契约 v1.0, 官方定案)
        min_edge: Decimal = Decimal("0.02"),  # [待标定]
    ) -> Dict[int, EVTradeSignal]:
        """
        1. 达标深度自动穿透 (DR-2026-1014-01):
           探针规模 S_target := sum_{j: edge_j >= min_edge} s_j = safe_capacity_at_min_edge
           计算该达标深度内纯盘口加权均价 P_bar，无需外部传入 target_allocation 盲猜，根除鸡生蛋死锁
        2. 计算有效买入价格: q_eff = P_bar * [1 + base_fee * (1 - P_bar)]
        3. 计算 net_ev 与 edge
        4. 执行带旗判定: 若 ctx.governance_flag 存在，强制 is_tradable = False (方案 A)
        """
        ...
```

### 3.2 M2 凯利优化器（`MultinomialKellyOptimizer`）

```python
@dataclass(frozen=True)
class KellyAllocationResult:
    is_success: bool
    optimal_allocations: Dict[int, Decimal] # 各档 f_i (6位 Decimal, ROUND_DOWN)
    total_allocation: Decimal
    expected_growth_rate: float
    status_message: str

class MultinomialKellyOptimizerInterface:
    def optimize(
        self,
        ctx: DecisionContext,
        signals: Dict[int, EVTradeSignal],
        theta: float,       # [F-2 LOCKED]
        eta: float,         # [F-2 LOCKED]
        delta_mu: float,    # [F-2 LOCKED]
        delta_sigma: float, # [F-2 LOCKED]
        tau_z: float = 1.0, # 来自流动性状态机 (DR-2026-1014-02 前置)
        tau_2D: float = 1.0,# 来自两维风控状态机 (DR-2026-1014-02 前置)
        eps: float = 1e-7,  # 破产防御常数 (P0-3)
    ) -> KellyAllocationResult:
        """
        1. 预算上限前置调制 (DR-2026-1014-02 / DR-2026-1014-03):
           C_max = tau_z * tau_2D * min(0.10 * B_eff, 0.70 * B_eff - Active_locked, W_free)
           全局利用率分母统一为 B_eff，Zombie 坚决 0.0x 剔除
        2. 过滤 signals 中 is_tradable == False 的档位，对应 f_i 强制锁死为 0
        3. 调用 UncertaintyEngine 计算 Delta Method + η 取 max 的区间 [p_L, p_U]
        4. LP 强对偶单层展开 (3K+1 维变量，P0-2 外部审计修正):
           合并内层最坏概率极小化与外层凯利极大化，目标函数严格线性，消除 argsort 折角与假死
        5. 配置解析闭式 Jacobian 矩阵调用 scipy.optimize.minimize (SLSQP)
        6. Fail-Closed 保证: 未收敛或含 NaN 立即回退全零向量
        7. 浮点转 Decimal: quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        """
        ...
```

### 3.3 M3 风险闸门与两维控制器（`RiskGateLimiter` & `TwoDimensionalRiskController`）

```python
@dataclass(frozen=True)
class RiskApprovalResult:
    is_approved: bool
    approved_allocations: Dict[int, Decimal] # x_approved
    total_approved: Decimal
    applied_haircut: Decimal
    rejection_reason: Optional[str] = None

class RiskGateLimiterInterface:
    def evaluate_gates(
        self,
        ctx: DecisionContext,
        raw_kelly_result: KellyAllocationResult,
        tau_z: float,
        tau_2D: float,
        eps: float = 1e-7,
    ) -> RiskApprovalResult:
        """
        纯布尔放行门禁求值 (DR-2026-1014-02, 调制已前置，S3 无后置乘法折剪):
        顺序执行 G1~G7 纯布尔求值:
        G6 (预购门 + 元数据门) -> G5 (带旗禁投) -> G7 (求解器收敛 & Wi >= eps) -> 
        G4 (两维标准化残差 z 门禁放行 tau_2D > 0) -> G3 (僵尸熔断放行 tau_z > 0) ->
        G1 (单市场 10% 封顶) -> G2 (全局 70% 利用率统一 B_eff 分母)
        若全部通过，approved_allocations 完整放行 raw_kelly_result；任一失败全额阻断
        """
        ...

@dataclass(frozen=True)
class TwoDimensionalRiskState:
    z_score: float                  # 无量纲标准化残差 z = |T_obs - mu_EMOS| / sigma_EMOS
    t_rem_minutes: float            # 距离台站自然日 23:59:59 关盘剩余分钟数
    tier: str                       # NORMAL / CRITICAL_SCALE / CERTAIN_DIRECTION / EXTREME_BLOCK
    tau_2D: float                   # 调制系数取值: 1.0 / 0.20 / 0.0
    is_counter_trend: bool          # 是否属于反向开仓 (与预测温差方向相反)
    is_allowed: bool                # G4 纯布尔放行状态 (tau_2D > 0 且无反向违规)
    reason: str

class TwoDimensionalRiskControllerInterface:
    def evaluate_2d_risk(
        self,
        ctx: DecisionContext,
        target_bin_index: int,
        z_cert: float = 0.3,        # [待标定]（参考基线 0.3，对应典型台站 sigma≈1.5°F 时之 0.5°F）
        z_crit_scale: float = 2.0,  # [待标定]（参考基线 2.0，对应典型台站 sigma≈1.5°F 时之 3.0°F）
    ) -> TwoDimensionalRiskState:
        """
        无量纲标准化残差 z 临盘两维风控控制器 (two_dim_controller.py，DR-2026-1014-02 / 04，τ_2D 阶梯补注)
        
        1. 计算无量纲标准化残差:
           z = |T_obs - mu_EMOS| / sigma_EMOS
           (按台站自身 EMOS 条件分布标准差动态无量纲化，天然适配各台站温标与季节性气候离散度)
        
        2. 完整 4 档阶梯映射 (结构定稿，阈值挂锁 [待标定]):
           ┌─────────────────────┬────────────────────────────────────────────┬───────────┬────────────────────────────────────────────┐
           │ 档位                │ 触发条件 (结构)                            │ τ_2D 取值 │ 业务与风控语义                             │
           ├─────────────────────┼────────────────────────────────────────────┼───────────┼────────────────────────────────────────────┤
           │ 正常档              │ 非以下各档                                 │ 1.0       │ 全额预算 (前置并入 C_max)                  │
           │ CRITICAL 缩放档     │ z_cert < z <= z_crit_scale ∧ t_rem <= 60m  │ 0.20      │ 承接原 ADR-0011 "临盘 1h 且温差大" 的 0.20x│
           │                     │                                            │           │ 预算折剪，防范模型尾部极端偏离风险         │
           │ CERTAIN 方向限制    │ z <= z_cert (预测高度确定)                 │ 正向 1.0  │ 承接原 "CERTAIN 禁反向投机": 同向正开仓    │
           │                     │                                            │ 反向 0.0  │ 1.0 正常放行，逆向反开档位一票否决阻断     │
           │ 极端阻断档          │ z > z_crit_scale ∧ t_rem <= 15m            │ 0.0       │ 现有阻断档: 临盘严重失真全额熔断 (C_max=0) │
           └─────────────────────┴────────────────────────────────────────────┴───────────┴────────────────────────────────────────────┘
        
        3. 换算对照基线与挂锁说明:
           - 阈值 z_cert (参考 0.3)、z_crit_scale (参考 2.0) 均为 [待标定]，F-2 绿灯后两步标定定稿；
           - 原 ADR-0011 华氏度绝对阈值 (0.5°F / 3.0°F) 保留为换算对照基线 (典型台站 sigma≈1.5°F 时，
             z = 0.5/1.5 ≈ 0.33, z = 3.0/1.5 = 2.0)，仅作审计追溯，运行时严格以无量纲 z 为准；
           - CERTAIN 口径演进说明: 原 v0.3 CERTAIN 判定需 t_rem < 0.5h ∧ ΔT <= 0.5°F 双条件；
             新口径统一以 z <= z_cert 判定 (时间条件已吸收进 z 判定，当预测高度确定时全时段严禁逆向开仓，
             反向禁投适用范围扩大至全时段，属更保守的防御方向，避免误读为 bug)；
        
        4. 架构约束与 S3 放行保证:
           - τ_2D 取值域严格限制为 {1.0, 0.20, 0.0} (含 CERTAIN 方向性)
           - τ_2D 在 S2 阶段前置并入 C_max 预算计算: C_max = tau_z * tau_2D * min(...)
           - S3 风险闸门 G4 纯布尔放行: gates["G4_TWODIM_ALLOW"] = bool(tau_2D > 0.0)
           - 0.20 缩放档预算正常放行进入 S4 执行路由，极端阻断或反向投机一票否决
        """
        ...
```

### 3.4 M4 执行路由与残差（`OrderRouter` & `ResidualHealer`）

```python
@dataclass(frozen=True)
class ExecutionReport:
    station_id: str
    market_id: str
    orders_dispatched: List[str]
    total_locked_capital: Decimal
    skipped_bins: Dict[int, str]

class OrderRouterInterface:
    def route_allocations(
        self,
        ctx: DecisionContext,
        approvals: RiskApprovalResult,
        min_edge: Decimal = Decimal("0.02"), # [待标定]
        eps: float = 1e-7,                   # 架构参数 (P0-3)
    ) -> ExecutionReport:
        """
        1. 遍历批准的 x_approved 档位 (单位 pUSD)
        2. 计算保护价 P_protect 与 safe_capacity (M1/M4)
        3. 保护检查: 若 safe_capacity <= 0，静默打上 SKIPPED_INSUFFICIENT_PROTECTED_DEPTH
        4. 严格执行 5 步 Tick/Lot 量化管道 (含费折算与深度截断，P0-3 修正):
           Step a: f_i* 已经过 6 位 Decimal ROUND_DOWN 截断
           Step b: P_protect 按 tick_size 实行 ROUND_DOWN:
                   P_protect = (P_protect // tick_size) * tick_size
           Step c: 计算有效保护成本 q_eff(P_protect) 并折算原始份额与 safe_capacity 截断:
                   raw_shares = min(f_i* / q_eff(P_protect), safe_capacity)
           Step d: 份额按 lot_size 实行 ROUND_DOWN:
                   final_shares = (raw_shares // lot_size) * lot_size
           Step e: 门禁检查: 若 final_shares < ctx.market_meta.minimum_order_size:
                   打上 SKIPPED_BELOW_MINIMUM_ORDER_SIZE 审计标签，跳过该档下注并释放资金
        5. 资金含费足额预冻结 (P0-3 修正): BankrollManager.lock_funds(final_shares * q_eff(P_protect))
        6. 下发 FAK (Fill-and-Kill) 限价单至 CLOB py-sdk 网关 (宪法铁律: 严禁市价单)
        7. 成交回报喂入 ResidualHealer (仅限 S4 凯利执行部分成交/单档失败场景，非套利；非原子成交监控与 30s 补单/止损)
        """
        ...
```

### 3.5 M6 只读错价监控（`MispriceMonitor`，2026-10-19 三轨废除后降级）

```python
@dataclass(frozen=True)
class MispriceObservation:
    single_bucket_deviation: Decimal   # max_i |Ask(YES_i)+Ask(NO_i)-1|
    cross_bucket_deviation: Decimal    # |sum_i Ask(YES_i) - 1|
    ts: datetime

class MispriceMonitorInterface:
    def observe(self, ctx: DecisionContext) -> MispriceObservation:
        """
        只读观测（零发射）:
        1. 单档互补偏离: Ask(YES_i)+Ask(NO_i)-1（协议恒等 $1/对 的偏离度）
        2. 跨档总和偏离: sum Ask(YES_i)-1（结算公理 Σp=1 的偏离度）
        3. 低频轮询(60s)/事件驱动; 超阈值写入告警日志（人工/审计消费）
        硬约束: 不触发任何下单、不产生仓位、不进入交易管线
        """
        ...
```

### 3.6 M8 数据层与 API 客户端接口（`DataAPIV2Client`）

```python
class DataAPIV2ClientInterface:
    """
    Polymarket Data API v2 客户端接口 (对齐契约 v1.0, 替代 2026-10-24 废弃之 v1):
    - 主端点: /v2/prices-history?token_id={token_id}&interval={interval}&fidelity={fidelity}
    - 分页协议: 基于 cursor 的流式迭代
    - 速率限制: 令牌桶 RateLimiter 控频 18.0 req/s (防御 20 req/s IP 限制)，遇 429 指数退避 (1s, 2s, 4s, 8s, 16s)
    - 离线回测: 强制 Airgap 模式，命中本地 parquet 缓存，严禁网络逃逸
    """
    def get_prices_history(
        self,
        token_id: str,
        interval: str = "1d",
        fidelity: int = 60,
        cursor: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        ...
```

---

## 四、 核心算法实现草案（Python 3.13 伪实现）

### 4.1 高斯族 Delta Method 闭式灵敏度计算（§4）

```python
import numpy as np
from scipy.stats import norm

def compute_gaussian_delta_sensitivity(
    a_f: float,
    b_f: float,
    mu: float,
    sigma: float,
    delta_mu: float,    # [F-2 LOCKED]
    delta_sigma: float, # [F-2 LOCKED]
) -> float:
    """
    计算单个离散温度档 [a, b] 对 EMOS 参数 (μ, σ) 的闭式灵敏度 SE_EMOS
    """
    if np.isneginf(a_f):
        z_a = -10.0
        phi_za = 0.0
    else:
        z_a = (a_f - mu) / sigma
        phi_za = norm.pdf(z_a)

    if np.isposinf(b_f):
        z_b = 10.0
        phi_zb = 0.0
    else:
        z_b = (b_f - mu) / sigma
        phi_zb = norm.pdf(z_b)

    # 偏导数闭式解
    dp_dmu = abs((phi_za - phi_zb) / sigma)
    
    term_a = z_a * phi_za if not np.isneginf(a_f) else 0.0
    term_b = z_b * phi_zb if not np.isposinf(b_f) else 0.0
    dp_dsigma = abs((term_a - term_b) / sigma)

    se_emos = dp_dmu * delta_mu + dp_dsigma * delta_sigma
    return float(se_emos)

def construct_uncertainty_interval(
    p_hat: np.ndarray,
    se_emos: np.ndarray,
    theta: float, # [F-2 LOCKED]
    eta: float,   # [F-2 LOCKED]
) -> tuple[np.ndarray, np.ndarray]:
    """
    双源不确定集取 max (Delta Method vs η 尾部膨胀)
    """
    se_tail = eta * np.sqrt(np.maximum(0.0, p_hat * (1.0 - p_hat)))
    se_total = np.maximum(se_emos, se_tail)

    p_L = np.maximum(0.0, p_hat - theta * se_total)
    p_U = np.minimum(1.0, p_hat + theta * se_total)
    return p_L, p_U
```

### 4.2 单层 LP 强对偶展开理论与梯度矩阵（P0-2 外部审计修正）

内层极小化问题在盒式约束 $p_L \le p \le p_U$ 与单纯形 $\sum p = 1$ 下满足强对偶定理，无对偶间隙。将对偶问题与外层凯利极大化合并，变量扩展为 $z = (f, \lambda, \alpha, \beta) \in \mathbb{R}^{3K+1}$：
- **目标函数（严格线性，$C^\infty$ 无限光滑）**：
  $$\max_{f, \lambda, \alpha, \beta} \; \lambda + \sum_{i=1}^K \alpha_i p_{L,i} - \sum_{i=1}^K \beta_i p_{U,i}$$
- **耦合约束（复合凹函数，水平集为闭凸集）**：
  $$g_i(z) := \ln\left(W_{\text{free}} + N_i + \frac{f_i}{q_{\text{eff},i}} - \sum_{j=1}^K f_j\right) - \lambda - \alpha_i + \beta_i \ge 0 \quad (\forall i)$$
- **解析 Jacobian 偏导数**：
  $$\frac{\partial g_i}{\partial f_j} = \frac{1}{W_i(f)}\left(\frac{\delta_{ij}}{q_{\text{eff},i}} - 1\right), \quad \frac{\partial g_i}{\partial \lambda} = -1, \quad \frac{\partial g_i}{\partial \alpha_j} = -\delta_{ij}, \quad \frac{\partial g_i}{\partial \beta_j} = \delta_{ij}$$
  彻底消灭 argsort 极点折角翻转，从数学层面彻底根绝 SLSQP 线搜索 status=8 假死。

### 4.3 稳健凯利 LP 强对偶单层 SLSQP 求解器实现（§3 & §6，P0-2 闭环）

```python
from scipy.optimize import minimize

def solve_robust_multinomial_kelly(
    p_hat: np.ndarray,
    q_eff: np.ndarray,
    p_L: np.ndarray,
    p_U: np.ndarray,
    existing_payouts: np.ndarray,
    w_free: float,
    budget_cap: float,
    eps: float = 1e-7,  # 架构参数 (P0-3 修复)
    maxiter: int = 200,
    ftol: float = 1e-9,
) -> tuple[bool, np.ndarray, float]:
    """
    单层 LP 强对偶连续可微 SLSQP 求解器 (P0-2 外部审计修正定稿)
    
    决策变量向量 z = [f (K维), lambda (1维), alpha (K维), beta (K维)]，总维度 3K + 1
    目标函数 (取负求极大):
        min -(lambda + sum(alpha * p_L) - sum(beta * p_U))
    约束条件:
        1. 耦合约束: ln(W_i(f)) - lambda - alpha_i + beta_i >= 0  (K个)
        2. 预算约束: budget_cap - sum(f) >= 0  (1个)
        3. 破产硬约束: W_i(f) - eps >= 0  (K个)
    边界:
        0 <= f_i <= budget_cap, alpha_i >= 0, beta_i >= 0, lambda 无界
    解析 Jacobian 梯度保证全局最优收敛。
    """
    k = len(p_hat)
    dim = 3 * k + 1
    zero_vector = np.zeros(k, dtype=np.float64)

    # 1. 输入防御与 Fail-Closed 保证
    if np.any(np.isnan(p_hat)) or np.any(np.isnan(q_eff)) or budget_cap <= 0 or w_free <= 0:
        return False, zero_vector, 0.0

    # 2. 决策变量边界约束
    bounds = [(0.0, float(budget_cap)) for _ in range(k)] # f_i
    bounds.append((None, None))                           # lambda 无界
    bounds.extend([(0.0, None) for _ in range(k)])         # alpha_i >= 0
    bounds.extend([(0.0, None) for _ in range(k)])         # beta_i >= 0

    # 3. 目标函数与解析梯度 (线性目标，C^inf 无限光滑)
    def objective(z: np.ndarray) -> float:
        lam = z[k]
        alpha = z[k + 1 : 2 * k + 1]
        beta = z[2 * k + 1 : 3 * k + 1]
        val = lam + np.sum(alpha * p_L) - np.sum(beta * p_U)
        return float(-val)

    def objective_jac(z: np.ndarray) -> np.ndarray:
        grad = np.zeros(dim, dtype=np.float64)
        grad[k] = -1.0                    # d/d_lambda
        grad[k + 1 : 2 * k + 1] = -p_L    # d/d_alpha
        grad[2 * k + 1 : 3 * k + 1] = p_U # d/d_beta
        return grad

    # 4. 财富计算函数 W_i(f) = w_free + N_i + f_i / q_eff_i - sum(f)
    def get_wealth(f: np.ndarray) -> np.ndarray:
        return w_free + existing_payouts + (f / q_eff) - np.sum(f)

    # 约束 1: 耦合约束 g_i(z) = ln(W_i(f)) - lambda - alpha_i + beta_i >= 0
    def coupling_constraint(z: np.ndarray) -> np.ndarray:
        f = z[:k]
        lam = z[k]
        alpha = z[k + 1 : 2 * k + 1]
        beta = z[2 * k + 1 : 3 * k + 1]
        w = get_wealth(f)
        safe_w = np.maximum(eps, w)
        return np.log(safe_w) - lam - alpha + beta

    def coupling_jacobian(z: np.ndarray) -> np.ndarray:
        f = z[:k]
        w = get_wealth(f)
        safe_w = np.maximum(eps, w)
        inv_w = 1.0 / safe_w
        jac = np.zeros((k, dim), dtype=np.float64)
        for i in range(k):
            # d/df_j = (1/W_i) * (delta_ij / q_eff[i] - 1.0)
            jac[i, :k] = -inv_w[i]
            jac[i, i] += inv_w[i] / q_eff[i]
            # d/d_lambda = -1.0
            jac[i, k] = -1.0
            # d/d_alpha_i = -1.0
            jac[i, k + 1 + i] = -1.0
            # d/d_beta_i = 1.0
            jac[i, 2 * k + 1 + i] = 1.0
        return jac

    # 约束 2: 预算总额 budget_cap - sum(f) >= 0
    def budget_constraint(z: np.ndarray) -> float:
        return float(budget_cap - np.sum(z[:k]))

    def budget_jacobian(z: np.ndarray) -> np.ndarray:
        jac = np.zeros(dim, dtype=np.float64)
        jac[:k] = -1.0
        return jac

    # 约束 3: 结局财富破产保护 W_i(f) - eps >= 0
    def wealth_constraint(z: np.ndarray) -> np.ndarray:
        return get_wealth(z[:k]) - eps

    def wealth_jacobian(z: np.ndarray) -> np.ndarray:
        jac = np.zeros((k, dim), dtype=np.float64)
        for i in range(k):
            jac[i, :k] = -1.0
            jac[i, i] += 1.0 / q_eff[i]
        return jac

    constraints = [
        {"type": "ineq", "fun": coupling_constraint, "jac": coupling_jacobian},
        {"type": "ineq", "fun": budget_constraint, "jac": budget_jacobian},
        {"type": "ineq", "fun": wealth_constraint, "jac": wealth_jacobian},
    ]

    # 5. 初始可行解构造 (保证 Slater 条件成立)
    z0 = np.zeros(dim, dtype=np.float64)
    w0 = get_wealth(z0[:k])
    if np.any(w0 < eps):
        return False, zero_vector, 0.0

    # 选取充分小的 lambda，使初始点严格落入耦合约束可行域内部
    z0[k] = float(np.min(np.log(w0))) - 1.0

    baseline_neg_val = objective(z0)

    try:
        res = minimize(
            objective,
            z0,
            jac=objective_jac,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": maxiter, "ftol": ftol, "disp": False},
        )

        # 6. 输出防御与 Fail-Closed 保证
        if not res.success or np.any(np.isnan(res.x)):
            return False, zero_vector, 0.0

        f_opt = np.maximum(0.0, res.x[:k])
        f_opt = np.where(f_opt < 1e-4, 0.0, f_opt)

        # 检查是否优于全零分配
        if res.fun >= baseline_neg_val - 1e-7:
            return True, zero_vector, 0.0

        growth = float(baseline_neg_val - res.fun)
        return True, f_opt, max(0.0, growth)

    except Exception:
        # 任何数值异常绝对 Fail-Closed
        return False, zero_vector, 0.0
```

### 4.4 保护价与容量穿透计算（§8）

```python
def calculate_protection_price(
    asks: list[OrderBookLevelSnapshot],
    p_hat: float,
    base_fee: Decimal,
    min_edge: Decimal,
) -> tuple[Optional[Decimal], Decimal]:
    """
    遍历 Asks 锁定最后一个满足 EV 判定 >= min_edge 的档位
    返回 (P_protect, safe_capacity)
    """
    safe_price = None
    safe_capacity = Decimal("0.000000")

    for lvl in sorted(asks, key=lambda x: x.price):
        # 试探该价格下的有效成本
        p_float = float(lvl.price)
        q_eff_tier = lvl.price * (Decimal("1.0") + base_fee * (Decimal("1.0") - lvl.price))
        
        net_ev = Decimal(str(p_hat)) - q_eff_tier
        edge = net_ev / q_eff_tier

        if edge < min_edge:
            # 击穿最小优势线，停止穿透
            break

        safe_price = lvl.price
        safe_capacity += lvl.size

    return safe_price, safe_capacity
```

---

## 五、 门禁布尔下沉契约（G1~G7 机械求值）

所有风控判定全部下沉为纯布尔函数，Agent 与运行时仅读取结果：

```python
def evaluate_all_gates(
    obs_age_minutes: float,
    data_connected: bool,
    gateway_connected: bool,
    metadata_valid: bool,
    station_state: StationLifeCycleState,
    is_hard_valve_open: bool,
    governance_flag: Optional[str],
    solver_success: bool,
    f_has_nan: bool,
    w_min: float,
    sum_f: Decimal,
    b_eff: Decimal,
    active_locked: Decimal,
    tau_z: float,
    tau_2D: float,
    eps: float = 1e-7,
) -> dict[str, bool]:
    """
    纯布尔风控门禁求值矩阵 (已对齐契约 v1.0 与 DR-2026-1014-01~04 裁决)
    """
    gates = {}
    # G6 预购门 + 元数据门 (ADR-0014)
    gates["G6_PRE_BUY_AGE"] = bool(obs_age_minutes <= 7.0)
    gates["G6_DATA_STREAM"] = bool(data_connected)
    gates["G6_GATEWAY"] = bool(gateway_connected)
    gates["G6_METADATA_VALID"] = bool(metadata_valid)
    gates["G6_STATION_ACTIVE"] = bool(station_state == StationLifeCycleState.ACTIVE)
    gates["G6_VALVE_OPEN"] = bool(is_hard_valve_open)
    gates["G6_PASS"] = bool(all([
        gates["G6_PRE_BUY_AGE"], gates["G6_DATA_STREAM"], gates["G6_GATEWAY"],
        gates["G6_METADATA_VALID"], gates["G6_STATION_ACTIVE"], gates["G6_VALVE_OPEN"]
    ]))

    # G5 带旗治理门 (方案 A)
    gates["G5_FLAGGED_CLEAR"] = bool(governance_flag is None)

    # G7 求解器收敛与破产保护 (P0-3)
    gates["G7_SOLVER_PASS"] = bool(solver_success and not f_has_nan and w_min >= eps)

    # G4 两维阶梯残差放行门禁 (DR-2026-1014-02 / 04, τ_2D 阶梯补注: 1.0/0.20 放行, 0.0 阻断)
    gates["G4_TWODIM_ALLOW"] = bool(tau_2D > 0.0)

    # G3 僵尸熔断阶梯放行门禁 (DR-2026-1014-02)
    gates["G3_ZOMBIE_ALLOW"] = bool(tau_z > 0.0)

    # G1 单市场 10% 硬顶 (ADR-0012)
    gates["G1_SINGLE_MARKET_CAP"] = bool(sum_f <= (b_eff * Decimal("0.10")))

    # G2 全局 70% 利用率硬顶 (分母统一为 B_eff, DR-2026-1014-03)
    gates["G2_GLOBAL_UTILIZATION_CAP"] = bool(
        b_eff > 0 and ((active_locked + sum_f) / b_eff) <= Decimal("0.70")
    )

    # 总体放行信号: 七道门禁必须全绿灯方可下发订单
    gates["ALL_SYSTEMS_PASS"] = bool(
        gates["G6_PASS"]
        and gates["G5_FLAGGED_CLEAR"]
        and gates["G7_SOLVER_PASS"]
        and gates["G4_TWODIM_ALLOW"]
        and gates["G3_ZOMBIE_ALLOW"]
        and gates["G1_SINGLE_MARKET_CAP"]
        and gates["G2_GLOBAL_UTILIZATION_CAP"]
    )
    return gates
```

---

## 六、 精度守恒与资金定点量化规范

1. **浮点与 Decimal 的物理结界**：
   - 气象模型、EMOS 灵敏度、SLSQP 优化目标函数内部允许使用 IEEE 754 64 位浮点数（`float` / `np.float64`）；
   - 一旦优化完成输出拟投入资金向量 $f^*$，**在离开优化器函数的第 0 毫秒**，必须执行定点量化：
     ```python
     f_decimal = [
         Decimal(str(x)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
         for x in f_opt
     ]
     ```
2. **零向上微动定理**：
   - 资金冻结、释放、结算、折剪全流程**强制采用 `ROUND_DOWN`**；
   - 严禁四舍五入（HALF_UP）导致总资金出现 $0.000001$ 碎屑透支。

3. **5 步 Tick / Lot 执行量化管道（顺序宪法级锁定，严禁倒置）**：
   ```python
   def quantize_order_execution(
       f_i: Decimal,               # S2 输出之资金分配 (pUSD, 6位定点)
       p_protect_raw: Decimal,     # M1/M4 保护价试算值
       safe_capacity: Decimal,     # M1/M4 达标盘口可成交深度 (P0-3)
       base_fee: Decimal,          # 官方费率参数 (0.05)
       tick_size: Decimal,         # 来自 MarketMeta, 如 Decimal("0.01")
       lot_size: Decimal,          # 来自 MarketMeta, 如 Decimal("1.0")
       min_order_size: Decimal,    # 来自 MarketMeta, 如 Decimal("5.0")
   ) -> tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal], Optional[str]]:
       """
       严格按 5 步流水线向下整取，含费折算与深度截断 (P0-3 外部审计修正):
       返回 (quantized_price, quantized_shares, required_locked_funds, skip_reason)
       """
       # Step a: f_i 已被截断至 6 位 Decimal (pUSD)
       if f_i <= Decimal("0.000000"):
           return None, None, None, "ZERO_ALLOCATION"
           
       # Step b: 保护价向下整取至 tick_size
       p_protect = (p_protect_raw // tick_size) * tick_size
       if p_protect <= Decimal("0"):
           return None, None, None, "INVALID_PROTECT_PRICE"

       # 有效含费保护价
       q_eff_protect = p_protect * (Decimal("1.0") + base_fee * (Decimal("1.0") - p_protect))

       # Step c: 试算原始份额并与 safe_capacity 截断 (P0-3 修正)
       raw_shares_budget = f_i / q_eff_protect
       raw_shares = min(raw_shares_budget, safe_capacity)

       # Step d: 份额向下整取至 lot_size
       final_shares = (raw_shares // lot_size) * lot_size

       # Step e: 最小下单规模检查
       if final_shares < min_order_size:
           return None, None, None, "SKIPPED_BELOW_MINIMUM_ORDER_SIZE"

       # 含费足额预冻结资金 (P0-3 修正)
       locked_funds = final_shares * q_eff_protect

       return p_protect, final_shares, locked_funds, None
   ```

---

## 七、 日志与审计标记受控词表（严禁自由发挥）

为确保生产环境日志可机械检索与回放，固化以下审计事件标签：

| 审计标签 (Audit Tag) | 触发条件 | 严重级别 | 后续动作 |
| :--- | :--- | :---: | :--- |
| `SKIPPED_INSUFFICIENT_PROTECTED_DEPTH` | 保护价不可行或 `safe_capacity <= 0` | INFO | 跳过该档单笔下注，解锁对应资金，不中断其余档 |
| `SKIPPED_BELOW_MINIMUM_ORDER_SIZE` | 经 Tick/Lot 量化后份额小于 `minimum_order_size` | INFO | 跳过该档单笔下注，释放预冻结资金，不中断其余档 |
| `SKIPPED_FLAGGED_ASSET_READONLY` | 资产带旗（方案 A） | WARNING | 拒绝开仓，仅记录观测值 |
| `FAILSAFE_DEGRADED_READONLY` | 触发严重降级保护 | WARNING | 强制只读 |
| `REHEDGE_LOSS_EXCEEDED` | 追单贴水超过 `max_rehedge_loss` | WARNING | 触发 `STOP_LOSS_TRIGGERED` 紧急止损 |
| `SLSQP_SOLVER_CONVERGENCE_FAIL` | 优化器未收敛或发散 | WARNING | 回退全零向量，累加失败计数器 |
| `DUTCH_BOOK_DISPATCH` | **[DEPRECATED]** 原套利触发事件 | NOTICE | 已废弃不触发（DR-2026-1019-01），由 `MISPRICE_OBSERVATION_ALERT` 替代 |
| `MISPRICE_OBSERVATION_ALERT` | 观测到单档或跨档偏离度超阈值 | NOTICE | 仅写审计日志与监控面板，零发射不下单 |
| `HARD_VALVE_ZERO_EMISSION_BLOCK` | 本地硬阀关闭或门禁击穿 | CRITICAL | 物理切断字节发射 |

---

## 八、 验收证据与交付状态

- **产出文件**：`docs/audit/P7-ALGO-2_工程落档细化.md`
- **对齐核对**：
  - [x] 对齐《Polymarket 市场特性契约》v1.0 + 外部审计修正（P0-1~P0-3, P1-1~P1-4, P2-1~P2-3）；
  - [x] 对齐 2026-10-19 套利轨废除与 S6 降级只读错价监控（DR-2026-1019-01）；
  - [x] 模块接口签名全量定稿（含不可变决策快照与 MarketMeta 静态元数据设计）；
  - [x] 数据模型与状态机（四桶 pUSD、生命周期、残差三态、FAK 禁市价单）；
  - [x] 核心算法实现草案（LP 强对偶单层 SLSQP 求解器 + 闭式解析 Jacobian）；
  - [x] 门禁 G1~G7 全部纯布尔化下沉（G2 分母统一 B_eff，G3/G4 纯布尔放行）；
  - [x] 精度守恒（6 位 Decimal ROUND_DOWN + 5 步 Tick/Lot 量化管道，含费折算与截断）；
  - [x] 日志与审计标记受控词表建立（含 SKIPPED_BELOW_MINIMUM_ORDER_SIZE 与 REHEDGE_LOSS_EXCEEDED）；
  - [x] 全新目录规划（不迁旧代码，原 arbitrage/ 调整为 monitor/misprice_monitor.py）。

开发端已全部完成工程落档细化（v1.4）！呈交主导方审阅与用户最终确认。

