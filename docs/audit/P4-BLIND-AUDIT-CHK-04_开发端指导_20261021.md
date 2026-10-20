# P4-BLIND-AUDIT-CHK-04 开发端指导（KMIA 补算 + 零假设可重复性）· 2026-10-21

> 配套任务书：`docs/audit/P4-BLIND-AUDIT-CHK-04_逐年相位可重复性_任务书_20261021.md`，口径以任务书为准。
> 硬边界：只读离线；不构造分相位模型、不拟合乘子、不动 a/b/c/d、不改 c_train、不重训、不写回 pkl/manifest、不读不跑 2019；只交原始值，判定留审核方。

## A. KMIA 逐年×相位补算
1. 新建脚本 `scripts/audit_t3/chk04_repeatability.py`，**不改** CHK-03 冻结脚本 `phase_attribution.py`。
2. 复用 CHK-03 的 raw_ratio 口径与逐年算法，补 KMIA 2000-2018 × 4 相位 mean_raw_ratio；KORD 已有值照原口径重算入面板，不覆盖 CHK-03 原 CSV。
3. 输出 `evidence/audit_t3/p4blind_chk04_year_phase_panel.csv`：`station,phase_h,year,mean_raw_ratio`。

## B. 零假设可重复性（只交原始量，不建模、不代判）
1. 逐年排序：每年对 4 相位 mean_raw_ratio 排名，统计每相位 19 年中居最高/最低的年数（原始计数）。
2. 每相位 19 年均值、年际 std；相位间最大年均差、差值/年际 std 比值（原始值）。
3. 两站并列，不合并、不判同向/相反。
4. 输出 `evidence/audit_t3/p4blind_chk04_repeatability.csv`：`station,phase_h,mean,std,top_years,bottom_years,rank`。

## C. 回交凭据
- 复现命令、退出码；脚本与两张 CSV 的 SHA-256；输入 manifest/KORD/KMIA truth/gefs 的 SHA-256；输出末尾原始片段。
- 布尔判定在脚本内实现，开发只回读结果，不自行下 pass/fail。

## D. commit（push 按用户当轮明确指令，不擅自推）
- `feat(audit): CHK-04 KMIA 逐年补算与相位可重复性零假设检验（只读）`
- 审核方已落盘的 CHK-03 撤回修订（任务书 §6、ledger §八、工作线 L4/L5）随本次一并 commit。
