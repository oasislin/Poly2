#!/usr/bin/env python3
"""
scripts/generate_recompute_svgs.py: Pure-Python SVG Vector Plotter for PIT and Reliability Diagrams.

Generates standard SVG vector graphics without external dependencies (matplotlib not required).
Produces:
1. evidence/pit_histograms.svg: PIT histograms for KORD, KMIA, KSFO vs ideal uniform distribution.
2. evidence/reliability_diagrams.svg: Calibration curves for KORD, KMIA, KSFO vs ideal diagonal.
"""

from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


def generate_pit_histogram_svg(df_all: pd.DataFrame, output_path: Path):
    """Generate SVG containing 3 subplots for PIT histograms of KORD, KMIA, KSFO."""
    stations = ["KORD", "KMIA", "KSFO"]
    width = 900
    height = 320
    sub_w = 260
    sub_h = 220
    margin_x = 40
    margin_y = 50

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="background-color:#ffffff; font-family:sans-serif;">',
        f'<text x="{width/2}" y="28" font-size="16" font-weight="bold" text-anchor="middle" fill="#111827">2019 Out-Of-Sample Probability Integral Transform (PIT) Histograms (10 Bins)</text>',
    ]

    for idx, station in enumerate(stations):
        df_st = df_all[df_all["station"] == station]
        u_vals = df_st["pit_u"].to_numpy()
        counts, edges = np.histogram(u_vals, bins=10, range=(0.0, 1.0))
        freqs = counts / len(u_vals)

        origin_x = margin_x + idx * (sub_w + 30)
        origin_y = margin_y

        # Subplot frame
        svg_parts.append(f'<g transform="translate({origin_x}, {origin_y})">')
        svg_parts.append(f'<rect x="0" y="0" width="{sub_w}" height="{sub_h}" fill="#f9fafb" stroke="#e5e7eb" stroke-width="1"/>')
        svg_parts.append(f'<text x="{sub_w/2}" y="-10" font-size="13" font-weight="bold" text-anchor="middle" fill="#374151">{station} (N=365)</text>')

        # Axes
        plot_x = 35
        plot_y = 20
        plot_w = sub_w - 50
        plot_h = sub_h - 50

        # Max frequency for scaling (up to 0.25)
        max_f = 0.25

        # Horizontal gridlines
        for level in [0.05, 0.10, 0.15, 0.20]:
            y_pos = plot_y + plot_h * (1.0 - level / max_f)
            svg_parts.append(f'<line x1="{plot_x}" y1="{y_pos}" x2="{plot_x + plot_w}" y2="{y_pos}" stroke="#e5e7eb" stroke-dasharray="3,3"/>')
            svg_parts.append(f'<text x="{plot_x - 5}" y="{y_pos + 4}" font-size="9" text-anchor="end" fill="#9ca3af">{level:.2f}</text>')

        # Ideal uniform line at freq = 0.10
        ideal_y = plot_y + plot_h * (1.0 - 0.10 / max_f)
        svg_parts.append(f'<line x1="{plot_x}" y1="{ideal_y}" x2="{plot_x + plot_w}" y2="{ideal_y}" stroke="#ef4444" stroke-width="1.5" stroke-dasharray="4,4"/>')

        # Draw 10 bins
        bin_w = plot_w / 10.0
        for b in range(10):
            b_freq = freqs[b]
            bar_h = (b_freq / max_f) * plot_h
            bx = plot_x + b * bin_w + 1
            by = plot_y + plot_h - bar_h
            bw = bin_w - 2
            svg_parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" fill="#3b82f6" opacity="0.85"/>')

        # Bottom axis ticks
        for t in [0.0, 0.5, 1.0]:
            tx = plot_x + t * plot_w
            svg_parts.append(f'<text x="{tx:.1f}" y="{plot_y + plot_h + 16}" font-size="10" text-anchor="middle" fill="#6b7280">{t:.1f}</text>')

        svg_parts.append(f'<text x="{plot_x + plot_w/2}" y="{plot_y + plot_h + 28}" font-size="10" text-anchor="middle" fill="#6b7280">PIT Quantile U</text>')

        # Summary box
        pit_mean = float(np.mean(u_vals))
        pit_std = float(np.std(u_vals, ddof=1))
        svg_parts.append(f'<rect x="{plot_x + 5}" y="{plot_y + 5}" width="95" height="32" fill="#ffffff" stroke="#d1d5db" rx="3" opacity="0.9"/>')
        svg_parts.append(f'<text x="{plot_x + 10}" y="{plot_y + 18}" font-size="9" fill="#1f2937">Mean: {pit_mean:.4f}</text>')
        svg_parts.append(f'<text x="{plot_x + 10}" y="{plot_y + 30}" font-size="9" fill="#1f2937">Std:  {pit_std:.4f}</text>')

        svg_parts.append('</g>')

    svg_parts.append('</svg>')
    output_path.write_text("\n".join(svg_parts), encoding="utf-8")
    print(f"Generated SVG: {output_path}")


