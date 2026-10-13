import datetime
import sqlite3
from src.bias_corrector import MovingWindowBiasCorrector

def run():
    corrector = MovingWindowBiasCorrector()
    bias, std_dev = corrector.get_bias(
        station_id='ZSPD',
        lat=31.198,
        lon=121.336,
        timezone='Asia/Shanghai',
        target_date='2026-07-17',
        is_lowest=False,
        window_days=7
    )
    print(f"Target Date: 2026-07-17 (Highest Temp)")
    print(f"Bias: {bias:+.3f}°C")
    print(f"StdDev: {std_dev}")

if __name__ == '__main__':
    run()
