"""
旅游手册生成器 — 图文并茂 + 交互地图
========================================
一本包含: 封面 → 每日行程(图片卡片) → 交互式Leaflet地图 → 必吃推荐 → 交通指南
"""
import os, json, time, urllib.request, re, datetime, logging, threading
from utils.config import AMAP_KEY, BASE_DIR

logger = logging.getLogger("travel_pipeline")
_photo_cache = {}
_last_fetch_time = 0
_fetch_lock = threading.Lock()


def _get_single_city(name, overall_city):
    if not overall_city:
        return "上海"
    cities = [c.strip() for c in overall_city.replace("，", ",").split(",") if c.strip()]
    if len(cities) <= 1:
        return overall_city
    for c in cities:
        if c in name:
            return c
    if any(k in name for k in ["大三巴", "威尼斯人", "葡", "马介休", "玛嘉烈", "安东尼奥", "蛋挞"]):
        return "澳门"
    if any(k in name for k in ["清晖", "逢简", "顺德", "双皮奶", "大良", "猪肉婆"]):
        return "佛山"
    if any(k in name for k in ["渔女", "情侣", "日月贝", "新海利", "金悦轩", "横琴"]):
        return "珠海"
    if any(k in name for k in ["广州塔", "陈家祠", "炳胜", "点都德", "沙面", "陶陶居"]):
        return "广州"
    return cities[0]


def _fetch_photos(name, city="上海", category=""):
    """线程安全获取 POI 照片：双层降级 + HTTPS 强制 + 全局并发限流"""
    global _last_fetch_time
    with _fetch_lock:
        if name in _photo_cache:
            return _photo_cache[name]

    urls = []
    cleaned = re.sub(r'[\uff08(].*?[\uff09)]', '', name).strip()
    single_city = _get_single_city(cleaned, city)
    if single_city == "顺德":
        single_city = "佛山"
    from utils.image_fetcher import _get_search_query
    search_name = _get_search_query(name, single_city, category)
    fallback_name = f"{single_city}{cleaned}" if single_city and single_city not in cleaned else cleaned

    # 全局线程安全限流
    with _fetch_lock:
        elapsed = time.time() - _last_fetch_time
        if elapsed < 0.2:
            time.sleep(0.2 - elapsed)
        _last_fetch_time = time.time()

    # 1. Gaode 图片搜索
    try:
        from utils.image_fetcher import _gaode
        urls = _gaode(search_name, single_city)
        if not urls and search_name != fallback_name:
            time.sleep(0.1)
            urls = _gaode(fallback_name, single_city)
    except Exception:
        pass

    # 2. Web 搜索引擎降级（360 → 百度 → Bing，带额外并发控制）
    if not urls:
        try:
            from utils.image_fetcher import _so, _baidu, _bing
            with _fetch_lock:
                time.sleep(0.15)
            urls = _so(search_name) or _baidu(search_name) or _bing(search_name)
            if not urls and search_name != fallback_name:
                with _fetch_lock:
                    time.sleep(0.2)
                urls = _so(fallback_name) or _baidu(fallback_name) or _bing(fallback_name)
        except Exception:
            pass

    # 统一转 HTTPS（仅非高德来源，高德 store.is.autonavi.com 不支持 HTTPS）
    safe_urls = []
    for u in urls:
        if u.startswith("http://") and "is.autonavi.com" not in u and "store.is" not in u:
            u = "https://" + u[7:]
        safe_urls.append(u)

    with _fetch_lock:
        _photo_cache[name] = safe_urls
    return safe_urls
