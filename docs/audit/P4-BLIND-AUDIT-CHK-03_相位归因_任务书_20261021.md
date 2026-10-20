# P4-BLIND-AUDIT-CHK-03 · lead 24h 周期相位归因 · 任务书（草案，待批准开工）

> 父工单：`P4-BLIND-AUDIT`（2019 双城 TMax 盲测复核与第三类重训检测）
> 前置：`P4-BLIND-AUDIT-CHK-02`（原阶段二 lead 归因，已审核通过）。
> 性质：B 线只读离线诊断；**不重训、不改模型参数、不写回 pkl/manifest、不读不跑 2019**；开发只交原始值，判定由审核方机械比较。
> 状态：**2026-10-21 用户批准开工**（用户指令"开工，交给开发端"）。

## 1. 待回答问题

CHK-02 发现 KORD raw_ratio/eff_s 沿 lead 呈稳定 24h 周期（18/42/66h 偏高、36/60h 偏低）。本单判定该周期是：
- **(a) 物理日循环相位**：lead 对应同一 UTC/当地时次，24h 后重复，峰谷由 TMax 观测时刻与预报相位决定，跨季跨年稳定 → 后续应走「分相位离散度」，而非单调平滑；
- **(b) 拟合伪影**：周期位置/幅度跨季跨年漂移、不可重复 → 回退，不作为建模依据。

## 2. 数据与范围

- 站：KORD、KMIA；变量 tmax；仅 2000-2018 训练窗口（airgap 白名单，沿用 CHK-02 加载口径）。
- lead：12,18,24,30,36,42,48,54,60,66,72。
- 只读 manifest 参数 + 训练窗残差/集合方差，不重拟合生产参数。

## 3. 只读检测步骤

> 相位定义采用 **UTC 相位 = lead mod 24**（不引入当地时换算，避免口径臆造）。由 lead 得四组：相位 0 = {24,48,72}；相位 6 = {30,54}；相位 12 = {12,36,60}；相位 18 = {18,42,66}。

1. **同相位分组**：把每格 raw_ratio（口径同 CHK-02：resid_var / mean(c²+d²·ens_var)，不含 c_train）按上列相位归组。
2. **跨季一致性**：对每个 (station, phase)，计算四季 raw_ratio 的组均值、极差、变异系数 cv=std/mean；比较同相位不同 lead 是否聚合。
3. **跨年稳定性（KORD 优先，轻量 LOYO）**：逐年算同相位 raw_ratio 均值，看峰谷相位是否跨年重复（不重训，仅描述原始值）。
4. 输出 CSV：
   - 相位分组表 `station,phase_h,leads,season,raw_ratio,group_mean,group_range,cv`；
   - 跨年相位表 `station,phase_h,year,mean_raw_ratio`；
   - 只列原始值，不下结论、不设阈值判定。

## 4. 判定口径（审核方机械比较，开发不代判）

- 物理相位成立（转分相位离散度）判据由审核方收表后用原始值定：同相位跨季聚合小、峰谷相位跨年重复；否则判拟合伪影、回退。
- 本单不实现分相位模型、不加正则、不改 c_train、不重训。

## 5. 交付物

1. 只读诊断脚本（`scripts/audit_t3/` 或新 `scripts/audit_p4blind/`）；
2. 相位分组 CSV + 跨年相位表 CSV；
3. 复现命令、退出码、输入 SHA-256、输出末尾原始片段。

## 6. 执行结果（批准开工后填写）
- 诊断脚本路径 / SHA-256：`scripts/audit_t3/phase_attribution.py` / `f0c552cd8151a037bb5e8ceec26424c263c21b39053fe5a647dc0988c7797536`
- 相位分组 CSV / SHA-256：`evidence/audit_t3/p4blind_chk03_phase_group.csv` (32 行) / `3ddd99564804edf332562797015fda9596ba6338524b346cb12c97359f3d11eb`
- 跨年相位表 CSV / SHA-256：`evidence/audit_t3/p4blind_chk03_year_phase.csv` (152 行) / `348b55c9a871a43b3864d33009d081b0fc6ef238a49f624c5599947e48926f18`
- 复现命令 / 退出码：`python3 scripts/audit_t3/phase_attribution.py --run-all` / `0`
- KMIA 跨年 LOYO 状态：KMIA 无 LOYO，按指导表项留空。
- commit hash：见 Commit 2（`feat(audit): CHK-03 lead 24h 相位归因只读诊断（KORD/KMIA）`）。
- 审核方结论：＿＿（待填）
