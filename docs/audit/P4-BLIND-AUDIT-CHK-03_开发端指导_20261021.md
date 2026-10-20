# P4-BLIND-AUDIT-CHK-03 开发端指导（开工命令 + 文档同步清单）· 2026-10-21

> 配套任务书：`docs/audit/P4-BLIND-AUDIT-CHK-03_相位归因_任务书_20261021.md`（口径以任务书为准）。
> 硬边界：只读离线，不重训、不改参数、不写回 pkl/manifest、不读不跑 2019；只交原始值，pass/fail 由审核方机械判定。

## A. CHK-03 开工（相位归因只读诊断）

1. 新建脚本 `scripts/audit_t3/phase_attribution.py`，复用 CHK-02（`lead_attribution.py`）的数据加载与 raw_ratio 口径，不重拟合生产参数。
2. 相位 = lead mod 24：相位 0={24,48,72}、相位 6={30,54}、相位 12={12,36,60}、相位 18={18,42,66}；仅 KORD/KMIA × tmax × 2000-2018。
3. 落盘两张 CSV 到 `evidence/audit_t3/`：
   - `p4blind_chk03_phase_group.csv`：`station,phase_h,leads,season,raw_ratio,group_mean,group_range,cv`
   - `p4blind_chk03_year_phase.csv`：`station,phase_h,year,mean_raw_ratio`（KORD 优先 LOYO；KMIA 无 LOYO 则留空并注明）
4. 复现命令、退出码、输出末尾原始片段、脚本与两张 CSV 的 SHA-256、输入数据 SHA-256 一并回交。
5. 只列原始值，不下结论。

## B. 本轮文档同步清单（审核方已落盘，开发端核对后随 commit）

1. `AGENTS.md`：硬性规则区新增「治理/审计编号（B 线）」指针条，勿改其他铁律原文。
2. `docs/项目编号与命名规范_20261021.md`：新文件，A 交付树/B 治理审计两套体系 + 历史旧号映射；父工单 `P4-BLIND-AUDIT` 已定稿。
3. `docs/audit/T3-阶段二_lead维归因诊断_开发端任务书_20261021.md` §7：审核方判定已填（D-1 通过；P-3 不进单调正则转 CHK-03；P-2 暂不进入）。
4. `docs/audit/DECISION_LEDGER.md` §七：状态更新为审核结论。
5. `docs/audit/工作线登记_V1盲测完善支线_20261020.md`：L2/L3/L4 行更新。
6. **manifest hash 笔误更正**：阶段二回交所写 `2643a6d7…` 错误，真实 manifest SHA-256 = `8bb364e26b8228a50372cfbcd7b0f7a5378b083b99bcb648c727d5e8c4de98eb`（本地复算 + P4-D1-D5 决议固化一致）；开发端若在其环境文档/回交记录留有错误值，一并更正。

## C. commit 分组（push 按用户当轮明确指令，不擅自推）

- commit 1：`docs(audit): P4-BLIND-AUDIT 命名规范定稿、B线指针与 CHK-02 判定回填`（B 节 1-5）
- commit 2：`feat(audit): CHK-03 lead 24h 相位归因只读诊断（KORD/KMIA）`（A 节脚本+CSV）
- 更正项并入 commit 1。push 与否等用户明确指令；不 force、不擅自合 main。

## D. 回交
两个 commit hash、CHK-03 脚本/CSV SHA-256、复现命令退出码与末尾片段、manifest hash 更正确认。
