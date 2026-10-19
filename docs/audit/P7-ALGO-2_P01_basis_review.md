<!-- 供主导方/开发端/用户共同读取 | 日期: 2026-10-13 | 性质: P0-1 修正方案数学依据溯源 -->
# P7-ALGO-2 P0-1 修正方案数学依据溯源（K 个线性硬约束方案）

> **问题**：开发端 §4.3 的二次罚函数（1e6·Σ(eps−W_i)²）破坏规格书 §3.3 凹性证明 → 全局收敛承诺失效。
> **修正方案**：删除罚函数，改为 **K 个线性不等式硬约束 W_i(f) ≥ eps**（因 W_i 对 f 线性），目标保持纯凹 → 凹最大化于凸集 → 全局最优保证完整保留。
> **本文件目的**：证明该方案不是拍脑袋，每个组件均有经典/教科书出处。

---

## 一、方案的数学结构（先写清在证明什么）

$$
\begin{aligned}
\text{目标} &\quad g(f) = \min_{p_L \le p \le p_U,\ \sum p = 1} \sum_i p_i \ln W_i(f) & (\text{凹，§3.3+§6}) \\
\text{其中} &\quad W_i(f) = W_{\text{free}} + N_i + \frac{f_i}{q_{\text{eff},i}} - \sum_j f_j & (\text{对 } f \text{ 线性}) \\
\text{硬约束} &\quad W_i(f) \ge \varepsilon,\ i = 1 \ldots K & (\text{K 个线性不等式} \rightarrow \text{凸集}) \\
&\quad f \ge 0,\ \sum f \le C_{\max},\ f_i \le C_{\max} & (\text{box + 单形} \rightarrow \text{凸集})
\end{aligned}
$$

凹函数 + 凸可行域 → 任何局部最优 = 全局最优（凸优化基本定理）。

## 二、组件 → 经典出处对照表

| 方案组件 | 经典出处 | 说明 |
| :--- | :--- | :--- |
| **A. 凹最大化于凸集 → 局部=全局** | Boyd & Vandenberghe, *Convex Optimization*, Cambridge Univ. Press, 2004, §4.2.2（"Any locally optimal point of a convex problem is globally optimal"） | 本方案的核心定理来源；已核实该书及配套教程存在 |
| **B. 对数财富最大化目标（凯利）** | Kelly, J. L. (1956), *A New Interpretation of Information Rate*, Bell System Technical Journal 35(4): 917–926 | 对数效用 = 复利下长期增长率最大化；已核实原文全文（Princeton 镜像） |
| **C. W_i(f) 线性 → 硬约束为线性不等式** | Boyd & Vandenberghe 2004 §4.1.3（显式 vs 隐含约束）；任意凸优化/NLP 教材：线性不等式是最基本凸约束 | 约束集仍是凸多面体，引理 3 不破 |
| **D. 对数定义域 W>0 显式化** | Boyd & Vandenberghe 2004 §4.1.3（domain 显式化）；对数函数定义域 (0,∞) | 把"隐式定义域"写为显式约束是教科书标准做法，保证数值稳定 |
| **E. 为何不推荐罚函数** | Nocedal & Wright, *Numerical Optimization* 2nd ed., Springer, 2006, §17.1：罚函数法是"约束近似"（approximate constraint）、需序列增大罚系数逼近；固定单一大系数二次罚改变问题形状（此处破坏凸性）；现代 SQP 以动态罚参数作 merit function（Byrd, Gould, Nocedal, Waltz 2004/2005），非凸目标仍无法保证全局 | 已核实 Nocedal/Wright 体系文献（Curtis 2007 论文、Byrd et al. penalty 论文、SNOPT 论文） |
| **F. 线性约束直接交给 SQP active-set** | Kraft (1988) SLSQP；Gill, Murray, Saunders, *SNOPT*（SQP 原生处理线性/非线性约束，线性约束是最标准场景） | 已核实 SNOPT 论文；SLSQP 为 scipy 内置实现 |
| **G. 内层 min_p 保凹（inf 保凹）** | Rockafellar, *Convex Analysis*, Princeton Univ. Press, 1970（凹函数逐点下确界仍凹，epigraph 交集论证） | 支撑规格书 §6 稳健化目标凹性 |
| **H. box 不确定集 + 最坏情形投影** | Ben-Tal, El Ghaoui, Nemirovski, *Robust Optimization*, Princeton Univ. Press, 2009；Bertsimas & Sim, *The Price of Robustness*, Operations Research 52(1): 35–53, 2004 | box 不确定集鲁棒优化是标准框架；最坏情形在顶点/排序解 |
| **I. 贪心顶格填充 = 连续背包 LP 解析最优** | 连续背包（fractional knapsack）贪心最优：Cormen et al., *Introduction to Algorithms* 3rd ed., 2009, §16.2；或鲁棒优化顶点排序结论 | 内层投影 O(K log K) 的出处 |

## 三、结论

1. **方案 b 的全部组件均为经典方法**：凯利（1956）+ 凸优化建模（Boyd 2004）+ 鲁棒优化（Ben-Tal 2009）+ SLSQP/SQP（Kraft 1988）的**标准拼装**，无任何自创数学；
2. **与规格书 §3.3/§6 的关系**：方案 b **不改规格书任何公式**——规格书的论证链本就是"凹目标 + 凸约束"，b 只是让实现与规格书严格一致（删除破坏凹性的罚项，把规格书隐含的 W>0 定义域显式化为线性约束）；
3. 需修订的只是**开发端 §4.3 的代码草案**（删罚函数、加约束矩阵）；
4. Fail-Closed（未收敛/NaN → 全零 + 上报）继续保留——数学保证（收敛即全局）与工程兜底（不死机）互补。

## 四、文献核实状态

- ✅ **已检索核实**：Kelly (1956) 原文；Boyd & Vandenberghe (2004) 及其教程；Nocedal & Wright 体系（Curtis 2007、Byrd et al. 2004/2005、SNOPT）。
- 🔲 学科常识级引用（未逐一检索，可补）：Rockafellar (1970)、Ben-Tal et al. (2009)、Bertsimas & Sim (2004)、CLRS (2009)。如需严格闭环可另行检索核实。

*本溯源随 P0-1 修正一并归档；方案 b 经用户确认后转开发端实施。*
