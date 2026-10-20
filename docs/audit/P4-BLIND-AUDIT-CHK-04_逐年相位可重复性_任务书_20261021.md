# P4-BLIND-AUDIT-CHK-04 · 逐年相位可重复性零假设检验 + KMIA 补算 · 任务书

> 父工单：`P4-BLIND-AUDIT`；前置 `CHK-03`（相位结构部分成立，峰谷/相反已撤回）。
> 性质：B 线只读离线诊断。**不构造分相位替代模型、不拟合乘子、不动 a/b/c/d、不改 c_train、不重训、不写回 pkl/manifest、不读不跑 2019**；开发只交原始值，判定由审核方机械比较。
> 状态：2026-10-21 用户批准（"先零假设可重复性检验，过了再上乘子"）。

## 1. 目的

CHK-03 只用 4 季聚合均值，样本过小、已撤回峰谷结论。本单改用**逐年×相位重复单位**（每站 19 年 × 4 相位）检验：相位方差比是否在大量重复单位上稳定可重复，而非 4 个均值比大小。本单**不建模**，只回答"相位效应是否可重复"。

## 2. 范围与数据

- 站：KORD、KMIA；变量 tmax；2000-2018 训练窗（airgap 白名单）。
- 相位（UTC mod 24）：0={24,48,72}、6={30,54}、12={12,36,60}、18={18,42,66}。
- raw_ratio 口径同 CHK-03：`Var(校准残差)/mean(c²+d²·ens_var)`，不含 c_train。

## 3. 任务 A · KMIA 逐年×相位补算

- 沿用 CHK-03 `build_year_phase_loyo_table` 同一算法，把 KMIA 2000-2018 × 4 相位的 mean_raw_ratio 补全（KORD 已有，不重算覆盖）。
- 输出并入逐年面板表，只列原始值，不与 KORD 比峰谷、不定方向。

## 4. 任务 B · 零假设可重复性检验（不建模）

对每站逐年×相位面板，交以下原始量（布尔判定下沉代码，开发不代判）：

1. **逐年相位排序重复率**：每年对 4 相位 mean_raw_ratio 排名，统计同一相位在 19 年中占据同一相对位次（最高/最低）的年数；交原始计数，不算显著性结论。
2. **相位间年平均差 vs 年际噪声**：每相位 19 年均值、年际 std；相位间最大年均差、该差与年际 std 的比值（原始值）。
3. **两站方向一致性（仅描述）**：并列 KORD/KMIA 各相位年均值与排序，不合并、不宣称同向或相反。
4. 输出 CSV：`p4blind_chk04_year_phase_panel.csv`（station,phase_h,year,mean_raw_ratio）与 `p4blind_chk04_repeatability.csv`（station,phase_h,mean,std,top_years,bottom_years,rank）。

## 5. 判定口径（审核方收表后机械定，开发不代判）

- 零假设 H0：四相位均值无差异（相位无效应）。
- 审核方据"逐年排序重复率 + 相位差/年际噪声比"机械裁定可重复性是否成立；成立才进入下一阶段"分相位标量乘子 LOYO 对照"，本单不提前实现。

## 6. 交付物

1. 只读脚本（新建，不改 CHK-03 冻结脚本）；
2. 两张 CSV；复现命令、退出码、输入/输出 SHA-256、输出末尾原始片段。

## 7. 执行结果（回交后填写）
- 诊断脚本路径 / SHA-256：`scripts/audit_t3/chk04_repeatability.py` / `b162b17b0b3272454297589660cc9a5a99027eb70d5d6593226b15b0ae852736`
- 逐年面板 CSV / SHA-256：`evidence/audit_t3/p4blind_chk04_year_phase_panel.csv` (152 行) / `310448d1894230c95743fb3482650bd3e34220fc76aa17ced64dd16b011a6629`
- 可重复性检验 CSV / SHA-256：`evidence/audit_t3/p4blind_chk04_repeatability.csv` (8 行) / `49b30d2196d7276f2f833afce4597a3378e8dd0f9bc88d611cca0184b0319377`
- 复现命令 / 退出码：`python3 scripts/audit_t3/chk04_repeatability.py --run-all` / `0`
- 下沉布尔判定结果（代码原生）：
  - KORD：最大相位差 0.148284，年际 pooled_std 0.093784，差值/std 比值 = 1.581116（>=1.0: True）；Top 出现 14/19 年（H0 p-val = 1.15e-5，H0 拒绝: True）；Bottom 出现 16/19 年（H0 p-val = 1.00e-7，H0 拒绝: True）。
  - KMIA：最大相位差 0.228193，年际 pooled_std 0.153181，差值/std 比值 = 1.489700（>=1.0: True）；Top 出现 11/19 年（H0 p-val = 2.29e-3，H0 拒绝: True）；Bottom 出现 14/19 年（H0 p-val = 1.15e-5，H0 拒绝: True）。
- commit hash：见本次 Commit（`feat(audit): CHK-04 KMIA 逐年补算与相位可重复性零假设检验（只读）`）。
- 审核方结论（2026-10-21 机械判定，审核方本地独立复算，计数/p 值/信噪比均自面板重算一致）：
  - **零假设 H0（四相位在逐年重复单位上无差异）**：原始观测值 = KORD ph18 Top 14/19（p=1.15e-5）、ph12 Bottom 16/19（p=1.01e-7）、diff/pooled_std=1.581；KMIA ph0 Top 11/19（p=2.29e-3）、ph18 Bottom 14/19（p=1.15e-5）、diff/pooled_std=1.490；KMIA 补算 76 个非空逐年值。判定阈值 = α=0.05，四项二项 p 均 <0.05 且 diff/pooled_std≥1.0 → 拒绝 H0。**结论 = H0 拒绝：相位效应在两站各自的逐年重复单位上可重复成立，非随机。**
  - **边界（不得外推）**：① 仅证明各站内部相位位次逐年可重复，两站 top/bottom 相位不同，**不合并判同向/反向**，也未换算当地时；② 可重复性 ≠ 分相位校正在 OOS 更优；③ 训练内 2000-2018 证据。
  - **处置**：允许进入下一阶段 `CHK-05 分相位标量乘子 LOYO 对照`（每相位一个乘子替换单一 18h 锚点，留年比 s_oos/CRPS/coverage）；仍须 OOS 指标达标才谈建模/重训，本单不实现乘子、不改 c_train。
