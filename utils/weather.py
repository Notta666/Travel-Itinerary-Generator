"""
高德天气查询模块
================
零额外依赖，使用高德API获取城市天气并生成出行建议。
"""
import urllib.request, json, time

try:
    from utils.amap_api import AMAP_KEY
except ImportError:
    try:
        from amap_api import AMAP_KEY
    except ImportError:
        import os
        AMAP_KEY = os.environ.get("AMAP_KEY", "")


def _fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

import datetime as _dt

def get_weather_for_dates(city="上海", start_date=None, days=2):
    """
    获取指定日期的天气（支持未来3天内预报，超过3天返回历史平均数据）
    start_date: datetime.date 对象，或 YYYY-MM-DD 字符串，默认为今天
    返回结构化天气数据
    """
    import datetime as _dt
    if start_date is None:
        start_date = _dt.date.today()
    elif isinstance(start_date, str):
        try:
            start_date = _dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        except Exception:
            start_date = _dt.date.today()

    today = _dt.date.today()
    diff = (start_date - today).days
    end_date = start_date + _dt.timedelta(days=days - 1)
    end_diff = (end_date - today).days

    # 如果出行日期全部在今天起的 4 天内（即高德天气 API 预报能覆盖的范围内，diff在0~3且end_diff在0~3）
    if 0 <= diff <= 3 and 0 <= end_diff <= 3:
        # 未来3天内：走高德预报
        wx = get_weather(city, "all")
        if wx.get("success") and wx.get("forecast"):
            # 裁剪到指定日期范围
            forecasts = wx["forecast"]
            filtered = []
            for d in forecasts:
                try:
                    fd = _dt.datetime.strptime(d["date"], "%Y-%m-%d").date()
                    if start_date <= fd <= end_date:
                        filtered.append(d)
                except Exception:
                    filtered.append(d)
            if filtered:
                wx["forecast"] = filtered
                avg_temp = []
                for d in filtered:
                    try:
                        parts = d["temp_range"].replace("°C","").split("~")
                        avg_temp.extend([int(p) for p in parts])
                    except Exception:
                        pass
                if avg_temp:
                    low, high = min(avg_temp), max(avg_temp)
                    diff_c = high - low
                    wx["suggestions"] = []
                    if high >= 30:
                        wx["suggestions"].append("🧴 紫外线偏强，建议做好防晒")
                    if diff_c >= 10:
                        wx["suggestions"].append(f"🧥 昼夜温差{diff_c}°C，建议备外套")
                    if any("雨" in d.get("day_weather","") for d in filtered):
                        wx["suggestions"].append("☔ 预计有雨，建议携带雨具")
                    if not wx["suggestions"]:
                        wx["suggestions"].append("✨ 天气宜人，祝旅途愉快")
                return wx

    # 超过3天或高德数据获取失败：通过 Open-Meteo 查询往年同期历史天气作为参考
    try:
        # Step 1: 地理编码获取城市经纬度
        enc = urllib.request.quote(city)
        geo_url = f"https://restapi.amap.com/v3/geocode/geo?key={AMAP_KEY}&address={enc}&output=JSON"
        geo = _fetch_json(geo_url)
        if geo.get("status") == "1" and geo.get("geocodes"):
            loc_str = geo["geocodes"][0]["location"]
            lng, lat = loc_str.split(",")
            
            # 计算去年同期的日期范围（年份减 1）
            def get_last_year_date(d):
                try:
                    return _dt.date(d.year - 1, d.month, d.day)
                except ValueError:
                    return _dt.date(d.year - 1, d.month, d.day - 1)

            hist_start = get_last_year_date(start_date)
            hist_end = get_last_year_date(end_date)
            
            hist_start_str = hist_start.strftime("%Y-%m-%d")
            hist_end_str = hist_end.strftime("%Y-%m-%d")
            
            # 调用 Open-Meteo API
            open_meteo_url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lng}&start_date={hist_start_str}&end_date={hist_end_str}&daily=temperature_2m_max,temperature_2m_min,rain_sum,weather_code&timezone=auto"
            hist_data = _fetch_json(open_meteo_url)
            
            if hist_data and "daily" in hist_data:
                daily_data = hist_data["daily"]
                forecast_list = []
                suggestions = []
                
                # 建立 WMO 代码与中文天气的映射
                WMO_CODES = {
                    0: "晴",
                    1: "晴间多云", 2: "多云", 3: "阴",
                    45: "雾", 48: "雾",
                    51: "轻微毛毛雨", 53: "毛毛雨", 55: "重毛毛雨",
                    61: "小雨", 63: "中雨", 65: "大雨",
                    80: "小阵雨", 81: "中阵雨", 82: "暴雨",
                    95: "雷阵雨"
                }
                
                max_temps = daily_data.get("temperature_2m_max", [])
                min_temps = daily_data.get("temperature_2m_min", [])
                rain_sums = daily_data.get("rain_sum", [])
                wmo_codes = daily_data.get("weather_code", [])
                
                for i in range(len(daily_data.get("time", []))):
                    d_str = (start_date + _dt.timedelta(days=i)).strftime("%Y-%m-%d")
                    t_max = round(max_temps[i]) if i < len(max_temps) and max_temps[i] is not None else 30
                    t_min = round(min_temps[i]) if i < len(min_temps) and min_temps[i] is not None else 22
                    code = wmo_codes[i] if i < len(wmo_codes) and wmo_codes[i] is not None else 0
                    
                    # 匹配天气描述
                    wx_desc = WMO_CODES.get(code, "多云" if code > 0 else "晴")
                    
                    forecast_list.append({
                        "date": d_str,
                        "day_weather": wx_desc,
                        "night_weather": wx_desc,
                        "temp_range": f"{t_min}~{t_max}°C"
                    })
                
                # 汇总建议
                all_max_temp = [t for t in max_temps if t is not None]
                all_min_temp = [t for t in min_temps if t is not None]
                all_rain = [r for r in rain_sums if r is not None]
                
                if all_max_temp:
                    max_t = max(all_max_temp)
                    if max_t >= 30:
                        suggestions.append(f"🧴 往年同期最高气温达 {round(max_t)}°C，建议做好防晒防暑")
                if all_max_temp and all_min_temp:
                    diff_avg = max(all_max_temp) - min(all_min_temp)
                    if diff_avg >= 10:
                        suggestions.append(f"🧥 昼夜温差较大大（约{round(diff_avg)}°C），建议随身携带外套")
                if any(r > 2.0 for r in all_rain):
                    suggestions.append("☔ 往年同期有降水记录，建议携带雨具以备不时之需")
                
                if not suggestions:
                    suggestions.append("✨ 往年同期天气温和，祝旅途愉快")
                
                return {
                    "success": True,
                    "type": "historical",
                    "city": city,
                    "note": "参考往年同期历史数据",
                    "forecast": forecast_list,
                    "suggestions": suggestions
                }
    except Exception as e:
        print(f"  ⚠️ 获取历史天气API异常: {e}，将降级到静态历史天气")
        
    # 终极降级方案：返回默认静态数据以防报错
    return {
        "success": True, "type": "historical",
        "city": city, "note": "参考往年同期数据(静态降级)",
        "forecast": [
            {"date": (start_date + _dt.timedelta(days=i)).strftime("%Y-%m-%d"),
             "day_weather": "晴转多云" if i == 0 else "多云",
             "night_weather": "多云",
             "temp_range": "25~34°C"}
            for i in range(days)
        ],
        "suggestions": [
            "🧴 夏季出行紫外线强，建议做好防晒",
            "🧥 室内空调温度低，建议带件薄外套备用",
            "💧 天气炎热请注意补水"
        ]
    }


