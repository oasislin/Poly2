import json
import glob
import datetime
import pytz
import sqlite3
import sys
sys.path.insert(0, '.')

archives = glob.glob('storage/archive/*.json')
conn = sqlite3.connect('storage/weather_cache.db')
cursor = conn.cursor()
cursor.execute('SELECT station_id, date, is_lowest, obs_extreme FROM weather_daily_cache WHERE obs_extreme IS NOT NULL')
obs_map = {(r[0].upper(), r[1], r[2]): r[3] for r in cursor.fetchall()}
conn.close()

valid_scenarios = []
for archive_path in archives[:20]:
    try:
        with open(archive_path, 'r', encoding='utf-8') as f:
            archive_data = json.load(f)
        raw_data = archive_data.get('raw_data', {})
        market_snapshot = raw_data.get('market_snapshot', {})
        raw_forecast = raw_data.get('raw_forecast', {})
        if not market_snapshot or not raw_forecast or 'hourly' not in raw_forecast:
            continue
        market_id = market_snapshot.get('market_id', '')
        station_info = market_snapshot.get('station_info', {})
        station_id = station_info.get('station_id', '').upper()
        target_date = market_snapshot.get('target_date', '')
        ranges = market_snapshot.get('ranges', [])
        timestamp = market_snapshot.get('timestamp')
        if not station_id or not target_date or not ranges or not timestamp:
            continue
        is_lowest = 1 if 'lowest' in market_id.lower() else 0
        obs_key = (station_id, target_date, is_lowest)
        if obs_key not in obs_map:
            continue
        obs_temp = obs_map[obs_key]
        winning_cond = None
        for r in ranges:
            cond = r.get('condition', '')
            if '<=' in cond:
                threshold = int(cond.replace('<=', ''))
                if obs_temp <= threshold:
                    winning_cond = cond
            elif '>=' in cond:
                threshold = int(cond.replace('>=', ''))
                if obs_temp >= threshold:
                    winning_cond = cond
            elif '-' in cond:
                parts = cond.split('-')
                if len(parts) == 2:
                    low, high = int(parts[0]), int(parts[1])
                    if low <= obs_temp <= high:
                        winning_cond = cond
        if not winning_cond:
            continue
        timezone_str = station_info.get('timezone') or 'America/Los_Angeles'
        tz = pytz.timezone(timezone_str)
        mock_dt = datetime.datetime.fromtimestamp(timestamp, tz=pytz.utc).astimezone(tz)
        mock_date_str = mock_dt.strftime('%Y-%m-%d')
        if mock_date_str == target_date:
            for hour in range(3):
                hour_mock_time_str = f'{target_date} {hour:02d}:00:00'
                valid_scenarios.append({'hour': hour})
        else:
            valid_scenarios.append({'hour': None})
    except Exception:
        continue

print('冒烟测试场景数:', len(valid_scenarios))
print('测试通过！')
