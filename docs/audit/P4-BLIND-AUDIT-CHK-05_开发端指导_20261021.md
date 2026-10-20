# P4-BLIND-AUDIT-CHK-05 开发端指导（分相位乘子 LOYO + 逐日 z² 附表）· 2026-10-21

> 配套任务书：`docs/audit/P4-BLIND-AUDIT-CHK-05_分相位乘子LOYO对照_任务书_20261021.md`，口径以任务书为准。
> 硬边界：不动 a/b/c/d、不重训、不写回 pkl/manifest、不改生产 c_train、不读不跑 2019；乘子只用训练折、留出年零参与；只交原始值，门限留审核方。

## A. LOYO 对照（19 折，每折留 1 年）
1. 新建脚本 `scripts/audit_t3/chk05_phase_multiplier_loyo.py`，复用 CHK-01 E8-b `offline_t3_detection.py` 的留年骨架，不改冻结件。
2. 臂 B 基线 / 臂 A 分相位乘子同折同留出年；k_p = 训练折内该相位全部格 raw_ratio 中位数（稳健中心），禁止使用留出年。
3. 逐折交留出年 s_oos、CRPS、90% coverage（两臂并列），输出 `evidence/audit_t3/p4blind_chk05_loyo_folds.csv`。

## B. 逐日 z² 描述附表（仅描述，不造 p 值）
1. z² = resid_calib²/σ_raw²，按站×相位交 n、mean_z2、按年聚类 std；输出 `evidence/audit_t3/p4blind_chk05_daily_z2.csv`。
2. 不按日数算显著性；独立显著性只认年 LOYO。

## C. 回交凭据
复现命令、退出码；脚本与两 CSV 的 SHA-256；输入 manifest/truth/gefs SHA-256；逐折原始片段；门限布尔在脚本内下沉，开发只回读。

## D. commit（push 按用户当轮明确指令，不擅自推）
- `feat(audit): CHK-05 分相位乘子 LOYO 对照与逐日 z² 描述附表（只读离线）`
