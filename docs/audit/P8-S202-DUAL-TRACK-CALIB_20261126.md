# P8-S202-DUAL-TRACK-CALIB：S2-02 (D-A1) 双轨 P13 走簿标定报告（`2026-11-26`）

- **依据工单**：`P8-WO-20261126-EXEC14-S202-CALIB`（实测生成）→ `P8-WO-20261126-EXEC15-L2-SIGNOFF`（业主裁定落盘授权）
- **业主裁定固化参数（`2026-11-26`）**：
  - 模拟切片名义额网格：`($5.00, $25.00, $53.13, $104.55, $171.14, $250.00)`
  - `wing_bin` 离线代理：`single_side == "bid_only"` OR `best_ask ∈ [0.02, 0.25]`
  - `pair_max_skew_sec`：`5.0s`（`max_book_staleness_sec = 60.0s`, `latency_ms = 150`, `max_silent_gap_sec = 30.0s`, `PhiPolicy(rho_0=0.30, k_slope=0, rho_min=0.10, rho_max=0.50)`）
  - 本报告权威路径：`docs/audit/P8-S202-DUAL-TRACK-CALIB_20261126.md`
  - `policy_ledger.json` 权威路径：`configs/policy_ledger.json`

---

## 一、全语料标定摘要（EXEC14 `§2.3` 报告全文）

```markdown
# S2-02 (D-A1) Dual-Track P13 Book-Walking Calibration Report
- Corpus: sessions=12, files=101, total_frames=83516, clean=72245, corrupt=0, fee_rates=['0.01'], span=121.81h, net=99.54h
- Gate (§8 L132): slices>=200=True, stations>=4=True, span>=72h=True, net>=72h=True => gate_passed=True
- YES_ONLY: valid_fills=9387 (FILLED=9287, PARTIAL=100), stations=['KATL', 'KDAL', 'KLGA', 'KMIA', 'KORD', 'KSEA'], median=0.071645, p25=0.000000, p75=0.343544, p90=1.149382
- DUAL_MERGED: valid_fills=9366 (FILLED=9241, PARTIAL=125), stations=['KATL', 'KDAL', 'KLGA', 'KMIA', 'KORD', 'KSEA'], median=0.031579, p25=0.000000, p75=0.180449, p90=0.596343
- §9.1 Dual Metrics: wing_ticks=3415, wing_yes_avail=96.95%, wing_dual_avail=97.39%, gain=+0.44pp, depth_gain_med_ratio=2.0, complement(p10/p50/p90)=0.000000/0.000000/0.000000, inverted_cross=0 (0.0000%)
- Per-Station YES_ONLY: {'KATL': 0.0665583880611068, 'KDAL': 0.06369641129201901, 'KLGA': 0.06774009970811355, 'KMIA': 0.07407574359972899, 'KORD': 0.0822612029158075, 'KSEA': 0.07800968964103712} | counts={'KATL': 1545, 'KDAL': 1811, 'KLGA': 1826, 'KMIA': 1534, 'KORD': 1223, 'KSEA': 1448}
- Per-Station DUAL_MERGED: {'KATL': 0.030343200210790577, 'KDAL': 0.029102256454318586, 'KLGA': 0.02722666218519467, 'KMIA': 0.03734635344630196, 'KORD': 0.031190304094171097, 'KSEA': 0.03588174676606845} | counts={'KATL': 1534, 'KDAL': 1806, 'KLGA': 1824, 'KMIA': 1525, 'KORD': 1229, 'KSEA': 1448}
- Per-Slice YES_ONLY: {'5.00': 0.0, '25.00': 0.02, '53.13': 0.04776144466260204, '104.55': 0.11166064361901624, '171.14': 0.21079145728643217, '250.00': 0.349413080026618}
- Per-Slice DUAL_MERGED: {'5.00': 0.0, '25.00': 0.008249744984699083, '53.13': 0.02338614106297575, '104.55': 0.04679994801648979, '171.14': 0.09204878705443181, '250.00': 0.14418452767657314}
- Draft (§9.2): track=YES_ONLY, friction_median=0.071645, version=p6-s202-v1.0, ledger_written=False
```

---

## 二、`D-6 §9.2` 签发定案与互补参考说明

- **签入 `P6` 实测值（`YES_ONLY` 轨道）**：`friction_median = 0.07164475764557077`（`p25 = 0.000000`, `p50 = 0.07164475764557077`, `p75 = 0.3435441370223979`, `p90 = 1.1493822102862115`，`valid_fills = 9387`，`6` 站覆盖）。
- **互补潜力参考（严禁写入 `P6`）**：`DUAL_MERGED` 轨道 `friction_median = 0.031578947368421054`（`p25 = 0.000000`, `p50 = 0.031578947368421054`, `p75 = 0.18044925844251308`, `p90 = 0.596343405647383`，`valid_fills = 9366`；合格深度中位比 `2.0x`、跨侧倒挂率 `0.0000%`），因当前 `enable_cross_side_split_routing = False`，依 `P8-D6-POLICY-CLOSURE §9.2` 仅留作本报告参考。
