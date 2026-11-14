# P8-ALGO 检验 C 2019 终跑与预注册判决报告（分支 A：GHCN(LST) + 5min(LST)）

- **执行日期**: 2026-11-14 | **脚本**: [`scripts/run_p8_inspection_c_2019_final_lst.py`](../scripts/run_p8_inspection_c_2019_final_lst.py)
- **分支与输入**: 分支 A 主门禁宇宙 (`Truth = GHCN(LST)`，`Obs = evidence/p8_2019_5min_lst.parquet`)；现役 hook 加载 [`evidence/p8_mu_r_lst_identifiable_calibration_20261114.json`](p8_mu_r_lst_identifiable_calibration_20261114.json) 与 `v2_2000_2018_oof_cv` `s_oos`。

## 一、 预注册总裁决（严格代码布尔） → **`C 档（终止可签）`** (`TIER_C`)

- **G1（桥必须交付真实预测价值）**: `G1 = True` (`G1a=True`, `G1b=True`)
  - G1a 全池连续 CRPS: 原始观测值 = `CRPS_bridge 1.294325°F` vs `CRPS_native 2.505005°F` (`-48.33%`); 判定阈值 = `CRPS_bridge < CRPS_native`; 结论 = `通过`
  - G1b 分层改善数量: 原始观测值 = `16/16`; 判定阈值 = `≥ 12/16`; 结论 = `通过`
- **G2（桥不得出现结构性病态）**: `G2 = True` (`G2a=True`, `G2b=True`)
  - G2a 232 切片塔性质偏差: 原始观测值 = `608d max=1.1456°F`, `2019(18h) max=1.3558°F`, `2019(22-cell) max=1.0850°F`; 判定阈值 = 全部 232 切片 `≤ 2.0°F`; 结论 = `通过`
  - G2b 分层最大 CRPS 退化比: 原始观测值 = `-0.3272` (`-32.72%`); 判定阈值 = `≤ +0.20 (+20%)`; 结论 = `通过`
- **G3（原子口径 OOS 与全池理性上限）**: `G3 = False` (`G3a=False`, `G3b=False`, `G3c=False`)
  - G3a 2019 午后原子: 原始观测值 = `out95 36/312`, `B1 wResid -0.015065`, `B2 wResid -0.006242`, `B3 wResid +0.000945`; 判定阈值 = `out95 ≤ 25/312` 且各族 `|wResid| ≤ 0.05`; 结论 = `不通过`
  - G3b 2019 早段 B12: 原始观测值 = `out95 38/228`; 判定阈值 = `≤ 20`; 结论 = `不通过`
  - G3c 全池理性上限: 原始观测值 = `ECE_bridge(inw) 0.030586` (native `0.003641`, Δ=`+0.026945`); 判定阈值 = `≤ 0.020`; 结论 = `不通过`
- **B 档集中度条件**: `concentration_cond = False` | 候选剔除方案 = `[]`

## 二、 16 层 CRPS & ECE 分层表现

| 站 | 季 | 时段 | 分布 | CRPS_nat | CRPS_br | Δ% | G1 | G2b | ECE_nat(inw) | ECE_br(inw) |
|:--|:--|:---|:---|---:|---:|---:|:---:|:---:|---:|---:|
| KORD | Winter | early | johnsonsu | 4.0685 | 1.6923 | -58.40% | True | True | 0.006190 | 0.026160 |
| KORD | Winter | late | johnsonsu | 4.1559 | 1.7170 | -58.69% | True | True | 0.006389 | 0.028845 |
| KORD | Spring | early | johnsonsu | 4.4269 | 2.0818 | -52.97% | True | True | 0.008499 | 0.027899 |
| KORD | Spring | late | johnsonsu | 4.3785 | 2.0786 | -52.53% | True | True | 0.008328 | 0.027621 |
| KORD | Summer | early | gaussian | 2.5599 | 1.4731 | -42.46% | True | True | 0.002873 | 0.028179 |
| KORD | Summer | late | gaussian | 2.7298 | 1.5293 | -43.98% | True | True | 0.005939 | 0.029952 |
| KORD | Autumn | early | johnsonsu | 3.1774 | 1.5349 | -51.69% | True | True | 0.004011 | 0.033695 |
| KORD | Autumn | late | johnsonsu | 3.2290 | 1.5643 | -51.55% | True | True | 0.002636 | 0.031788 |
| KMIA | Winter | early | johnsonsu | 1.8282 | 0.9684 | -47.03% | True | True | 0.008316 | 0.034843 |
| KMIA | Winter | late | johnsonsu | 1.8773 | 0.9906 | -47.23% | True | True | 0.005823 | 0.032527 |
| KMIA | Spring | early | johnsonsu | 1.2920 | 0.8670 | -32.89% | True | True | 0.014277 | 0.032636 |
| KMIA | Spring | late | johnsonsu | 1.3397 | 0.8829 | -34.09% | True | True | 0.009983 | 0.033855 |
| KMIA | Summer | early | johnsonsu | 1.2816 | 0.8622 | -32.72% | True | True | 0.021856 | 0.034302 |
| KMIA | Summer | late | johnsonsu | 1.3170 | 0.8781 | -33.33% | True | True | 0.020901 | 0.036921 |
| KMIA | Autumn | early | johnsonsu | 1.1737 | 0.7740 | -34.06% | True | True | 0.003432 | 0.032699 |
| KMIA | Autumn | late | johnsonsu | 1.1874 | 0.7759 | -34.65% | True | True | 0.008474 | 0.033220 |

## 三、 平行非门禁对照输出（不参与 A/B/C 裁决）

1. **METAR(DST) 结算视角偏差分解（G-15 输入）**: KORD `mean(METAR_settle - GHCN) = -0.5384°F` (`|diff|≥2°F: 4.1%`, `2019-10-02 diff=+0.00°F`); KMIA `mean(METAR_settle - GHCN) = -0.8304°F` (`|diff|≥2°F: 9.1%`).
2. **M_t = OfficialMETAR(LST) 观测流敏感性（量化 MADISHF 整度量化噪声）**: 匹配 18h 快照 `n=21083`，`CRPS_bridge(OfficialMETAR) = 1.109202°F` vs `CRPS_bridge(5min) = 0.925230°F` (`diff=+0.183972`); `ECE_bridge_inw(OfficialMETAR) = 0.034378` vs `5min 0.033727` (`diff=+0.000651`); 午后原子 `out95=49/312`。