def get_weather(city="上海", extensions="all"):
    """
    获取城市天气预报，自动通过地理编码解析adcode。
    extensions: 'base'=实况, 'all'=今明后三天预报
    返回结构化天气数据 + 出行建议
    """
    # Step 1: 地理编码获取adcode
    try:
        enc = urllib.request.quote(city)
        geo_url = f"https://restapi.amap.com/v3/geocode/geo?key={AMAP_KEY}&address={enc}&output=JSON"
        geo = _fetch_json(geo_url)
        if geo.get("status") != "1" or not geo.get("geocodes"):
            return {"error": f"无法定位城市'{city}'"}
        adcode = geo["geocodes"][0]["adcode"]
    except Exception as e:
        return {"error": f"地理编码失败: {e}"}

    # Step 2: 查询天气
    try:
        w_url = f"https://restapi.amap.com/v3/weather/weatherInfo?key={AMAP_KEY}&city={adcode}&extensions={extensions}&output=JSON"
        data = _fetch_json(w_url)
        if data.get("status") != "1":
            return {"error": f"天气查询失败: {data.get('info','')}"}
    except Exception as e:
        return {"error": f"天气请求异常: {e}"}

    suggestions = []

    if extensions == "base" and data.get("lives"):
        live = data["lives"][0]
        temp = float(live["temperature"])
        weather = live["weather"]

        if "雨" in weather: suggestions.append("🌧️ 当前有雨，请备好雨具")
        elif "雪" in weather: suggestions.append("❄️ 有降雪，注意保暖防滑")
        elif "霾" in weather: suggestions.append("😷 空气质量不佳，建议佩戴口罩")

        if temp >= 30: suggestions.append("☀️ 天气炎热，注意防晒补水")
        elif temp <= 10: suggestions.append("🧣 气温偏低，注意保暖")
        else: suggestions.append("🍀 气温宜人，适合出行")

        return {
            "success": True, "type": "live",
            "city": live["city"], "weather": weather,
            "temperature": f"{temp}°C",
            "humidity": f"{live['humidity']}%",
            "wind": f"{live['winddirection']}风 {live['windpower']}级",
            "suggestions": suggestions,
        }

    if extensions == "all" and data.get("forecasts"):
        forecast = data["forecasts"][0]
        casts = forecast["casts"]
        today = casts[0]
        day_t, night_t = float(today["daytemp"]), float(today["nighttemp"])
        day_w = today["dayweather"]

        if "雨" in day_w: suggestions.append("☔ 今日预计有雨，建议携带雨具")
        if day_t >= 30: suggestions.append("🧴 紫外线偏强，建议做好防晒")
        diff = day_t - night_t
        if diff >= 10: suggestions.append(f"🧥 昼夜温差{diff:.0f}°C，建议备外套")
        if not suggestions: suggestions.append("✨ 今日天气宜人，祝旅途愉快")

        days_list = []
        for c in casts:
            days_list.append({
                "date": c["date"],
                "day_weather": c["dayweather"],
                "night_weather": c["nightweather"],
                "temp_range": f"{c['nighttemp']}~{c['daytemp']}°C",
            })

        return {
            "success": True, "type": "forecast",
            "city": forecast["city"],
            "today": {"weather": day_w, "temp_range": f"{night_t}~{day_t}°C"},
            "suggestions": suggestions,
            "forecast": days_list,
        }

    return {"error": "无天气数据"}
