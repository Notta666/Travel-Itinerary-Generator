"""
旅游路线对抗性辩论规划
=======================
三步调用 DeepSeek API:
  Step 6.1: Bull — 密集打卡派路线
  Step 6.2: Bear — 悠闲体验派路线
  Step 6.3: Fusion — 综合生成最终行程

复用 Stock Investment pipeline_funcs.py 的 DeepSeek 调用模式。
"""

import os, json, urllib.request, time

def _load_api_key():
    """从环境变量或项目根目录的 .env 文件加载 DeepSeek API Key"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip("\"'")
                        if val and val != "***":
                            return val
        except Exception:
            pass
    return ""


def _call_deepseek(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 4000) -> dict:
    """调用 DeepSeek API，返回解析后的 JSON"""
    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError("DeepSeek API Key 未配置（需在 .env 设置 DEEPSEEK_API_KEY）")

    req_body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"}
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=req_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    content = result["choices"][0]["message"]["content"]
    return json.loads(content)


def plan_adversarial(poi_list, days, city, distance_matrix=None):
    """
    对抗性辩论路线规划

    输入:
      poi_list: [{name, location:[lng,lat], address, rating, cost, tag, district}]
      days: 行程天数
      city: 城市名
      distance_matrix: {matrix: [[{distance,duration}]], labels: [names]}

    返回:
      [{day, label, pois: [{name, location, address, rating, cost, ...}]}]
    """
    # 构造输入数据
    poi_summary = []
    for i, p in enumerate(poi_list):
        poi_summary.append({
            "id": i + 1,
            "name": p["name"],
            "location": p["location"],
            "address": p.get("address", ""),
            "district": p.get("district", ""),
            "rating": p.get("rating", ""),
            "cost": p.get("cost", ""),
            "tag": p.get("tag", ""),
        })

    data_json = json.dumps({
        "city": city,
        "days": days,
        "pois": poi_summary,
        "distance_matrix": distance_matrix,
    }, ensure_ascii=False, indent=2)

    # ── Step 6.1: Bull Prompt（密集打卡派） ──
    bull_prompt = f"""你是旅行规划中的「密集打卡派」分析师。你的任务是最大化行程效率，在有限天数内覆盖最多的精品地点。

【核心原则】
- 按区域分组：把同区域/同方向的POI放同一天，减少跨区交通
- 参考距离矩阵：优先安排相邻POI在同一天
- 每个POI建议停留时长，标注建议到访时段（上午/下午/傍晚/夜景）
- 考虑营业时间（餐厅优先午餐/晚餐时段）
- 早餐/晚餐就近解决

【数据】
{data_json}

输出纯JSON格式，严格按以下结构：
{{
  "bull_plan": [
    {{
      "day": 1,
      "label": "区域名/主题",
      "pois": [
        {{
          "poi_id": 1,
          "time_slot": "上午",
          "suggested_duration_min": 90,
          "note": "建议早去避开人流"
        }}
      ],
      "lunch_suggestion": "就近推荐",
      "dinner_suggestion": "就近推荐"
    }}
  ],
  "reasoning": "整体规划思路说明"
}}"""

    # ── Step 6.2: Bear Prompt（悠闲体验派） ──
    bear_prompt = f"""你是旅行规划中的「悠闲体验派」分析师。你的任务是避免行程过赶，注重体验质量和休息节奏。

【核心原则】
- 每天不超过3-4个点，留足闲逛和休息时间
- 同一片区深度游优于跨区走马观花
- 标注哪些POI可以合并（如在同一个景区内）
- 识别步行距离过远的组合 → 建议打车/地铁
- 提醒天气敏感点（露天景点避开正午、夜景景点傍晚出发）
- 预留用餐时间至少1小时

【数据】
{data_json}

输出纯JSON格式，严格按以下结构：
{{
  "bear_plan": [
    {{
      "day": 1,
      "label": "区域名/主题",
      "pois": [
        {{
          "poi_id": 1,
          "time_slot": "09:00-11:00",
          "suggested_duration_min": 120,
          "note": "悠闲游览，附近有咖啡厅可休息",
          "warning": "正午暴晒建议带伞"
        }}
      ],
      "pace": "轻松/适中/紧凑",
      "transit_note": "建议打车约15分钟"
    }}
  ],
  "risk_warnings": ["风险1", "风险2"],
  "reasoning": "整体规划思路说明"
}}"""

    # ── 执行前两步 ──
    print("  [Step 6.1] Bull 密集打卡派分析中...")
    bull_raw = _call_deepseek(
        "你是旅行路线规划师，擅长密集高效路线。返回纯JSON。",
        bull_prompt, temperature=0.3, max_tokens=4000
    )
    print(f"    完成: {len(bull_raw.get('bull_plan', []))} 天规划")

    print("  [Step 6.2] Bear 悠闲体验派分析中...")
    bear_raw = _call_deepseek(
        "你是旅行路线规划师，注重节奏和体验。返回纯JSON。",
        bear_prompt, temperature=0.3, max_tokens=4000
    )
    print(f"    完成: {len(bear_raw.get('bear_plan', []))} 天规划")

    bull_plan = bull_raw if isinstance(bull_raw, dict) else {}
    bear_plan = bear_raw if isinstance(bear_raw, dict) else {}

    # ── Step 6.3: Fusion Prompt（综合裁决） ──
    fusion_prompt = f"""你是首席旅行规划师。以下是你两位分析师对{city}{days}日游的规划方案，请综合双方意见，做出最终行程。

