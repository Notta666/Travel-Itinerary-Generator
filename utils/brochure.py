"""
旅游手册生成器 — 图文并茂 + 交互地图
========================================
一本包含: 封面 → 每日行程(图片卡片) → 交互式Leaflet地图 → 必吃推荐 → 交通指南
"""

import os, json, time, urllib.request, hashlib

try:
    from utils.amap_api import AMAP_KEY
except ImportError:
    try:
        from amap_api import AMAP_KEY
    except ImportError:
        AMAP_KEY = os.environ.get("AMAP_KEY", "")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_photo_cache = {}
_last_fetch_time = 0

def _get_single_city(name, overall_city):
    if not overall_city:
        return "上海"
    cities = [c.strip() for c in overall_city.replace("，", ",").split(",") if c.strip()]
    if len(cities) <= 1:
        return overall_city
    # 针对多城市列表，根据关键字自动匹配具体城市
    for c in cities:
        if c in name:
            return c
    # 特殊规则映射
    if any(k in name for k in ["大三巴", "威尼斯人", "葡", "马介休", "玛嘉烈", "安东尼奥", "蛋挞"]):
        return "澳门"
    if any(k in name for k in ["清晖", "逢简", "顺德", "双皮奶", "大良", "猪肉婆"]):
        return "佛山"
    if any(k in name for k in ["渔女", "情侣", "日月贝", "新海利", "金悦轩", "横琴"]):
        return "珠海"
    if any(k in name for k in ["广州塔", "陈家祠", "炳胜", "点都德", "沙面", "陶陶居"]):
        return "广州"
    return cities[0]

def _fetch_photos(name, city="上海"):
    """高德API获取POI照片，带重试和限流"""
    global _last_fetch_time
    if name in _photo_cache:
        return _photo_cache[name]
    urls = []

    import re
    # 移除括号及其内的分店名信息（如 陶陶居（荔湾店） -> 陶陶居）
    cleaned = re.sub(r'[\uff08(].*?[\uff09)]', '', name).strip()

    single_city = _get_single_city(cleaned, city)
    if single_city == "顺德":
        single_city = "佛山"
    # 前缀补全搜索词以提升配图精准度
    search_name = cleaned
    if single_city not in cleaned and not any(k in cleaned for k in ["澳门", "佛山", "顺德", "珠海", "广州"]):
        search_name = f"{single_city}{cleaned}"

    # 限流：每次请求间隔至少 0.2s
    import time as _t
    elapsed = _t.time() - _last_fetch_time
    if elapsed < 0.2:
        _t.sleep(0.2 - elapsed)
    # 高德API（最多重试2次）
    # 高德API（最多重试2次）
    from utils.amap_api import _request
    for attempt in range(2):
        try:
            kw = urllib.request.quote(search_name)
            ct = urllib.request.quote(single_city)
            url = f"https://restapi.amap.com/v5/place/text?key={AMAP_KEY}&keywords={kw}&region={ct}&city_limit=true&page_size=1&show_fields=photos"
            data = _request(url)
            if data.get("status")=="1" and data.get("pois"):
                photos = data["pois"][0].get("photos", [])
                if photos:
                    urls = [p["url"] for p in photos[:2]]
                    break
        except:
            if attempt == 0:
                _t.sleep(1.0)
            continue
    _last_fetch_time = _t.time()
    if not urls:
        # 降级：百度/Bing搜图
        try:
            from utils.image_fetcher import get_photos as _gp
            urls = _gp(search_name, single_city)
        except:
            pass
    _photo_cache[name] = urls
    return urls