def generate_reliability_diagram_svg(df_all: pd.DataFrame, output_path: Path):
    """Generate SVG containing reliability diagram calibration curves for KORD, KMIA, KSFO."""
    stations = ["KORD", "KMIA", "KSFO"]
    width = 900
    height = 320
    sub_w = 260
    sub_h = 220
    margin_x = 40
    margin_y = 50

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="background-color:#ffffff; font-family:sans-serif;">',
        f'<text x="{width/2}" y="28" font-size="16" font-weight="bold" text-anchor="middle" fill="#111827">2019 Reliability Calibration Curves (20 Probability Bins vs Observed Frequency)</text>',
    ]

    for idx, station in enumerate(stations):
        df_st = df_all[df_all["station"] == station]
        probs = df_st["center_bin_prob"].to_numpy()
        hits = df_st["center_bin_hit"].to_numpy()

        origin_x = margin_x + idx * (sub_w + 30)
        origin_y = margin_y

        svg_parts.append(f'<g transform="translate({origin_x}, {origin_y})">')
        svg_parts.append(f'<rect x="0" y="0" width="{sub_w}" height="{sub_h}" fill="#f9fafb" stroke="#e5e7eb" stroke-width="1"/>')
        svg_parts.append(f'<text x="{sub_w/2}" y="-10" font-size="13" font-weight="bold" text-anchor="middle" fill="#374151">{station} Calibration</text>')

        plot_x = 35
        plot_y = 20
        plot_w = sub_w - 50
        plot_h = sub_h - 50

        # Ideal 45-degree diagonal line
        svg_parts.append(f'<line x1="{plot_x}" y1="{plot_y + plot_h}" x2="{plot_x + plot_w}" y2="{plot_y}" stroke="#9ca3af" stroke-width="1.5" stroke-dasharray="4,4"/>')

        # Compute empirical points
        edges = np.linspace(0.0, 1.0, 21)
        bin_idx = np.clip(np.digitize(probs, edges) - 1, 0, 19)
        pts = []
        for b in range(20):
            mask = bin_idx == b
            if np.sum(mask) >= 5:
                p_m = float(np.mean(probs[mask]))
                h_m = float(np.mean(hits[mask]))
                px = plot_x + p_m * plot_w
                py = plot_y + plot_h * (1.0 - h_m)
                pts.append((px, py))

        # Draw calibration polyline
        if len(pts) > 1:
            points_str = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts)
            svg_parts.append(f'<polyline points="{points_str}" fill="none" stroke="#2563eb" stroke-width="2"/>')
            for p in pts:
                svg_parts.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="3.5" fill="#1d4ed8"/>')

        # Ticks
        for t in [0.0, 0.5, 1.0]:
            tx = plot_x + t * plot_w
            ty = plot_y + plot_h * (1.0 - t)
            svg_parts.append(f'<text x="{tx:.1f}" y="{plot_y + plot_h + 16}" font-size="10" text-anchor="middle" fill="#6b7280">{t:.1f}</text>')
            svg_parts.append(f'<text x="{plot_x - 5}" y="{ty + 3:.1f}" font-size="9" text-anchor="end" fill="#6b7280">{t:.1f}</text>')

        svg_parts.append(f'<text x="{plot_x + plot_w/2}" y="{plot_y + plot_h + 28}" font-size="10" text-anchor="middle" fill="#6b7280">Forecast Probability</text>')
        svg_parts.append('</g>')

    svg_parts.append('</svg>')
    output_path.write_text("\n".join(svg_parts), encoding="utf-8")
    print(f"Generated SVG: {output_path}")


def main():
    parquet_path = EVIDENCE_DIR / "pilot_predictions_2019.parquet"
    if not parquet_path.exists():
        print(f"Error: {parquet_path} does not exist. Run audit_provenance_and_recompute.py first.")
        return

    df_all = pd.read_parquet(parquet_path)
    generate_pit_histogram_svg(df_all, EVIDENCE_DIR / "pit_histograms.svg")
    generate_reliability_diagram_svg(df_all, EVIDENCE_DIR / "reliability_diagrams.svg")


if __name__ == "__main__":
    main()