def _fetch_photos_batch(poi_items, default_city="上海", max_workers=4):
    """批量并行获取POI照片"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for item in poi_items:
            if isinstance(item, tuple) and len(item) >= 3:
                name, single_city, category = item[:3]
            elif isinstance(item, tuple):
                name, single_city = item[:2]
                category = ""
            else:
                name, single_city = item, default_city
                category = ""
            if not single_city:
                single_city = default_city
            futures[ex.submit(_fetch_photos, name, single_city, category)] = name
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
    elapsed = time.time() - _last_fetch_time
    if elapsed < 0.2:
        time.sleep(0.2 - elapsed)
    try:
        loc = f"{location[0]},{location[1]}" if isinstance(location, (list,tuple)) else location
        url = f"https://restapi.amap.com/v5/place/around?key={AMAP_KEY}&location={loc}&radius={radius}&types=100000&sortrule=weight&page_size=10&show_fields=business,rating,cost,tel"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        _last_fetch_time = time.time()
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
    except Exception:
        _last_fetch_time = time.time()
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
    date_range_str = ""
    if weather and weather.get("forecast"):
        forecasts = weather["forecast"]
        try:
            d1 = datetime.datetime.strptime(forecasts[0]["date"], "%Y-%m-%d")
            d2 = datetime.datetime.strptime(forecasts[-1]["date"], "%Y-%m-%d")
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
    all_hotels_data = []

    # 预批量获取所有照片
    all_poi_items = []
    for day in itinerary:
        for poi in day.get("pois", []):
            all_poi_items.append((poi["name"], poi.get("city", ""), "sight"))
        for food in day.get("foods", []):
            all_poi_items.append((food["name"], food.get("city", ""), "food"))
    photo_cache = _fetch_photos_batch(all_poi_items, city) if all_poi_items else {}

    # 预批量搜索酒店
    from concurrent.futures import ThreadPoolExecutor
    from utils.amap_api import AMapClient
    amap = AMapClient()
    hotel_locations = []
    dest_cities = [c.strip() for c in city.replace("，", ",").split(",") if c.strip()]

    for day in itinerary:
        stay_city = day.get("accommodation_city", "").strip()
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
        for poi in day.get("pois", []):
            photos = photo_cache.get(poi["name"], [])
            slots.append({"type":"sight","data":poi,"photos":photos})
        for food in day.get("foods", []):
            photos = photo_cache.get(food["name"], [])
            slots.append({"type":"food","data":food,"photos":photos})

        hotels = hotel_cache.get(day["day"], [])
        if hotels:
            day_num = day["day"]
            hc = ""
            for hi, h in enumerate(hotels[:3]):
                # 检查并设置 _main_pic 字段
                main_pic = h.get("_main_pic") or h.get("main_pic") or ""
                if not main_pic:
                    try:
                        from utils.image_fetcher import get_photos
                        fallback_photos = get_photos(h["name"], day.get("accommodation_city", city), category="")
                        if fallback_photos:
                            main_pic = fallback_photos[0]
                    except Exception:
                        pass
                h["_main_pic"] = main_pic

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
                
                # 酒店主图
                pic_html = f'<img class="hpic" src="{main_pic}" alt="" onerror="this.style.display=\'none\'">' if main_pic else ""
                
                hc += (
                    f'<div class="hc {selected_class}" data-day="{day_num}" data-idx="{hi}" onclick="selectHotel({day_num},{hi})">'
                    f'<div class="hc-check">{"✓" if hi == 0 else ""}</div>'
                    f'{pic_html}'
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
                dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
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

    map_items_json = json.dumps(all_items_flat, ensure_ascii=False)

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

    budget_html = ""
    if budget:
        days_n = len(itinerary) if itinerary else 2
        daily = 1500
        nums = re.findall(r'\d+', budget.replace(',', ''))
        if nums:
            budget_vals = [int(n) for n in nums if int(n) >= 100]
            if budget_vals:
                val = max(budget_vals)
                is_daily = any(x in budget for x in ['天', '日', 'daily', '每天', '每日'])
                is_per_person = any(x in budget for x in ['人均', '每人', '每人每天', '人均每天', '单人', '/人'])
                specified_people = people_count
                match_people = re.search(r'(\d+|两|三|四|五|六)人', budget)
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
                        daily = val // max(days_n, 1)
                    else:
                        daily = val // (max(specified_people, 1) * max(days_n, 1))
        daily = max(daily, 1)
        total_budget = daily * days_n * people_count
        accommodation_est = int(daily * 0.25)
        food_est = int(daily * 0.18)
        transport_est = int(daily * 0.12)
        ticket_est = int(daily * 0.25)
        shopping_est = daily - accommodation_est - food_est - transport_est - ticket_est
        budget_html = f"""
    <div class="sec bs">
        <h2>💰 预算概览（{days_n}天 · {people_count}人 · 约¥{daily}/天/人）</h2>
        <div class="bg">
            <div class="bi"><div class="bn">🏨 住宿</div><div class="bv">¥{accommodation_est*days_n*people_count}</div><div class="bp">{(accommodation_est/daily*100):.0f}%</div><div class="bb" style="width:{(accommodation_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🎫 门票</div><div class="bv">¥{ticket_est*days_n*people_count}</div><div class="bp">{(ticket_est/daily*100):.0f}%</div><div class="bb" style="width:{(ticket_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🍽️ 餐饮</div><div class="bv">¥{food_est*days_n*people_count}</div><div class="bp">{(food_est/daily*100):.0f}%</div><div class="bb" style="width:{(food_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🚗 交通</div><div class="bv">¥{transport_est*days_n*people_count}</div><div class="bp">{(transport_est/daily*100):.0f}%</div><div class="bb" style="width:{(transport_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🛍️ 其他</div><div class="bv">¥{shopping_est*days_n*people_count}</div><div class="bp">{(shopping_est/daily*100):.0f}%</div><div class="bb" style="width:{(shopping_est/daily*100):.0f}%"></div></div>
        </div>
        <div class="bt">预算合计 ≈ ¥{total_budget}（{transport or '出行方式'} · {people_count}人）</div>
    </div>"""

    fh_html = ""
    if food_highlights:
        chips = "".join(f'<div class="fc">{h}</div>' for h in food_highlights[:6])
        fh_html = f'<div class="sec fh"><h2>🏆 必吃推荐</h2><div class="fg">{chips}</div></div>'

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

    # ─── 一键预订总览 ───────────────────────────
    _bk = flyai_prices or {}
    _booking_items = []
    
    # 打印调试日志确认传入的 flyai_prices 结构与内容
    print(f"[DEBUG] utils/brochure/__init__.py: flyai_prices available = {_bk.get('available')}")
    print(f"[DEBUG] utils/brochure/__init__.py: flight keys = {list(_bk.get('flight', {}).keys()) if _bk.get('flight') else 'None'}")
    print(f"[DEBUG] utils/brochure/__init__.py: train keys = {list(_bk.get('train', {}).keys()) if _bk.get('train') else 'None'}")
    print(f"[DEBUG] utils/brochure/__init__.py: hotel keys = {list(_bk.get('hotel', {}).keys()) if _bk.get('hotel') else 'None'}")
    print(f"[DEBUG] utils/brochure/__init__.py: ticket count = {len(_bk.get('tickets', {})) if _bk.get('tickets') else 0}")
    
    has_bk_data = _bk.get("available") or any(k in _bk for k in ("flight", "train", "hotel", "tickets"))
    if has_bk_data:
        # 机票
        _fd = _bk.get("flight", {})
        if _fd.get("items"):
            _bf = _fd["items"][0]; _pf = _bf["price"]; _jf = _bf.get("jump_url","")
            _sf = _fd.get("source","live"); _lf = "飞猪实时 🟢" if _sf=="live" else "缓存价 🟡"
            _segs = _bf.get("segments") or _bf.get("journeys") or []
            _fdet = ""
            if _segs:
                _s = _segs[0]
                _dt = _s.get("dep_time") or _s.get("depDateTime") or ""
                _dt = _dt[11:16] if len(_dt) > 15 else _dt
                _at = _s.get("arr_time") or _s.get("arrDateTime") or ""
                _at = _at[11:16] if len(_at) > 15 else _at
                _flight_no = _s.get("flight_no") or _s.get("marketingTransportNo") or ""
                _airline = _s.get("airline") or _s.get("marketingTransportName") or ""
                _dep_airport = _s.get("dep_airport") or _s.get("depStationName") or ""
                _arr_airport = _s.get("arr_airport") or _s.get("arrStationName") or ""
                _dep_terminal = _s.get("dep_terminal") or _s.get("depTerm") or ""
                _arr_terminal = _s.get("arr_terminal") or _s.get("arrTerm") or ""
                _fdet = f'<div class="bi-detail">{_flight_no} {_airline} · {_dep_airport}{" T"+str(_dep_terminal) if _dep_terminal else ""} {_dt} → {_arr_airport}{" T"+str(_arr_terminal) if _arr_terminal else ""} {_at}</div>'
            _bbtn = f'<a class="btn-booking" href="{_jf}" target="_blank" rel="noopener">✈️ 预订 ¥{_pf:.0f}</a>' if _jf else f'<span class="booking-no-link">✈️ ¥{_pf:.0f}</span>'
            _booking_items.append(f'<div class="bi-row"><div class="bi-icon">✈️</div><div class="bi-info"><div class="bi-name">机票 · {start_city or ""} → {city}</div>{_fdet}<div class="bi-meta">{_lf} · {_fd.get("count",0)} 个选项</div></div><div class="bi-action">{_bbtn}</div></div>')
        # 高铁
        _td = _bk.get("train", {})
        if _td.get("items"):
            _bt = _td["items"][0]; _pt = _bt["price"]; _jt = _bt.get("jump_url","")
            _st = _td.get("source","live"); _lt = "飞猪实时 🟢" if _st=="live" else "缓存价 🟡"
            _segs = _bt.get("segments") or _bt.get("journeys") or []
            _tdet = ""
            if _segs:
                _s = _segs[0]
                _dt = _s.get("dep_time") or _s.get("depDateTime") or ""
                _dt = _dt[11:16] if len(_dt) > 15 else _dt
                _at = _s.get("arr_time") or _s.get("arrDateTime") or ""
                _at = _at[11:16] if len(_at) > 15 else _at
                _train_no = _s.get("train_no") or _s.get("marketingTransportNo") or ""
                _seat_class = _s.get("seat_class") or _s.get("seatClassName") or ""
                _dep_station = _s.get("dep_station") or _s.get("depStationName") or ""
                _arr_station = _s.get("arr_station") or _s.get("arrStationName") or ""
                _duration_min = _s.get("duration_min") or _s.get("duration") or ""
                _tdet = f'<div class="bi-detail">{_train_no} {_seat_class} · {_dep_station} {_dt} → {_arr_station} {_at} ({_duration_min}min)</div>'
            _tbtn = f'<a class="btn-booking" href="{_jt}" target="_blank" rel="noopener">🚄 预订 ¥{_pt:.0f}</a>' if _jt else f'<span class="booking-no-link">🚄 ¥{_pt:.0f}</span>'
            _booking_items.append(f'<div class="bi-row"><div class="bi-icon">🚄</div><div class="bi-info"><div class="bi-name">高铁 · {start_city or ""} → {city}</div>{_tdet}<div class="bi-meta">{_lt} · {_td.get("count",0)} 个选项</div></div><div class="bi-action">{_tbtn}</div></div>')
        # 酒店
        _hd = _bk.get("hotel", {})
        if _hd.get("items"):
            _bh = _hd["items"][0]
            _hbtn = f'<a class="btn-booking" href="{_bh.get("jump_url","")}" target="_blank" rel="noopener" style="background:linear-gradient(135deg,#f97316,#ea580c)">🏨 预订</a>' if _bh.get("jump_url") else ""
            _booking_items.append(f'<div class="bi-row"><div class="bi-icon">🏨</div><div class="bi-info"><div class="bi-name">{_bh["name"]}</div><div class="bi-meta">¥{_bh["price"]:.0f}/晚 · 飞猪</div></div><div class="bi-action">{_hbtn}</div></div>')
        # 门票
        _tks = _bk.get("tickets", {})
        if _tks:
            for _day in (itinerary or []):
                for _poi in _day.get("pois", []):
                    _n = _poi["name"]; _tdi = _tks.get(_n, {})
                    if _tdi and _tdi.get("source") != "fail":
                        _pm = _tdi.get("price_min")
                        if _pm:
                            _bu = _tdi.get("booking_url","")
                            _tkbtn = f'<a class="btn-booking" href="{_bu}" target="_blank" rel="noopener" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">🎫 预订 ¥{_pm}</a>' if _bu else f'<span class="booking-no-link">🎫 ¥{_pm}</span>'
                            _booking_items.append(f'<div class="bi-row"><div class="bi-icon">🎫</div><div class="bi-info"><div class="bi-name">{_n}</div><div class="bi-meta">¥{_tdi.get("price_max", _pm) if _tdi.get("price_max") != _pm else _pm}/人</div></div><div class="bi-action">{_tkbtn}</div></div>')
    
    print(f"[DEBUG] utils/brochure/__init__.py: Generated {len(_booking_items)} booking items: {_booking_items}")
    
    booking_html = ""
    if _booking_items:
        _navail = sum(1 for b in _booking_items if "btn-booking" in b)
        booking_html = f"""
    <div class="sec booking-section">
        <h2>📋 一键预订总览</h2>
        <div class="booking-intro">共 {len(_booking_items)} 项 · {_navail} 项可在线预订</div>
        <div class="booking-list">{''.join(_booking_items[:15])}</div>
        <div class="booking-footer">点击「预订」跳转飞猪/携程完成下单</div>
    </div>"""

    ts = time.strftime("%Y-%m-%d")

    cover_extra = []
    if start_city: cover_extra.append(f'📍 起点：{start_city}')
    if transport: cover_extra.append(f'🚗 {transport}')
    if budget: cover_extra.append(f'💰 {budget}')
    if preference: cover_extra.append(f'🎯 {preference}')
    cover_extra_html = ' · '.join(cover_extra)

    day_map_labels = [{"day": day["day"]} for day in itinerary]

    from utils.brochure.renderer import render_brochure
    html = render_brochure(
        city=city,
        trip_label=trip_label,
        date_range_str=date_range_str,
        accommodation=accommodation or '市中心',
        cover_extra_html=cover_extra_html,
        day_html=''.join(day_html_parts),
        hotel_html=''.join(hotel_html_parts),
        tips_html=thtml,
        weather_html=whtml,
        budget_html=budget_html,
        booking_html=booking_html,
        food_highlights_html=fh_html,
        transport_html=tg_html,
        day_map_labels=day_map_labels,
        map_items_json=map_items_json,
        all_hotels_json=json.dumps(all_hotels_data, ensure_ascii=False),
        generated_ts=ts,
    )
    return html


def generate(city="上海", itinerary=None, food_highlights=None, overall_note="",
             transport="", accommodation="", budget="", preference="", tips=None, weather=None, start_city="", people_count=2):
    if not itinerary:
        print("⚠️ 无行程数据")
        return None
    html = generate_brochure(itinerary, city, food_highlights, overall_note,
                            transport, accommodation, budget, preference, tips, weather, start_city, people_count)
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    safe_city = re.sub(r'[^\w\u4e00-\u9fa5\-\.]', '_', city)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(outputs_dir, f"{safe_city}_brochure_{ts}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 旅游手册(含地图)已生成: {path}")
    return path