def _fetch_photos_batch(poi_items, default_city="上海", max_workers=2):
    """批量并行获取POI照片"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for item in poi_items:
            if isinstance(item, tuple):
                name, single_city = item
            else:
                name, single_city = item, default_city
            # If single_city is empty, fallback to default_city
            if not single_city:
                single_city = default_city
            futures[ex.submit(_fetch_photos, name, single_city)] = name
        for f in as_completed(futures):
            name = futures[f]
            try:
                results[name] = f.result()
            except Exception:
                results[name] = []
    return results


def _search_hotels(location, city="上海", radius=1500):
    """高德搜索附近酒店(types=100000)，带限流与城市越界过滤"""
    global _last_fetch_time
    import time as _t
    elapsed = _t.time() - _last_fetch_time
    if elapsed < 0.2:
        _t.sleep(0.2 - elapsed)
    try:
        loc = f"{location[0]},{location[1]}" if isinstance(location, (list,tuple)) else location
        url = f"https://restapi.amap.com/v5/place/around?key={AMAP_KEY}&location={loc}&radius={radius}&types=100000&sortrule=weight&page_size=10&show_fields=business,rating,cost,tel"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        _last_fetch_time = _t.time()
        results = []
        for p in data.get("pois", []):
            name = p.get("name", "")
            address = p.get("address", "")
            if city == "珠海" and any(x in name or x in address for x in ["澳门", "特别行政区", "Macau", "MACAU"]):
                continue
            if city == "广州" and any(x in name or x in address for x in ["佛山", "顺德"]):
                continue
            biz = p.get("business", {})
            results.append({
                "name": name,
                "location": p.get("location", ""),
                "address": address,
                "rating": biz.get("rating", ""),
                "cost": biz.get("cost", ""),
                "tel": biz.get("tel", ""),
                "distance": p.get("distance", 0),
            })
        return results[:5]
    except:
        _last_fetch_time = _t.time()
        return []


_POI_GRADIENTS = [
    "linear-gradient(135deg,#667eea,#764ba2)", "linear-gradient(135deg,#f093fb,#f5576c)",
    "linear-gradient(135deg,#4facfe,#00f2fe)", "linear-gradient(135deg,#fa709a,#fee140)",
    "linear-gradient(135deg,#a18cd1,#fbc2eb)", "linear-gradient(135deg,#fccb90,#d57eeb)",
    "linear-gradient(135deg,#e0c3fc,#8ec5fc)", "linear-gradient(135deg,#43e97b,#38f9d7)",
]
_FOOD_GRADIENTS = [
    "linear-gradient(135deg,#ff6b35,#f7c948)", "linear-gradient(135deg,#e17055,#fd9a6e)",
    "linear-gradient(135deg,#ff7675,#fdcb6e)", "linear-gradient(135deg,#e84393,#fd79a8)",
]

def _color_for(name, is_food):
    pool = _FOOD_GRADIENTS if is_food else _POI_GRADIENTS
    return pool[hash(name) % len(pool)]


def generate_brochure(itinerary, city, food_highlights=None, overall_note="",
                       transport="", accommodation="", budget="", preference="", tips=None, weather=None, start_city="", people_count=2):
    """生成「图文手册+交互地图」单文件HTML，含交通/住宿/预算等"""
    import datetime as _dt
    date_range_str = ""
    if weather and weather.get("forecast"):
        forecasts = weather["forecast"]
        try:
            d1 = _dt.datetime.strptime(forecasts[0]["date"], "%Y-%m-%d")
            d2 = _dt.datetime.strptime(forecasts[-1]["date"], "%Y-%m-%d")
            if d1.month == d2.month:
                date_range_str = f"{d1.month}月{d1.day}日—{d2.day}日"
            else:
                date_range_str = f"{d1.month}月{d1.day}日—{d2.month}月{d2.day}日"
        except Exception:
            date_range_str = f"{forecasts[0]['date']}—{forecasts[-1]['date']}"
    if not date_range_str:
        date_range_str = "出行日期"

    num_days = len(itinerary) if itinerary else 2
    day_label_map = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七"}
    trip_label = f"{day_label_map.get(num_days, str(num_days))}日深度游"

    day_html_parts = []
    all_items_flat = []
    hotel_html_parts = []
    all_hotels_data = []  # 存储所有酒店数据供 JS 使用
    total_km = 0

    # 预批量获取所有照片
    all_poi_items = []
    for day in itinerary:
        for poi in day.get("pois", []):
            all_poi_items.append((poi["name"], poi.get("city", "")))
        for food in day.get("foods", []):
            all_poi_items.append((food["name"], food.get("city", "")))
    photo_cache = _fetch_photos_batch(all_poi_items, city) if all_poi_items else {}

    # 预批量搜索酒店
    from concurrent.futures import ThreadPoolExecutor
    from utils.amap_api import AMapClient
    amap = AMapClient()
    hotel_locations = []
    dest_cities = [c.strip() for c in city.replace("，", ",").split(",") if c.strip()]
    
    for day in itinerary:
        stay_city = day.get("accommodation_city", "").strip()
        # 自动兜底逻辑：如果LLM没有显式输出当晚住宿城市
        if not stay_city:
            if day["day"] in [1, 2] and len(dest_cities) >= 1:
                stay_city = dest_cities[0]
            elif day["day"] in [3, 4] and len(dest_cities) >= 3:
                stay_city = dest_cities[2]
            elif day["day"] < num_days and dest_cities:
                stay_city = dest_cities[0]
            else:
                stay_city = ""
                
        if not stay_city:
            hotel_locations.append((day["day"], None, ""))
            continue
            
        city_center = amap.geocode(stay_city)
        day_locs = []
        for s in (day.get("pois", []) + day.get("foods", [])):
            loc = s.get("location")
            if loc and city_center:
                dist = ((loc[0] - city_center[0])**2 + (loc[1] - city_center[1])**2)**0.5 * 111
                if dist < 45:
                    day_locs.append(loc)
                    
        # 若当天在该宿地城市无景点活动坐标，寻找其他天的同宿城景点坐标
        if not day_locs:
            for other_day in itinerary:
                other_stay_city = other_day.get("accommodation_city", "").strip()
                if other_stay_city == stay_city:
                    for s in (other_day.get("pois", []) + other_day.get("foods", [])):
                        loc = s.get("location")
                        if loc and city_center:
                            dist = ((loc[0] - city_center[0])**2 + (loc[1] - city_center[1])**2)**0.5 * 111
                            if dist < 45:
                                day_locs.append(loc)
                    if day_locs:
                        break
                        
        if day_locs:
            clng = sum(l[0] for l in day_locs) / len(day_locs)
            clat = sum(l[1] for l in day_locs) / len(day_locs)
            hotel_locations.append((day["day"], [clng, clat], stay_city))
        else:
            hotel_locations.append((day["day"], city_center, stay_city))

    hotel_cache = {}
    def _search_one(args):
        day_num, loc, s_city = args
        if loc and s_city:
            return day_num, _search_hotels(loc, s_city)
        return day_num, []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for day_num, hotels in ex.map(_search_one, hotel_locations):
            hotel_cache[day_num] = hotels

    for di, day in enumerate(itinerary):
        slots = []
        day_locations = []
        for poi in day.get("pois", []):
            photos = photo_cache.get(poi["name"], [])
            slots.append({"type":"sight","data":poi,"photos":photos})
            if poi.get("location"): day_locations.append(poi["location"])
        for food in day.get("foods", []):
            photos = photo_cache.get(food["name"], [])
            slots.append({"type":"food","data":food,"photos":photos})

        # 使用预搜索的酒店缓存
        hotels = hotel_cache.get(day["day"], [])
        if hotels:
            day_num = day["day"]
            hc = ""
            for hi, h in enumerate(hotels[:3]):
                cost_val = h.get("cost", "")
                cost_display = f"¥{cost_val}/晚" if cost_val and cost_val != "?" else "暂无报价"
                cost_class = "hpr" if cost_val and cost_val != "?" else "hpr no-price"
                rating_val = h.get("rating", "")
                rating_display = rating_val if rating_val and rating_val != "?" else "--"
                dist_val = h.get("distance", "")
                dist_display = f"{dist_val}m" if dist_val else ""
                tel_val = h.get("tel", "")
                tel_html = f'<span class="htel">📞 {tel_val}</span>' if tel_val else ""
                selected_class = "selected" if hi == 0 else ""
                hc += (
                    f'<div class="hc {selected_class}" data-day="{day_num}" data-idx="{hi}" onclick="selectHotel({day_num},{hi})">' 
                    f'<div class="hc-check">{"✓" if hi == 0 else ""}</div>'
                    f'<div class="hc-info">'
                    f'<div class="hc-row1"><span class="hn">{h["name"]}</span><span class="hsg">⭐{rating_display}</span></div>'
                    f'<div class="hc-row2"><span class="{cost_class}">{cost_display}</span>'
                    f'{f"<span class=hdi>{dist_display}</span>" if dist_display else ""}'
                    f'{tel_html}</div>'
                    f'</div>'
                    f'</div>'
                )
                hloc = h.get("location", "")
                if isinstance(hloc, str) and "," in hloc:
                    hlng, hlat = hloc.split(",")
                    all_items_flat.append({"name":h["name"],"loc":[float(hlng),float(hlat)],"type":"hotel","day":day_num,"time":"","hIdx":hi})
                    all_hotels_data.append({"name":h["name"],"loc":[float(hlng),float(hlat)],"day":day_num,"idx":hi,"rating":rating_display,"cost":cost_display})
            hotel_html_parts.append(f'<div class="hs"><div class="ht">Day {day_num} 推荐住宿 <span class="ht-hint">点击选择 · 联动地图</span></div><div class="hw">{hc}</div></div>')

        def _tk(s):
            t = s["data"].get("time_slot","")
            for p in ["09","10","11","12","13","14","15","16","17","18"]:
                if p in t: return int(p)
            return 12
        slots.sort(key=_tk)

        day_html = ""
        for si, s in enumerate(slots):
            d, is_food = s["data"], s["type"]=="food"
            photos = s["photos"]
            has_photo = bool(photos)
            photo_url = photos[0] if has_photo else ""
            grad = _color_for(d["name"], is_food)
            bg = f'style="background-image:url(\'{photo_url}\');background-size:cover;background-position:center;"' if has_photo else f'style="background:{grad};"'

            side = "l" if si%2==0 else "r"
            icon, badge = ("🍴","🍴") if is_food else ("📍","🏛")
            name_short = d["name"][:10]+".." if len(d["name"])>10 else d["name"]

            tags = []
            if d.get("rating"):
                r = float(d["rating"]) if d["rating"] else 0
                tags.append(f'<span class="t {"g" if r>=4 else "m"}">★ {d["rating"]}</span>')
            if d.get("cost"): tags.append(f'<span class="t b">{d["cost"]}</span>')
            if is_food and d.get("cuisine"): tags.append(f'<span class="t o">🍳 {d["cuisine"]}</span>')
            if d.get("time_slot"): tags.append(f'<span class="t ti">🕐 {d["time_slot"]}</span>')
            transit_text = d.get("transit", "")
            if transit_text:
                if "步行" in transit_text or "走" in transit_text:
                    t_icon = "🚶"
                elif "地铁" in transit_text:
                    t_icon = "🚇"
                elif "公交" in transit_text or "巴士" in transit_text:
                    t_icon = "🚌"
                elif "骑" in transit_text:
                    t_icon = "🚲"
                elif "出发" in transit_text:
                    t_icon = "🏁"
                else:
                    t_icon = "🚗"
                tags.append(f'<span class="t tr">{t_icon} {transit_text}</span>')

            overlay = f'<div class="po">{name_short}</div>' if not has_photo else ""
            all_items_flat.append({"name":d["name"],"loc":d.get("location",[121.47,31.23]),"type":is_food,"day":day["day"],"time":d.get("time_slot","")})

            day_html += f"""
            <div class="cr {side}">
                <div class="cp" {bg}>{overlay}<div class="cb">{badge}</div></div>
                <div class="cc">
                    <h3>{icon} {d['name']}</h3>
                    <div class="tw">{' '.join(tags)}</div>
                    {f'<p class="ad">{d.get("address","")[:45]}</p>' if d.get("address") else ''}
                    {f'<p class="nt">{d.get("note","")}</p>' if d.get("note") else ''}
                </div>
            </div>"""

        d_label = f'第{day["day"]}天'
        if weather and weather.get("forecast") and di < len(weather["forecast"]):
            try:
                date_str = weather["forecast"][di]["date"]
                dt_obj = _dt.datetime.strptime(date_str, "%Y-%m-%d")
                d_label = f"{dt_obj.month}月{dt_obj.day}日"
            except Exception:
                pass
        day_html_parts.append(f"""
        <div class="ds">
            <div class="dh" style="background:linear-gradient(135deg,hsl({210+di*30},70%,50%),hsl({210+di*30},70%,30%));">
                <div class="dn">Day {day['day']}</div>
                <div class="dt">{day.get('label','')}</div>
                <div class="dd">{d_label}</div>
            </div>
            {f'<div class="dsm">{day.get("summary","")}</div>' if day.get("summary") else ''}
            <div class="ccont">{day_html}</div>
        </div>""")

    # 地图数据
    map_items_json = json.dumps(all_items_flat, ensure_ascii=False)

    # 美食推荐
    # 出行建议
    thtml = ""
    if tips:
        general = tips.get("general", [])
        pref_tips = tips.get("preference_tips", [])
        daily = tips.get("daily_tips", [])
        emergency = tips.get("emergency", "")
        items = []
        for g in general[:5]:
            items.append(f'<li>{g}</li>')
        if pref_tips:
            for p in pref_tips[:3]:
                items.append(f'<li class="pt">🎯 {p}</li>')
        if daily:
            for d in daily[:3]:
                items.append(f'<li class="dt">📅 {d}</li>')
        if emergency:
            items.append(f'<li class="em">⚠️ {emergency}</li>')
        if items:
            thtml = f"""
    <div class="sec ts">
        <h2>💡 出行建议与注意事项</h2>
        <ul class="tl">{''.join(items)}</ul>
    </div>"""

    # 天气信息
    whtml = ""
    if weather and weather.get("success"):
        forecast = weather.get("forecast", [])
        wx_suggestions = weather.get("suggestions", [])
        cards = ""
        for d in forecast[:3]:
            cards += f'<div class="wf"><div class="wd">{d["date"][5:]}</div><div class="ww">{d["day_weather"]}</div><div class="wt">{d["temp_range"]}</div></div>'
        wx_sug = ""
        for s in wx_suggestions[:3]:
            wx_sug += f'<div class="ws">{s}</div>'
        whtml = f"""
    <div class="sec wx">
        <h2>🌤️ {weather["city"]} 天气预报</h2>
        <div class="wf-row">{cards}</div>
        <div class="ws-row">{wx_sug}</div>
    </div>"""

    # 预算估算
    import re as _re
    budget_html = ""
    if budget:
        days = len(itinerary) if itinerary else 2
        # 默认每人每天预算
        daily = 1500
        nums = _re.findall(r'\d+', budget.replace(',', ''))
        if nums:
            budget_vals = [int(n) for n in nums if int(n) >= 100]
            if budget_vals:
                val = max(budget_vals)
                is_daily = any(x in budget for x in ['天', '日', 'daily', '每天', '每日'])
                is_per_person = any(x in budget for x in ['人均', '每人', '每人每天', '人均每天', '单人', '/人'])
                specified_people = people_count
                match_people = _re.search(r'(\d+|两|三|四|五|六)人', budget)
                if match_people:
                    p_word = match_people.group(1)
                    if p_word == '两': specified_people = 2
                    elif p_word == '三': specified_people = 3
                    elif p_word == '四': specified_people = 4
                    elif p_word.isdigit(): specified_people = int(p_word)
                
                if is_daily:
                    if is_per_person:
                        daily = val
                    else:
                        daily = val // max(specified_people, 1)
                else:
                    if is_per_person:
                        daily = val // max(days, 1)
                    else:
                        daily = val // (max(specified_people, 1) * max(days, 1))
        daily = max(daily, 1)
        total_budget = daily * days * people_count
        accommodation_est = int(daily * 0.25)
        food_est = int(daily * 0.18)
        transport_est = int(daily * 0.12)
        ticket_est = int(daily * 0.25)
        shopping_est = daily - accommodation_est - food_est - transport_est - ticket_est
        budget_html = f"""
    <div class="sec bs">
        <h2>💰 预算概览（{days}天 · {people_count}人 · 约¥{daily}/天/人）</h2>
        <div class="bg">
            <div class="bi"><div class="bn">🏨 住宿</div><div class="bv">¥{accommodation_est*days*people_count}</div><div class="bp">{(accommodation_est/daily*100):.0f}%</div><div class="bb" style="width:{(accommodation_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🎫 门票</div><div class="bv">¥{ticket_est*days*people_count}</div><div class="bp">{(ticket_est/daily*100):.0f}%</div><div class="bb" style="width:{(ticket_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🍽️ 餐饮</div><div class="bv">¥{food_est*days*people_count}</div><div class="bp">{(food_est/daily*100):.0f}%</div><div class="bb" style="width:{(food_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🚗 交通</div><div class="bv">¥{transport_est*days*people_count}</div><div class="bp">{(transport_est/daily*100):.0f}%</div><div class="bb" style="width:{(transport_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🛍️ 其他</div><div class="bv">¥{shopping_est*days*people_count}</div><div class="bp">{(shopping_est/daily*100):.0f}%</div><div class="bb" style="width:{(shopping_est/daily*100):.0f}%"></div></div>
        </div>
        <div class="bt">预算合计 ≈ ¥{total_budget}（{transport or '出行方式'} · {people_count}人）</div>
    </div>"""

    fh_html = ""
    if food_highlights:
        chips = "".join(f'<div class="fc">{h}</div>' for h in food_highlights[:6])
        fh_html = f'<div class="sec fh"><h2>🏆 必吃推荐</h2><div class="fg">{chips}</div></div>'

    # 交通指南
    tg_parts = []
    if start_city:
        tg_parts.append(f'📍 起点：{start_city}')
    if accommodation:
        tg_parts.append(f'🏠 住宿：{accommodation}')
    if transport:
        tg_parts.append(f'🚗 交通：{transport}')
    if not tg_parts:
        tg_parts = ['各景点间交通便利，地铁/步行可达']
    tg_html = f"""
    <div class="sec tg">
        <h2>🚇 出行信息</h2>
        <p>{" | ".join(tg_parts)}</p>
    </div>"""

    ts = time.strftime("%Y-%m-%d")

    # 动态封面信息
    cover_extra = []
    if start_city: cover_extra.append(f'📍 起点：{start_city}')
    if transport: cover_extra.append(f'🚗 {transport}')
    if budget: cover_extra.append(f'💰 {budget}')
    if preference: cover_extra.append(f'🎯 {preference}')
    cover_extra_html = ' · '.join(cover_extra)

    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{city}旅行手册 | {trip_label}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Outfit:wght@600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{{--bg:#0a0d14;--text:#e8edf5;--text2:rgba(232,237,245,0.6);--text3:rgba(232,237,245,0.35);--card:rgba(255,255,255,0.03);--border:rgba(255,255,255,0.06);--border2:rgba(255,255,255,0.1);--tbg:rgba(255,255,255,0.05);--c1:#0f1729;--c2:#1a1f35;--mday1:hsl(210,70%,50%);--mday2:hsl(240,70%,50%);font-family:'Inter',sans-serif;color-scheme:dark;}}
[data-theme="light"]{{--bg:#f5f6fa;--text:#1a1d26;--text2:rgba(26,29,38,0.55);--text3:rgba(26,29,38,0.3);--card:rgba(255,255,255,0.85);--border:rgba(0,0,0,0.06);--border2:rgba(0,0,0,0.1);--tbg:rgba(0,0,0,0.04);--c1:#e8edf5;--c2:#d5dce8;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);max-width:960px;margin:0 auto;padding:0;transition:all .3s;}}
.tb{{position:fixed;top:20px;right:20px;z-index:999;width:40px;height:40px;border-radius:50%;border:1px solid var(--border2);background:var(--card);color:var(--text);font-size:18px;cursor:pointer;backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:center;}}
.tb:hover{{transform:scale(1.1);}}
.cover{{height:100vh;min-height:600px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:40px 20px;position:relative;overflow:hidden;background:linear-gradient(135deg,var(--c1),var(--c2));}}
.cover::before{{content:'';position:absolute;top:-50%;left:-50%;width:200%;height:200%;background:radial-gradient(ellipse at 30% 40%,rgba(100,180,255,0.08)0%,transparent 50%),radial-gradient(ellipse at 70% 60%,rgba(167,139,250,0.06)0%,transparent 50%);animation:fl 20s ease-in-out infinite;}}
@keyframes fl{{0%,100%{{transform:translate(0,0)}}50%{{transform:translate(-20px,-20px)}}}}
.cover h1{{font-family:'Outfit',sans-serif;font-size:52px;font-weight:900;position:relative;z-index:1;background:linear-gradient(135deg,#64b4ff,#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:12px;}}
.cs{{font-size:18px;color:var(--text3);position:relative;z-index:1;letter-spacing:2px;}}
.ci{{position:absolute;bottom:60px;left:0;right:0;font-size:14px;color:var(--text3);z-index:1;}}
.ci span{{margin:0 16px;}}
.ds{{margin:30px 12px;border-radius:20px;overflow:hidden;background:var(--card);border:1px solid var(--border);}}
.dh{{padding:30px 24px;color:#fff;position:relative;}}
.dn{{font-family:'Outfit',sans-serif;font-size:48px;font-weight:900;opacity:.15;position:absolute;top:10px;right:20px;}}
.dt{{font-size:24px;font-weight:700;}}
.dd{{font-size:14px;opacity:.7;margin-top:4px;}}
.dsm{{padding:16px 24px;font-size:14px;color:var(--text2);line-height:1.6;background:var(--tbg);border-bottom:1px solid var(--border);}}
.ccont{{padding:16px;}}
.cr{{display:flex;gap:16px;margin-bottom:16px;align-items:stretch;}}
.cr.r{{flex-direction:row-reverse;}}
.cp{{width:200px;min-height:160px;border-radius:16px;flex-shrink:0;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;}}
.po{{font-size:15px;font-weight:700;color:rgba(255,255,255,0.35);text-shadow:0 2px 8px rgba(0,0,0,0.3);}}
.cb{{position:absolute;top:8px;left:8px;width:32px;height:32px;border-radius:50%;background:rgba(0,0,0,0.45);backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;font-size:16px;border:1px solid rgba(255,255,255,0.15);}}
.cc{{flex:1;padding:4px 0;}}
.cc h3{{font-size:17px;font-weight:600;margin-bottom:8px;}}
.tw{{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin-bottom:6px;}}
.t{{font-size:11px;padding:3px 10px;border-radius:8px;font-weight:500;white-space:nowrap;display:inline-flex;align-items:center;gap:3px;}}
.t.g{{background:rgba(245,158,11,0.12);color:#f59e0b;border:1px solid rgba(245,158,11,0.25);}}
.t.m{{background:rgba(16,185,129,0.1);color:#10b981;border:1px solid rgba(16,185,129,0.2);}}
.t.b{{background:rgba(100,180,255,0.1);color:#64b4ff;border:1px solid rgba(100,180,255,0.2);}}
.t.o{{background:rgba(255,107,53,0.1);color:#ff6b35;border:1px solid rgba(255,107,53,0.2);}}
.t.ti{{background:rgba(148,163,184,0.1);color:#94a3b8;border:1px solid rgba(148,163,184,0.2);}}
.t.tr{{background:rgba(255,107,53,0.08);color:#ff6b35;border:1px solid rgba(255,107,53,0.15);}}
.ad{{font-size:12px;color:var(--text3);margin-bottom:4px;}}
.nt{{font-size:12px;color:var(--text2);line-height:1.5;}}

/* 地图专区 */
.map-section{{margin:20px 12px;border-radius:20px;overflow:hidden;border:1px solid var(--border);}}
.map-section h2{{padding:20px 24px 0;font-size:20px;}}
#map{{height:400px;width:100%;}}

.sec{{margin:20px 12px;padding:24px;border-radius:20px;}}
.fh{{background:linear-gradient(135deg,rgba(255,107,53,0.08),rgba(255,107,53,0.02));border:1px solid rgba(255,107,53,0.15);}}
.fh h2{{font-size:20px;margin-bottom:16px;}}
.fg{{display:flex;flex-wrap:wrap;gap:8px;}}
.fc{{padding:8px 16px;border-radius:12px;background:rgba(255,107,53,0.1);border:1px solid rgba(255,107,53,0.2);font-size:13px;color:#ff6b35;}}

/* 出行建议 */
.ts{{background:linear-gradient(135deg,rgba(245,158,11,0.04),rgba(251,191,36,0.02));border:1px solid rgba(245,158,11,0.1);}}
.ts h2{{font-size:20px;margin-bottom:14px;display:flex;align-items:center;gap:8px;}}
.tl{{list-style:none;padding:0;}}
.tl li{{padding:10px 14px;margin-bottom:6px;border-radius:12px;font-size:13px;line-height:1.6;color:var(--text);display:flex;align-items:flex-start;gap:8px;}}
.tl li:nth-child(1),.tl li:nth-child(2),.tl li:nth-child(3),.tl li:nth-child(4),.tl li:nth-child(5){{background:rgba(255,255,255,0.04);border:1px solid var(--border);}}
.tl li.pt{{background:linear-gradient(135deg,rgba(255,107,53,0.08),rgba(239,68,68,0.03));border:1px solid rgba(255,107,53,0.15);color:#ff6b35;}}
.tl li.dt{{background:linear-gradient(135deg,rgba(99,102,241,0.06),rgba(139,92,246,0.03));border:1px solid rgba(99,102,241,0.12);color:var(--text);}}
.tl li.em{{background:linear-gradient(135deg,rgba(245,158,11,0.08),rgba(245,158,11,0.03));border:1px solid rgba(245,158,11,0.15);color:#d97706;}}
/* 天气 */
.wx{{background:linear-gradient(135deg,rgba(16,185,129,0.06),rgba(52,211,153,0.04));border:1px solid rgba(16,185,129,0.12);}}
.wx h2{{font-size:20px;margin-bottom:12px;}}
.wf-row{{display:flex;gap:8px;margin-bottom:12px;}}
.wf{{flex:1;padding:10px;border-radius:12px;background:var(--tbg);border:1px solid var(--border);text-align:center;}}
.wd{{font-size:12px;font-weight:700;color:var(--text2);margin-bottom:4px;}}
.ww{{font-size:20px;margin-bottom:4px;}}
.wt{{font-size:11px;color:var(--text3);}}
.ws-row{{display:flex;flex-wrap:wrap;gap:6px;}}
.ws{{font-size:12px;padding:4px 10px;border-radius:8px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.15);color:var(--text2);}}

/* 酒店推荐 - 重设计 */
.hs{{margin:12px;padding:20px;border-radius:20px;background:linear-gradient(135deg,rgba(139,92,246,0.06),rgba(99,102,241,0.03));border:1px solid rgba(139,92,246,0.15);backdrop-filter:blur(8px);}}
.ht{{font-size:16px;font-weight:700;color:var(--text);margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;}}
.ht-hint{{font-size:11px;font-weight:400;color:var(--text3);margin-left:auto;}}
.hw{{display:flex;flex-direction:column;gap:10px;}}
.hc{{display:flex;align-items:center;gap:12px;padding:14px 16px;border-radius:14px;background:var(--card);border:2px solid var(--border2);cursor:pointer;transition:all .3s ease;position:relative;}}
.hc:hover{{border-color:rgba(139,92,246,0.4);background:rgba(139,92,246,0.06);transform:translateY(-1px);box-shadow:0 4px 12px rgba(139,92,246,0.1);}}
.hc.selected{{border-color:rgba(16,185,129,0.6);background:linear-gradient(135deg,rgba(16,185,129,0.08),rgba(52,211,153,0.04));box-shadow:0 0 0 1px rgba(16,185,129,0.2);}}
.hc-check{{width:24px;height:24px;border-radius:50%;border:2px solid var(--border2);display:flex;align-items:center;justify-content:center;font-size:12px;color:#10b981;flex-shrink:0;transition:all .2s;}}
.hc.selected .hc-check{{background:#10b981;border-color:#10b981;color:#fff;}}
.hc-info{{flex:1;min-width:0;}}
.hc-row1{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}}
.hc-row2{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;}}
.hn{{font-size:14px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-right:8px;}}
.hsg{{font-size:12px;color:#f59e0b;font-weight:600;flex-shrink:0;}}
.hpr{{font-size:13px;color:#10b981;font-weight:700;}}
.hpr.no-price{{color:var(--text3);font-weight:400;font-style:italic;}}
.hdi{{font-size:11px;color:var(--text3);padding:2px 8px;background:var(--tbg);border-radius:6px;}}
.htel{{font-size:11px;color:var(--text2);}}

/* 预算概览 */
.bs{{background:linear-gradient(135deg,rgba(16,185,129,0.06),rgba(16,185,129,0.02));border:1px solid rgba(16,185,129,0.12);}}
.bs h2{{font-size:18px;margin-bottom:14px;}}
.bg{{display:flex;flex-direction:column;gap:8px;}}
.bi{{display:flex;align-items:center;gap:8px;font-size:13px;}}
.bn{{width:50px;flex-shrink:0;color:var(--text2);}}
.bv{{width:70px;text-align:right;font-weight:600;color:var(--text);}}
.bp{{width:30px;text-align:right;font-size:11px;color:var(--text3);}}
.bb{{height:8px;border-radius:4px;background:linear-gradient(90deg,#10b981,#34d399);}}
.bt{{margin-top:10px;font-size:12px;color:var(--text2);text-align:center;}}

.tg{{background:var(--card);border:1px solid var(--border);}}
.tg h2{{font-size:20px;margin-bottom:12px;}}
.tg p{{font-size:14px;color:var(--text2);line-height:1.8;}}
.ft{{text-align:center;padding:40px 20px;font-size:12px;color:var(--text3);}}

/* 地图 Tab */
.map-tabs{{display:flex;gap:6px;padding:8px 24px 0;}}
.mt{{padding:5px 14px;border-radius:14px;border:1px solid var(--border2);background:var(--tbg);color:var(--text2);font-size:12px;cursor:pointer;transition:all .2s;}}
.mt.active{{background:var(--mday1);color:#fff;border-color:var(--mday1);}}
.mt:hover{{opacity:.8;}}

/* 图例 */
.legend{{display:flex;gap:20px;padding:8px 24px 16px;font-size:13px;color:var(--text2);}}
.legend-dot{{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:4px;vertical-align:middle;}}

@media print{{body{{background:#fff!important;color:#333!important;}}.cover{{height:100vh;}}.ds,.map-section,.sec{{break-inside:avoid;}}.tb{{display:none!important;}}}}
@media(max-width:600px){{.cover h1{{font-size:32px;}}.cr,.cr.r{{flex-direction:column;}}.cp{{width:100%;min-height:120px;}}}}
</style>
</head>
<body>

<button class="tb" onclick="tt()" title="切换主题">🌙</button>

<div class="cover">
    <h1>{city}·{trip_label}</h1>
    <div class="cs">美食与景点 · 深度体验指南</div>
    <div class="ci"><span>📅 {date_range_str}</span><span>🏠 {accommodation or '市中心'}</span><span>🍽️ 美食 · 🏛️ 景点</span>{f'<span>{cover_extra_html}</span>' if cover_extra_html else ''}</div>
</div>

{''.join(day_html_parts)}

{''.join(hotel_html_parts)}

{thtml}

{whtml}

{budget_html}

<!-- 交互式地图（按日切换） -->
<div class="map-section">
    <h2>🗺️ 行程地图</h2>
    <div class="map-tabs">
        <button class="mt" data-day="all" onclick="switchMapDay('all')">📍 全部</button>
        {''.join(f'<button class="mt{" active" if i==0 else ""}" data-day="{day["day"]}" onclick="switchMapDay({day["day"]})">Day {day["day"]}</button>' for i, day in enumerate(itinerary))}
        <button class="mt" data-day="hotel" onclick="switchMapDay('hotel')">🏨 住宿</button>
    </div>
    <div class="legend">
        <span><span class="legend-dot" style="background:#64b4ff"></span>景点</span>
        <span><span class="legend-dot" style="background:#ff6b35"></span>餐厅</span>
        <span><span class="legend-dot" style="background:#10b981"></span>住宿</span>
    </div>
    <div id="map"></div>
</div>

{fh_html}
{tg_html}

<div class="ft">Generated by Hermes AI · 高德地图数据支持 · {ts}</div>

<script>
function tt(){{
    var h=document.documentElement;
    var n=h.getAttribute('data-theme')==='dark'?'light':'dark';
    h.setAttribute('data-theme',n);
    document.querySelector('.tb').textContent=n==='dark'?'🌙':'☀️';
}}

// 地图 - 按日切换
var map = L.map('map',{{zoomControl:true,attributionControl:false}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18}}).addTo(map);

var allItems = {map_items_json};
var allHotels = {json.dumps(all_hotels_data, ensure_ascii=False)};
var markers = [];
var polylines = [];
var currentDay = 'all';
var dayColors = ['hsl(210,70%,50%)','hsl(240,70%,50%)','hsl(330,70%,50%)','hsl(30,70%,50%)','hsl(150,70%,50%)','hsl(270,70%,50%)','hsl(0,70%,50%)'];

// 每天被选中的酒店索引 (默认选第一家)
var selectedHotels = {{}};
allHotels.forEach(function(h){{
    if(selectedHotels[h.day] === undefined) selectedHotels[h.day] = 0;
}});

function getItemColor(item) {{
    if(item.type==='hotel') return '#10b981';
    if(item.type) return '#ff6b35';
    return dayColors[(item.day-1)%dayColors.length];
}}
function getItemLabel(item) {{
    if(item.type==='hotel') return '🏨';
    if(item.type) return '🍴';
    return item.day;
}}

function renderMap(day) {{
    markers.forEach(function(m){{map.removeLayer(m);}});
    polylines.forEach(function(p){{map.removeLayer(p);}});
    markers = [];
    polylines = [];
    var items;
    if(day === 'all') {{
        items = allItems.filter(function(i){{
            if(i.type==='hotel') return i.hIdx === selectedHotels[i.day];
            return true;
        }});
    }} else if(day === 'hotel') {{
        items = allItems.filter(function(i){{return i.type==='hotel' && i.hIdx === selectedHotels[i.day];}});
    }} else {{
        items = allItems.filter(function(i){{
            if(i.type==='hotel') return i.day === day && i.hIdx === selectedHotels[i.day];
            return i.day === day;
        }});
    }}
    var orderedCoords = [];
    items.forEach(function(item,i){{
        if(!item.loc||item.loc.length<2) return;
        var color = getItemColor(item);
        var label = getItemLabel(item);
        var icon = L.divIcon({{
            html:'<div style="width:30px;height:30px;border-radius:50%;background:'+color+';color:#fff;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;border:2px solid rgba(255,255,255,0.8);box-shadow:0 2px 10px rgba(0,0,0,0.35);">'+label+'</div>',
            className:'',iconSize:[30,30],iconAnchor:[15,15]
        }});
        var m = L.marker([item.loc[1],item.loc[0]],{{icon:icon}}).addTo(map);
        var ptype = item.type==='hotel'?'<br>🏨 推荐住宿':(item.type?'<br>🍴 推荐餐厅':'');
        m.bindPopup('<b>'+item.name+'</b>'+(item.time?'<br>🕐 '+item.time:'')+ptype);
        markers.push(m);
        orderedCoords.push([item.loc[1],item.loc[0]]);
    }});
    // 画路线连线
    if(orderedCoords.length>=2 && day !== 'hotel') {{
        var lineColor = typeof day === 'number' ? dayColors[(day-1)%dayColors.length] : '#a78bfa';
        var pl = L.polyline(orderedCoords, {{color:lineColor,weight:3,opacity:0.5,dashArray:'8,6'}}).addTo(map);
        polylines.push(pl);
    }}
    var coords = items.filter(function(i){{return i.loc&&i.loc.length>=2;}}).map(function(i){{return [i.loc[1],i.loc[0]];}});
    if(coords.length>=2) map.fitBounds(L.latLngBounds(coords),{{padding:[30,30]}});
    else if(coords.length===1) map.setView(coords[0],13);
}}

function switchMapDay(day) {{
    currentDay = day;
    document.querySelectorAll('.mt').forEach(function(b){{b.classList.remove('active');}});
    var btn = document.querySelector('.mt[data-day="'+day+'"]');
    if(btn) btn.classList.add('active');
    renderMap(day);
}}

function selectHotel(day, idx) {{
    selectedHotels[day] = idx;
    // 更新酒店卡片 UI
    document.querySelectorAll('.hc[data-day="'+day+'"]').forEach(function(card){{
        var ci = parseInt(card.getAttribute('data-idx'));
        if(ci === idx) {{
            card.classList.add('selected');
            card.querySelector('.hc-check').textContent = '✓';
        }} else {{
            card.classList.remove('selected');
            card.querySelector('.hc-check').textContent = '';
        }}
    }});
    renderMap(currentDay);
}}

renderMap(1);
</script>
</body>
</html>"""


def generate(city="上海", itinerary=None, food_highlights=None, overall_note="",
             transport="", accommodation="", budget="", preference="", tips=None, weather=None, start_city="", people_count=2):
    if not itinerary:
        print("⚠️ 无行程数据")
        return None
    html = generate_brochure(itinerary, city, food_highlights, overall_note,
                            transport, accommodation, budget, preference, tips, weather, start_city, people_count)
    outputs_dir = os.path.join(BASE, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    import re
    safe_city = re.sub(r'[^\w\u4e00-\u9fa5\-\.]', '_', city)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(outputs_dir, f"{safe_city}_brochure_{ts}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 旅游手册(含地图)已生成: {path}")
    return path
