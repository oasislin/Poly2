# Phase 2 波次三 (W3) 真实盘口接入预注册规格书（框架草案）

> **工单编号**：`P7-W3-PREREG-FRAMEWORK`  
> **任务编号**：`P7-W3-KICKOFF-001` (事项 ② & ③)  
> **文档版本**：**Rev.0.1 (委员会议定骨架版，仅框架，不含任何未授权判据数值)**  
> **文书编号**：`P7-W3-PREREG-FRAMEWORK-R1`  
> **生效分支**：`fix/p7-w2-shortloop`（基线 HEAD `c718802`，严禁 merge 到 main）  
> **串行位次**：**0/4（环境冻结与规格书预注册框架）**  
> **治理原则**：“预注册优先、判据先行实现在后、数值由委员会审定、零实现代码、零资金变动、零私钥加载”。

---

## 声明：判据数值冻结与代码禁止令
> [!IMPORTANT]
> **本文件为纯规格书框架**。所有关于延迟容忍阈值、深度穿透阈值、正 EV 判定阈值、价差门槛等判据数值**均保留占位符（`[PENDING_COMMITTEE_SPECIFICATION]`）**。  
> 必须经由用户与技术裁决委员会共同议定并正式批复后，方可填入数值；**在委员会正式签发 W3-A 实现放行令之前，严格禁止编写任何生产级盘口拉取与对接代码**。

---

## 一、 盘口拉取方式（CLOB API 只读通道契约）

### 1.1 协议与连接架构
1. **只读公开通道（Public Read-Only Endpoints）**：
   - 采用 Polymarket CLOB HTTP REST / WebSocket 公共行情端点；
   - 严格限定请求范围为只读公共行情：市场元数据查询（`/markets`）、订单簿快照（`/book`）与公共价格行情；
   - 绝对禁止调用任何需要签名权限的私有端点（如 `/order`、`/cancel`、`/trades` 私有历史）；
2. **零私钥与零认证绝缘（Zero Authentication / Zero Signer）**：
   - 盘口采集模块严格不加载、不读取、不解析任何生产私钥或 API 交易凭证（API Secret/Passphrase）；
   - 运行时上下文环境变量必须剥离任何钱包私钥注入；
3. **频率限制与反压管理（Rate Limiting & Backoff）**：
   - 严格遵守 Polymarket 公共 API 速率限制配额；
   - 遇 HTTP 429 速率限制或网络抖动时，采用指数退避迟滞策略，坚决禁止激进轮询。

---

## 二、 快照频次与延迟容忍规范（框架占位）

### 2.1 快照采集周期
- **轮询频次基准**：`[PENDING_COMMITTEE_SPECIFICATION]`（待委员会与用户议定，例如 30s / 60s / 300s）；
- **对齐触发机制**：与 W2 物理观测合流事件及 30 分钟定价重估周期的对齐方式 `[PENDING_COMMITTEE_SPECIFICATION]`。

### 2.2 盘口新鲜度与延迟容忍门禁（Staleness Tolerance）
1. **物理时钟与行情时钟同步差**：
   - 最大允许盘口快照时延 $\Delta t_{\text{book\_lag}} \le$ `[PENDING_COMMITTEE_SPECIFICATION]` 秒；
2. **超龄与断流处置规则**：
   - 当盘口更新延迟超过容忍上限时，触发 `BOOK_DATA_STALE` 警示；
   - 盘口断流期间的定价信号抑制与只读回退机制 `[PENDING_COMMITTEE_SPECIFICATION]`。

---

## 三、 盘口到对价映射定义（OrderBook -> Effective Price）

### 3.1 2°F 几何分桶与 Polymarket 合同 Token 映射
1. **合同 Token 动态寻址**：
   - 根据台站标识（KORD / KMIA）、标的类型（TMax / TMin）、到期日期与 2°F 分桶区间，动态匹配 Polymarket 预测市场的 Token ID；
   - 无法解析或无流动性分桶的空盘标记契约；
2. **深度加权成交均价（VWAP）穿透**：
   - 沿用 W2 深度穿透模型：针对设定目标名义规模 $V$，计算 Ask 深度加权有效买入价 $P_{\text{eff}}$：
     $$P_{\text{eff}} = \frac{\sum P_m \cdot q_m}{V}$$
   - 薄盘口（深度不足以填满 $V$）的拒单标记契约：`REJECTED_INSUFFICIENT_DEPTH`；
