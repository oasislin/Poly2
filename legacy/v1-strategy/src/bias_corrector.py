import datetime
import time
import requests
import numpy as np
from src.config import CONFIG, PROXIES, setup_logger
import src.weather_cache as weather_cache

logger = setup_logger("BiasCorrector")

class BaseBiasCorrector:
    def get_bias(self, station_id: str, lat: float, lon: float, timezone: str, target_date: str, is_lowest: bool, **kwargs) -> tuple:
        """
        根据气象站、坐标、时区和目标日期，计算温度偏置纠正量 (Celsius)、滚动残差标准差 (Celsius, 可为 None)、逐日残差列表
        """
        raise NotImplementedError

class MovingWindowBiasCorrector(BaseBiasCorrector):
    def get_bias(self, station_id: str, lat: float, lon: float, timezone: str, target_date: str, is_lowest: bool, **kwargs) -> tuple:
        """
        基于滑动窗口残差 (Moving Window Residual) 自适应计算偏置，优先使用本地缓存，支持增量拉取。
        返回 (avg_bias, rolling_std_dev, daily_residuals)
        """
        window_days = kwargs.get("window_days", 7)
        
        try:
            target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        except Exception as e:
            logger.error(f"解析目标日期 {target_date} 失败: {e}")
            return 0.0, None, []
            
        # 1. 计算过去 N 天的日期窗口 (从 T-window_days 到 T-1)
        start_dt = target_dt - datetime.timedelta(days=window_days)
        dates_in_window = [(start_dt + datetime.timedelta(days=d)).strftime("%Y-%m-%d") for d in range(window_days)]
        
        # 2. 批量读取本地 SQLite 缓存
        cached_data = weather_cache.get_cached_stats(station_id, dates_in_window, is_lowest, include_completion=True)
        
        # 3. 找出缺失的日期或非完整拉取的日期，并在已结束的情况下进行更新
        import pytz
        try:
            tz = pytz.timezone(timezone)
            station_now = datetime.datetime.now(tz)
        except Exception:
            station_now = datetime.datetime.now()
        station_today_str = station_now.strftime("%Y-%m-%d")
        
        missing_dates = []
        for d in dates_in_window:
            if d < station_today_str:
                if d not in cached_data:
                    missing_dates.append(d)
                else:
                    _, _, is_comp = cached_data[d]
                    if not is_comp:
                        missing_dates.append(d)
        
        # 4. 如果有缺失日期，优先从归档读取预报，缺失的再回退到 API
        if missing_dates:
            # 4a. 尝试从归档读取预报数据（使用真正的当时预报，而非再分析值）
            archive_forecasts = self._read_forecast_from_archive(lat, lon, missing_dates, is_lowest)

            # 4b. 对归档中找到的日期，用 Wunderground 实况计算残差并写入缓存
            if archive_forecasts:
                wu_history = weather_cache.fetch_wunderground_daily_history(station_id)
                for day_str, mean_forecast_extreme in archive_forecasts.items():
                    day_wu = wu_history.get(day_str)
                    if not day_wu:
                        logger.warning(f"[{station_id}] 归档命中 {day_str} 预报，但 Wunderground 历史极值未包含此日期，跳过")
                        continue
                    obs_extreme = day_wu["min_temp"] if is_lowest else day_wu["max_temp"]
                    if obs_extreme is None:
                        continue
                    is_comp = 1 if day_str < station_today_str else 0
                    weather_cache.save_cached_stats(station_id, day_str, is_lowest, mean_forecast_extreme, obs_extreme, is_complete=is_comp)
                    cached_data[day_str] = (mean_forecast_extreme, obs_extreme, is_comp)
                    logger.info(f"[{station_id}] 日期 {day_str} 从归档读取预报 ({mean_forecast_extreme:.2f}°C) 并写入缓存")
                    if day_str in missing_dates:
                        missing_dates.remove(day_str)

        # 4c. 仍缺失的日期，回退到 historical-forecast-api（再分析值，精度较低）
        if missing_dates:
            min_missing = min(missing_dates)
            max_missing = max(missing_dates)
            
            logger.info(f"[{station_id}] 本地缓存未完全命中。缺失日期: {missing_dates}。开始增量拉取范围 {min_missing} 至 {max_missing} ...")
            
            # 拉取预报历史数据 (ICON40 集合预报)
            forecast_url = "https://historical-forecast-api.open-meteo.com/v1/forecast"
            forecast_params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": min_missing,
                "end_date": max_missing,
                "hourly": "temperature_2m",
                "models": "icon_seamless",
                "timezone": timezone
            }
            
            # 优先读取本地 API 缓存 (历史预报是历史数据，极少发生变化，设定 12 小时缓存有效期)
            f_data = weather_cache.get_api_cache(forecast_url, forecast_params, expire_seconds=43200)
            
            if not f_data:
                time.sleep(0.3)  # 礼貌限频延迟
                try:
                    resp_f = requests.get(forecast_url, params=forecast_params, proxies=PROXIES, timeout=10)
                    if resp_f.status_code != 200:
                        logger.warning(f"获取历史预报失败, 状态码: {resp_f.status_code}。跳过本次增量纠偏。")
                        return 0.0, None, []
                    f_data = resp_f.json()
                    weather_cache.save_api_cache(forecast_url, forecast_params, f_data)
                except Exception as e:
                    logger.warning(f"获取历史预报异常: {e}。跳过本次增量纠偏。")
                    return 0.0, None, []
                
            # 拉取真实观测数据 (Wunderground TWC v3)
            wu_history = weather_cache.fetch_wunderground_daily_history(station_id)
            
            # 解析数据并写入缓存
            f_hourly = f_data.get("hourly", {})
            f_times = f_hourly.get("time", [])
            
            member_keys = ["temperature_2m"] + [f"temperature_2m_member{i:02d}" for i in range(1, 40)]
            
            # 处理获取到的每一天并保存
            for day_str in missing_dates:
                # A. 提取该日预报均值
                f_day_indices = [idx for idx, t_str in enumerate(f_times) if t_str.startswith(day_str)]
                if not f_day_indices:
                    continue
                    
                day_member_extrema = []
                for m_key in member_keys:
                    if m_key not in f_hourly:
                        continue
                    m_temps = f_hourly[m_key]
                    day_temps = [m_temps[idx] for idx in f_day_indices if m_temps[idx] is not None]
                    if day_temps:
                        day_member_extrema.append(min(day_temps) if is_lowest else max(day_temps))
                        
                if not day_member_extrema:
                    continue
                mean_forecast_extreme = np.mean(day_member_extrema)
                
                # B. 提取该日观测实况值 (来自 Wunderground)
                day_wu = wu_history.get(day_str)
                if not day_wu:
                    logger.warning(f"[{station_id}] Wunderground 历史极值未包含日期 {day_str}，跳过此日缓存写入")
                    continue
                obs_extreme = day_wu["min_temp"] if is_lowest else day_wu["max_temp"]
                if obs_extreme is None:
                    continue
                
                # 写入 SQLite 缓存
                is_comp = 1 if day_str < station_today_str else 0
                weather_cache.save_cached_stats(station_id, day_str, is_lowest, mean_forecast_extreme, obs_extreme, is_complete=is_comp)
                # 更新本地临时字典
                cached_data[day_str] = (mean_forecast_extreme, obs_extreme, is_comp)
                logger.info(f"[{station_id}] 日期 {day_str} 历史预报/Wunderground实况已计算并写入本地缓存")
        
        
        # 5. 统一从已补全的 cached_data 中提取并计算最终 residuals
        daily_residuals = []
        for day_str in dates_in_window:
            if day_str in cached_data:
                mean_forecast_extreme, obs_extreme = cached_data[day_str][:2]
                residual = obs_extreme - mean_forecast_extreme
                daily_residuals.append(residual)
                logger.debug(f"[{station_id}] 日期: {day_str} | 实况: {obs_extreme:.2f}°C | 预报均值: {mean_forecast_extreme:.2f}°C | 残差: {residual:+.2f}°C")
                
        if not daily_residuals:
            logger.warning(f"[{station_id}] 过去 {window_days} 天无任何可对齐计算的残差数据，偏置修正与滚动标准差设为 0 与 None")
            return 0.0, None, []

        avg_bias = float(np.mean(daily_residuals))
        # 样本数 >= 4 时才计算并信任滚动标准差，否则返回 None (触发兜底)
        std_dev = float(np.std(daily_residuals, ddof=1)) if len(daily_residuals) >= 4 else None

        logger.info(f"[{station_id}] 自适应温度纠偏计算完成。样本天数: {len(daily_residuals)} | 平均偏差 Bias: {avg_bias:+.3f}°C | 滚动标准差 StdDev: {f'{std_dev:.3f}°C' if std_dev is not None else 'None (使用兜底)'} (缓存命中天数: {window_days - len(missing_dates)}/{window_days})")
        return avg_bias, std_dev, daily_residuals

    def _read_forecast_from_archive(self, lat: float, lon: float, dates: list, is_lowest: bool) -> dict:
        """
        从 storage/archive/ 读取指定日期的预报极值。
        对每个日期 D，查找 D-1 和 D-2 日收集的归档（真正的当时预报），
        通过 lat/lon 匹配确认是同一站点，提取 D 日的集合预报极值均值。
        返回 {date_str: mean_forecast_extreme} 字典。
        """
        import glob
        import os
        import json as _json

        ARCHIVE_DIR = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "archive"
        )

        if not os.path.isdir(ARCHIVE_DIR):
            return {}

        result = {}
        member_keys = ["temperature_2m"] + [f"temperature_2m_member{i:02d}" for i in range(1, 40)]

        for day_str in dates:
            try:
                day_dt = datetime.datetime.strptime(day_str, "%Y-%m-%d")
            except Exception:
                continue

            # 查找 D-1 和 D-2 日收集的归档（优先 D-1，即最接近当天的预报）
            for offset in [1, 2]:
                collect_dt = day_dt - datetime.timedelta(days=offset)
                collect_prefix = collect_dt.strftime("%Y%m%d")
                pattern = os.path.join(ARCHIVE_DIR, f"{collect_prefix}_*.json")
                candidates = glob.glob(pattern)

                if not candidates:
                    continue

                for fpath in candidates:
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = _json.load(f)

                        raw_forecast = data.get("raw_data", {}).get("raw_forecast", {})
                        f_lat = raw_forecast.get("latitude")
                        f_lon = raw_forecast.get("longitude")

                        if f_lat is None or f_lon is None:
                            continue
                        # lat/lon 匹配容差 0.05°（约 5km）
                        if abs(f_lat - lat) > 0.05 or abs(f_lon - lon) > 0.05:
                            continue

                        # 匹配成功，提取 day_str 的 24 小时预报
                        hourly = raw_forecast.get("hourly", {})
                        times = hourly.get("time", [])
                        day_indices = [i for i, t in enumerate(times) if t.startswith(day_str)]

                        if not day_indices:
                            continue

                        member_extrema = []
                        for m_key in member_keys:
                            if m_key not in hourly:
                                continue
                            temps = hourly[m_key]
                            day_temps = [temps[i] for i in day_indices if i < len(temps) and temps[i] is not None]
                            if day_temps:
                                member_extrema.append(min(day_temps) if is_lowest else max(day_temps))

                        if member_extrema:
                            result[day_str] = float(np.mean(member_extrema))
                            break  # 找到匹配，不再遍历候选文件
                    except Exception:
                        continue

                if day_str in result:
                    break  # D-1 找到了，不用看 D-2

        return result

# 模块注册工厂
CORRECTORS = {
    "MovingWindowBiasCorrector": MovingWindowBiasCorrector
}

def get_bias_corrector(class_name: str) -> BaseBiasCorrector:
    if class_name not in CORRECTORS:
        logger.error(f"未定义的纠偏实现类: {class_name}，fallback 至 MovingWindowBiasCorrector")
        return MovingWindowBiasCorrector()
    return CORRECTORS[class_name]()