【密集打卡派方案】
{json.dumps(bull_plan, ensure_ascii=False, indent=2)}

【悠闲体验派方案】
{json.dumps(bear_plan, ensure_ascii=False, indent=2)}

【原始POI数据】
{data_json}

【融合任务】
1. 采纳Bull的路线效率 + Bear的节奏把控
2. 每天POI数控制在3-5个
3. 同区域POI合并，跨区换天
4. 标注每个POI的预计到访时间和停留时长
5. 每段交通给出建议方式和预估时间
6. 每天标注一个主题（如"浦西人文日"/"浦东现代日"）

输出纯JSON格式：
{{
  "itinerary": [
    {{
      "day": 1,
      "label": "主题名",
      "pois": [
        {{
          "poi_id": 1,
          "name": "POI名称",
          "location": [经度, 纬度],
          "address": "地址",
          "time_slot": "09:00-10:30",
          "duration_min": 90,
          "note": "游玩提示"
        }}
      ],
      "lunch": "午餐建议",
      "dinner": "晚餐建议",
      "transit_summary": "本日交通概要"
    }}
  ],
  "daily_pacing": ["轻松", "适中", "紧凑"],
  "tips": "整体出行建议"
}}"""

    print("  [Step 6.3] Fusion 综合裁决中...")
    fusion_raw = _call_deepseek(
        "你是首席旅行规划师，综合多方意见输出最优路线。返回纯JSON。",
        fusion_prompt, temperature=0.2, max_tokens=4000
    )
    print(f"    完成: {len(fusion_raw.get('itinerary', []))} 天行程")

    # 转换为标准格式（填充完整POI信息）
    itinerary_raw = fusion_raw.get("itinerary", [])
    poi_map = {i + 1: p for i, p in enumerate(poi_list)}

    itinerary = []
    for day_data in itinerary_raw:
        day_pois = []
        for p in day_data.get("pois", []):
            poi_id = p.get("poi_id", 0)
            source = poi_map.get(poi_id, {})
            day_pois.append({
                "name": p.get("name", source.get("name", "")),
                "location": p.get("location", source.get("location", [0, 0])),
                "address": p.get("address", source.get("address", "")),
                "rating": source.get("rating", ""),
                "cost": source.get("cost", ""),
                "tag": source.get("tag", ""),
                "time_slot": p.get("time_slot", ""),
                "duration_min": p.get("duration_min", 60),
                "note": p.get("note", ""),
            })
        itinerary.append({
            "day": day_data.get("day", len(itinerary) + 1),
            "label": day_data.get("label", f"Day {len(itinerary) + 1}"),
            "pois": day_pois,
            "lunch": day_data.get("lunch", ""),
            "dinner": day_data.get("dinner", ""),
            "transit_summary": day_data.get("transit_summary", ""),
        })

    return itinerary, fusion_raw.get("tips", "")


if __name__ == "__main__":
    # 测试
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.amap_api import AMapClient
    c = AMapClient()

    test_pois = [
        {"name": "上海外滩", "location": [121.493167, 31.245385], "address": "上海外滩"},
        {"name": "东方明珠广播电视塔", "location": [121.499718, 31.239703], "address": "浦东陆家嘴"},
        {"name": "上海豫园", "location": [121.492497, 31.227714], "address": "黄浦区福佑路"},
        {"name": "武康大楼", "location": [121.438278, 31.204430], "address": "徐汇区武康路"},
        {"name": "上海新天地", "location": [121.474465, 31.220484], "address": "黄浦区"},
        {"name": "南京路步行街", "location": [121.483088, 31.236831], "address": "黄浦区"},
        {"name": "田子坊", "location": [121.468658, 31.208332], "address": "黄浦区泰康路"},
    ]

    itinerary, tips = plan_adversarial(test_pois, 3, "上海")
    print(f"\n最终行程: {len(itinerary)} 天")
    for d in itinerary:
        print(f"\nDay {d['day']}: {d['label']}")
        for p in d['pois']:
            print(f"  {p.get('time_slot',''):12s} {p['name']:16s} ({p.get('duration_min',0)}min) {p.get('note','')}")
    if tips:
        print(f"\n💡 {tips}")
