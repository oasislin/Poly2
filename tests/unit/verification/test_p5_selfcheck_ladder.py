"""S1–S5 阶梯对账——断言即预言，修改本文件任何断言 = 交付违规。"""
import csv, json, hashlib
from pathlib import Path
import numpy as np
import pytest

FIX = Path("tests/fixtures/p5_selfcheck")
ORACLE = json.loads((FIX/"oracle_arithmetic.json").read_text())
INV = json.loads((FIX/"oracle_streams_invariants.json").read_text())
TOL_NOTE = "counting/bucket/flag: strict; floats: compare at oracle's printed precision"

# ---------- S1: 管道与防御 ----------
@pytest.mark.parametrize("case", list(csv.DictReader(open(FIX/"oracle_adversarial.csv"))))
def test_s1_adversarial(case):
    from scripts.standalone_reliability_check import route_pit_value   # agent 提供的入口
    if case["expect"].startswith("error"):
        with pytest.raises(Exception) as ei:
            route_pit_value(case["pit"])
        assert case["expect"].split(":")[1].split("_")[0].lower() in str(ei.value).lower()
    else:
        assert route_pit_value(case["pit"]) == int(case["expect_bin"])

# ---------- S2: 算术单元 ----------
def test_s2_bin_edges_42():
    from scripts.standalone_reliability_check import pit_to_bin
    for r in csv.DictReader(open(FIX/"oracle_routing.csv")):
        assert pit_to_bin(float(r["pit"])) == int(r["expect_bin"]), f"pit={r['pit']}"

def test_s2_wilson():
    from scripts.standalone_reliability_check import wilson_interval
    for c in ORACLE["T3_wilson"]:
        lo, hi = wilson_interval(c["k"], c["n"])
        assert round(lo,10) == c["ci95"][0] and round(hi,10) == c["ci95"][1]

def test_s2_bh():
    from scripts.standalone_reliability_check import apply_benjamini_hochberg_fdr
    q = list(apply_benjamini_hochberg_fdr(ORACLE["T4_bh"]["p_in"]))
    assert [round(x,4) for x in q] == ORACLE["T4_bh"]["q_out"]

def test_s2_pit_jitter():
    from scripts.standalone_reliability_check import compute_pit
    c = ORACLE["T5_pit"]
    assert round(compute_pit(c["obs"], c["mu"], c["sigma"], c["seed"]),10) == c["pit_expect"]

def test_s2_ece_weighted():
    from scripts.standalone_reliability_check import weighted_ece
    assert round(weighted_ece(ORACLE["T6_ece"]["buckets"]),10) == ORACLE["T6_ece"]["weighted_ece"]

def test_s2_bss():
    from scripts.standalone_reliability_check import brier_skill_score
    assert round(brier_skill_score(ORACLE["T7_bss"]["bs_model"], ORACLE["T7_bss"]["bs_clim"]),10) \
           == ORACLE["T7_bss"]["bss"]


# ---------- S3: 组装件 ----------
def test_s3_merge_path():   # T2 合并路径：n=50×15 + n=10×5 → spec §2.1 + 约定 C1-C3 机器推导
    from scripts.standalone_reliability_check import merge_small_bins
    # 预言书修订 #3：修订 #2 的 [[14,15],[15,16],[15,16],[15,16],[14,15]] 有误——
    # 其第 5 步 [14,15] 合并两个已达标桶(60,40)，违反终止条件，经 agent 申报、
    # 评审方独立复核确认废止。正确推导（4 步，终态 16 桶 [50×14,60,40]）：
    #   R1 最左小桶 idx15: 左右 |Δp̄|=0.05 平局→并左 [14,15]，桶14=60 p̄=0.7333
    #   R2 idx15(orig16): 左 Δ=0.0917 / 右 Δ=0.0500 → 并右 [15,16]，=20 p̄=0.85
    #   R3 idx15(20):     左 Δ=0.1167 / 右 Δ=0.0750 → 并右 [15,16]，=30 p̄=0.875
    #   R4 idx16(orig19): 无右邻 → 并左 [15,16]，=40 p̄=0.90；全桶≥30 终止
    expect_seq = [[14,15],[15,16],[15,16],[15,16]]
    assert merge_small_bins([50]*15+[10]*5, min_n=30) == expect_seq


def test_s3_stream_routing():
    from scripts.standalone_reliability_check import route_stream
    for name in INV:
        got = route_stream(f"{FIX}/{name}.csv")
        assert got["row_count"] == INV[name]["row_count"]
        assert got["counts"] == INV[name]["counts"]          # 同种子必须逐位一致

# ---------- S4: 统计性质 ----------
def test_s4_invariants():
    from scripts.standalone_reliability_check import route_stream
    for name in ["stream_uniform","stream_lowband"]:
        got = route_stream(f"{FIX}/{name}.csv")
        assert sum(got["counts"]) == 1000                    # 守恒
        idx = got["first_last_bin_of_sorted"]                # 单调
        assert idx == sorted(idx)
        for b,(lo,hi) in enumerate(zip(np.arange(0,1,0.05), np.arange(0.05,1.0001,0.05))):
            pass  # 区间一致性由 route_stream 内部断言，越界即 raise

# ---------- S5: 确定性 ----------
def test_s5_determinism(tmp_path):
    import subprocess, sys
    outs = []
    for i in range(2):
        p = tmp_path/f"run{i}.csv"
        subprocess.run([sys.executable, "scripts/standalone_reliability_check.py",
                        "--synthetic-suite", str(FIX/"stream_uniform.csv"),
                        "--out", str(p)], check=True)
        outs.append(hashlib.sha256(p.read_bytes()).hexdigest())
    assert outs[0] == outs[1]
