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

def _fetch_photos(name, city="上海"):
    """高德API获取POI照片，带重试和限流"""
    global _last_fetch_time
    if name in _photo_cache:
        return _photo_cache[name]
    urls = []
    # 限流：每次请求间隔至少 0.5s
    import time as _t
    elapsed = _t.time() - _last_fetch_time
    if elapsed < 0.5:
        _t.sleep(0.5 - elapsed)
    # 高德API（最多重试2次）
    for attempt in range(2):
        try:
            kw = urllib.request.quote(name)
            ct = urllib.request.quote(city)
            url = f"https://restapi.amap.com/v5/place/text?key={AMAP_KEY}&keywords={kw}&region={ct}&city_limit=true&page_size=1&show_fields=photos"
            req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            if data.get("status")=="1" and data.get("pois"):
                photos = data["pois"][0].get("photos", [])
                if photos:
                    urls = [p["url"] for p in photos[:2]]
                    break
        except:
            if attempt == 0:
                _t.sleep(1)  # 重试前等1秒
            continue
    _last_fetch_time = _t.time()
    _photo_cache[name] = urls
    return urls


def _search_hotels(location, city="上海", radius=1500):
    """高德搜索附近酒店(types=100000)，带限流"""
    global _last_fetch_time
    import time as _t
    elapsed = _t.time() - _last_fetch_time
    if elapsed < 0.5:
        _t.sleep(0.5 - elapsed)
    try:
        loc = f"{location[0]},{location[1]}" if isinstance(location, (list,tuple)) else location
        kw = urllib.request.quote(city)
        url = f"https://restapi.amap.com/v5/place/around?key={AMAP_KEY}&location={loc}&radius={radius}&types=100000&sortrule=weight&page_size=5&show_fields=business,rating,cost,tel"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        _last_fetch_time = _t.time()
        results = []
        for p in data.get("pois", []):
            biz = p.get("business", {})
            results.append({
                "name": p["name"],
                "location": p.get("location", ""),
                "address": p.get("address", ""),
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
                       transport="", accommodation="", budget="", preference="", tips=None):
    """生成「图文手册+交互地图」单文件HTML，含交通/住宿/预算等"""
    day_html_parts = []
    all_items_flat = []
    hotel_html_parts = []
    total_km = 0

    for di, day in enumerate(itinerary):
        slots = []
        day_locations = []
        for poi in day.get("pois", []):
            photos = _fetch_photos(poi["name"], city)
            slots.append({"type":"sight","data":poi,"photos":photos})
            if poi.get("location"): day_locations.append(poi["location"])
        for food in day.get("foods", []):
            photos = _fetch_photos(food["name"], city)
            slots.append({"type":"food","data":food,"photos":photos})

        # 每天搜酒店
        hotels = []
        if day_locations:
            clng = sum(l[0] for l in day_locations) / len(day_locations)
            clat = sum(l[1] for l in day_locations) / len(day_locations)
            hotels = _search_hotels([clng, clat], city)
        if hotels:
            hc = "".join(f'<div class="hc"><div class="hn">{h["name"]}</div><div class="hm">⭐{h.get("rating","?")} | 💰约{h.get("cost","?")}/晚 | {h.get("distance","?")}m</div></div>' for h in hotels[:3])
            hotel_html_parts.append(f'<div class="hs"><div class="ht">Day {day["day"]} 推荐住宿</div><div class="hw">{hc}</div></div>')

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
            if d.get("transit"): tags.append(f'<span class="t tr">🚗 {d["transit"]}</span>')

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

        day_html_parts.append(f"""
        <div class="ds">
            <div class="dh" style="background:linear-gradient(135deg,hsl({210+di*30},70%,50%),hsl({210+di*30},70%,30%));">
                <div class="dn">Day {day['day']}</div>
                <div class="dt">{day.get('label','')}</div>
                <div class="dd">7月{4+day['day']}日</div>
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

    # 预算估算
    import re as _re
    budget_html = ""
    if budget:
        days = len(itinerary) if itinerary else 2
        # 从budget字符串中提取数字，智能判断是日均还是总预算
        daily = 3000
        nums = _re.findall(r'\d+', budget.replace(',', ''))
        if nums:
            daily = int(nums[0])
            # 如果budget包含"总预算""一共""总共"等词，视为总预算 ÷ 天数
            if _re.search(r'总[预算共]|一[共]|总共', budget):
                daily = daily // max(days, 1)
            # 如果日均超过10000，很可能也是总预算
            if daily > 10000:
                daily = daily // max(days, 1)
        total_budget = daily * days
        accommodation_est = int(daily * 0.25)
        food_est = int(daily * 0.18)
        transport_est = int(daily * 0.12)
        ticket_est = int(daily * 0.25)
        shopping_est = daily - accommodation_est - food_est - transport_est - ticket_est
        budget_html = f"""
    <div class="sec bs">
        <h2>💰 预算概览（{days}天 · 2人 · 约¥{daily}/天）</h2>
        <div class="bg">
            <div class="bi"><div class="bn">🏨 住宿</div><div class="bv">¥{accommodation_est*days}</div><div class="bp">{(accommodation_est/daily*100):.0f}%</div><div class="bb" style="width:{(accommodation_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🎫 门票</div><div class="bv">¥{ticket_est*days}</div><div class="bp">{(ticket_est/daily*100):.0f}%</div><div class="bb" style="width:{(ticket_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🍽️ 餐饮</div><div class="bv">¥{food_est*days}</div><div class="bp">{(food_est/daily*100):.0f}%</div><div class="bb" style="width:{(food_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🚗 交通</div><div class="bv">¥{transport_est*days}</div><div class="bp">{(transport_est/daily*100):.0f}%</div><div class="bb" style="width:{(transport_est/daily*100):.0f}%"></div></div>
            <div class="bi"><div class="bn">🛍️ 其他</div><div class="bv">¥{shopping_est*days}</div><div class="bp">{(shopping_est/daily*100):.0f}%</div><div class="bb" style="width:{(shopping_est/daily*100):.0f}%"></div></div>
        </div>
        <div class="bt">预算合计 ≈ ¥{total_budget}（{transport or '出行方式'} · 2人）</div>
    </div>"""

    fh_html = ""
    if food_highlights:
        chips = "".join(f'<div class="fc">{h}</div>' for h in food_highlights[:6])
        fh_html = f'<div class="sec fh"><h2>🏆 必吃推荐</h2><div class="fg">{chips}</div></div>'

    # 交通指南
    tg_parts = []
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
    if transport: cover_extra.append(f'🚗 {transport}')
    if budget: cover_extra.append(f'💰 {budget}')
    if preference: cover_extra.append(f'🎯 {preference}')
    cover_extra_html = ' · '.join(cover_extra)

    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{city}旅行手册 | 周末两日游</title>
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

/* 酒店推荐 */
.hs{{margin:12px;padding:16px;border-radius:16px;background:linear-gradient(135deg,rgba(139,92,246,0.04),rgba(99,102,241,0.02));border:1px solid rgba(139,92,246,0.12);}}
.ht{{font-size:15px;font-weight:600;margin-bottom:10px;color:var(--text);display:flex;align-items:center;gap:6px;}}
.hw{{display:flex;flex-direction:column;gap:6px;}}
.hc{{padding:8px 12px;border-radius:10px;background:var(--tbg);border:1px solid var(--border);display:flex;align-items:center;gap:10px;transition:all .2s;}}
.hc:hover{{border-color:rgba(139,92,246,0.3);background:rgba(139,92,246,0.04);}}
.hn{{font-size:13px;font-weight:500;color:var(--text);flex:1;}}
.hm{{font-size:11px;color:var(--text2);white-space:nowrap;}}

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
    <h1>{city}·周末两日游</h1>
    <div class="cs">美食与景点 · 深度体验指南</div>
    <div class="ci"><span>📅 7月5日—7月6日</span><span>🏠 {accommodation or '市中心'}</span><span>🍽️ 美食 · 🏛️ 景点</span>{f'<span>{cover_extra_html}</span>' if cover_extra_html else ''}</div>
</div>

{''.join(day_html_parts)}

{''.join(hotel_html_parts)}

{thtml}

{budget_html}

<!-- 交互式地图（按日切换） -->
<div class="map-section">
    <h2>🗺️ 行程地图</h2>
    <div class="map-tabs">
        <button class="mt" data-day="all" onclick="switchMapDay('all')">📍 全部</button>
        <button class="mt active" data-day="1" onclick="switchMapDay(1)">Day 1</button>
        <button class="mt" data-day="2" onclick="switchMapDay(2)">Day 2</button>
    </div>
    <div class="legend">
        <span><span class="legend-dot" style="background:#64b4ff"></span>景点</span>
        <span><span class="legend-dot" style="background:#ff6b35"></span>餐厅</span>
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
var markers = [];
var currentDay = 'all';
var dayColors = ['hsl(210,70%,50%)','hsl(240,70%,50%)','hsl(330,70%,50%)'];

function renderMap(day) {{
    markers.forEach(function(m){{map.removeLayer(m);}});
    markers = [];
    var items = day === 'all' ? allItems : allItems.filter(function(i){{return i.day === day;}});
    items.forEach(function(item,i){{
        if(!item.loc||item.loc.length<2) return;
        var color = item.type ? '#ff6b35' : dayColors[(item.day-1)%dayColors.length];
        var label = item.type ? '🍴' : (item.day);
        var icon = L.divIcon({{
            html:'<div style="width:28px;height:28px;border-radius:50%;background:'+color+';color:#fff;font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center;border:2px solid rgba(255,255,255,0.7);box-shadow:0 2px 8px rgba(0,0,0,0.3);">'+label+'</div>',
            className:'',iconSize:[28,28],iconAnchor:[14,14]
        }});
        var m = L.marker([item.loc[1],item.loc[0]],{{icon:icon}}).addTo(map);
        m.bindPopup('<b>'+item.name+'</b>'+(item.time?'<br>🕐 '+item.time:'')+(item.type?'<br>🍴 推荐餐厅':''));
        markers.push(m);
    }});
    var coords = items.filter(function(i){{return i.loc&&i.loc.length>=2;}}).map(function(i){{return [i.loc[1],i.loc[0]];}});
    if(coords.length>=2) map.fitBounds(L.latLngBounds(coords),{{padding:[30,30]}});
    else if(coords.length===1) map.setView(coords[0],12);
}}

function switchMapDay(day) {{
    currentDay = day;
    document.querySelectorAll('.mt').forEach(function(b){{b.classList.remove('active');}});
    var btn = document.querySelector('.mt[data-day="'+day+'"]');
    if(btn) btn.classList.add('active');
    renderMap(day);
}}

renderMap(1);
</script>
</body>
</html>"""


def generate(city="上海", itinerary=None, food_highlights=None, overall_note="",
             transport="", accommodation="", budget="", preference="", tips=None):
    if not itinerary:
        print("⚠️ 无行程数据")
        return None
    html = generate_brochure(itinerary, city, food_highlights, overall_note,
                            transport, accommodation, budget, preference, tips)
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