3. **盘口买卖价差（Spread）过滤门槛**：
   - 最大允许买卖价差 $\text{Spread} = P_{\text{ask}} - P_{\text{bid}} \le$ `[PENDING_COMMITTEE_SPECIFICATION]`。

---

## 四、 真实 EV 定价判据（占位与框架）

### 4.1 净期望收益与边际（Net EV & Edge）
依据 W2-A 冻结之微观结构公式：
$$\text{EV}_{\text{net}} = p_k \cdot (1.0 - f) - P_{\text{eff}}, \quad \text{Edge} = \frac{\text{EV}_{\text{net}}}{P_{\text{eff}}}$$
- 费率 $f$ 设定口径：`[PENDING_COMMITTEE_SPECIFICATION]`（标准 Taker/Maker 费率）；
- 最小边际开仓阈值 $\text{min\_reprice\_edge}$：`[PENDING_COMMITTEE_SPECIFICATION]`（例如 3%）。

### 4.2 资产治理约束继承（W2 冻结项）
1. **KMIA_12h 挂旗资产**：强制继承 `COMPLETED_ECE_FLAGGED` 治理标签，头寸额度硬折剪 50%；
2. **FAILSAFE 粗粒度资产降级**：若发生路由回退，强制执行 `FAILSAFE_DEGRADED_READONLY`，可交易信号严格置 0；
3. **死档（$p_k = 0.0$）绝对拒绝**：严禁向死档发出任何执行信号。

---

## 五、 数据性质显式标注条款（沿用 W2 教训）

> [!IMPORTANT]
> **数据性质法定标注条款（反混淆红线）**：
> 1. **双重数据源显式打标**：
>    所有进入系统、日志、报告或审计工件的盘口及物理观测数据，必须带有严格不可篡改的元数据标签：
>    - `DATA_PROVENANCE = "POLYMARKET_LIVE_CLOB"`（真实生产盘口 API 镜像）；
>    - `DATA_PROVENANCE = "SYNTHETIC_INJECTED_REPLAY"`（本地离线合成回放）；
> 2. **禁止含混表述**：严禁在合成回放数据上使用“实盘/实证成交”等容易引起混淆的措辞；所有分析报告首章必须明示数据来源属性。

---

## 六、 门禁与判据预定义占位表 (C-W3 系列)

| 门禁编号 | 门禁名称 | 判定阈值 / 门槛指标 (占位) | 门禁性质 | 验证与审计方法 |
| :---: | :--- | :--- | :--- | :--- |
| **C-W3-1** | **真实盘口 API 连通性与时延门禁** | 成功响应率 $\ge$ `[PENDING]`%；<br>P99 延迟 $\le$ `[PENDING]`ms | 网络质量硬门禁 | 连续采集时钟流，审计网络时延与断流捕获 |
| **C-W3-2** | **订单簿深度解析与 VWAP 穿透门禁** | 深度穿透计算误差 $\equiv 0$；<br>薄盘口拦截率 $= 100\%$ | 微观定价硬门禁 | 注入真实订单簿快照，与基准定价引擎核对 |
| **C-W3-3** | **真实盘口动态 EV 信号生成门禁** | 死档信号 $\equiv 0$；<br>正 EV 信号生成精确率 $= 100\%$ | 策略风控硬门禁 | 真实盘口对价 vs W1/W2 物理概率分布比对 |
| **C-W3-4** | **C5 真实盘口零资金零私钥门禁** | **真实资金变动 $\equiv \$0.00$；<br>生产私钥加载 $\equiv 0$ 次；<br>下单调用次数 $\equiv 0$ 次** | 最高安全门禁 | 静态扫描代码与动态监控环境变量，断言纯只读 |
| **C-W3-5** | **全量回归测试套件零退化门禁** | **1043 + N passed, 0 failed**；<br>退出码严格为 0 | 交付门槛 | 全库自动化测试护航 |

---

## 七、 C5 红线首次确认声明（W3 全程生效）

1. **零资金变动**：W3 阶段外部资金（Free USDC / 链上资产）变动严格为 **`$0.00`**；
2. **零私钥加载**：生产私钥、助记词或敏感签名凭证在 W3 全程**绝对禁止加载进入代码或内存**；
3. **零下单调用**：系统仅使用公开只读行情 API，**任何形态的下单接口调用、签名生成或发送订单尝试即判定为 ERROR 级严重违令**，直接终止会话。

---

## 八、 呈报与后续流程

本预注册规格书框架草案现正式呈报技术裁决委员会与用户。  
**下步动作**：请委员会与用户审议本框架，共同议定各占位符的法定数值；在获得正式批准前，严格保持零实现代码状态。
