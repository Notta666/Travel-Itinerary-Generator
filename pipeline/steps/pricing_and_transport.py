import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()

def step_55_flyai_pricing(context):
    """飞猪 FlyAI 实时机票/高铁/酒店价格查询（并行）

    数据写入 context["flyai_prices"]:
      flight/train/hotel: {items, source, cheapest}
      available: True/False

    如果 FlyAI 不可用或查询失败，静默降级（当前固定百分比算法不受影响）。
    """
    print(f"\n{'='*50}")
    print(f"Step 5.5/9: 飞猪 FlyAI 实时物价查询 ✈️🚄🏨")
    print(f"{'='*50}")

    try:
        from utils.flyai_api import FlyAIApiClient
        client = FlyAIApiClient()
        if not client.check_environment():
            print("  ⚠️ FlyAI CLI 不可用，跳过实时物价查询")
            context["flyai_prices"] = {"available": False}
            return context
    except ImportError:
        print("  ⚠️ utils.flyai_api 未安装，跳过实时物价查询")
        context["flyai_prices"] = {"available": False}
        return context
    except Exception as e:
        print(f"  ⚠️ FlyAI 初始化失败: {e}")
        context["flyai_prices"] = {"available": False}
        return context

    city = context["city"]
    prefs = context.get("preferences", {})
    start_city = prefs.get("start_city", "")
    start_date = context.get("start_date", "")
    days = context.get("days", 2)
    transport = prefs.get("transport", "")
    people = prefs.get("people_count", 2)
    hotel_budget_min = prefs.get("hotel_budget_min", 300)
    hotel_budget_max = prefs.get("hotel_budget_max", 500)

    if not start_city or not start_date:
        print("  ⚠️ 缺少出发城市或日期，跳过实时物价查询")
        context["flyai_prices"] = {"available": False}
        return context

    from datetime import datetime, timedelta
    try:
        dep_date = datetime.strptime(start_date, "%Y-%m-%d")
        ret_date = (dep_date + timedelta(days=days)).strftime("%Y-%m-%d")
    except ValueError:
        ret_date = ""

    results = {}

    # 1. 交通工具查询 (高铁/机票)
    if transport and dep_date:
        time.sleep(1.0)
        try:
            if transport in ("飞机", "flight"):
                items, source = client.query_flight(start_city, city, start_date)
                key = "flight"
            elif transport in ("高铁", "train", "动车"):
                items, source = client.query_train(start_city, city, start_date)
                key = "train"
            else:
                items, source = None, "fail"
                key = ""

            if key:
                if items:
                    cheapest = min(items, key=lambda x: x["price"])
                    results[key] = {
                        "items": items, "source": source,
                        "cheapest": cheapest["price"], "count": len(items)
                    }
                    print(f"  ✅ {key}: 查询成功, 最低价 ¥{cheapest['price']}")
                else:
                    results[key] = {"items": [], "source": source, "cheapest": None, "count": 0}
                    print(f"  ⚠️ {key}: 查询无数据/失败")
        except Exception as e:
            print(f"  ⚠️ {transport} 查询异常: {e}")

    # 2. 酒店查询
    time.sleep(1.5)
    try:
        items, source = client.query_hotel(
            city, start_date, ret_date or start_date, 
            None, hotel_budget_max if hotel_budget_max else None, people
        )
        key = "hotel"
        if items:
            # 酒店按用户选择的预算区间过滤
            if hotel_budget_min or hotel_budget_max:
                filtered = []
                for item in items:
                    p = item.get("price", 0)
                    if hotel_budget_min and p < hotel_budget_min:
                        continue
                    if hotel_budget_max and p > hotel_budget_max:
                        continue
                    filtered.append(item)
                if filtered:
                    items = filtered
                    print(f"  🏨 预算过滤: {len(items)}/{len(filtered)} 家在 ¥{hotel_budget_min}~{hotel_budget_max}/晚")
                else:
                    print(f"  ⚠️ 无 ¥{hotel_budget_min}~{hotel_budget_max} 酒店，显示全部")
            
            cheapest = min(items, key=lambda x: x["price"])
            results[key] = {
                "items": items, "source": source,
                "cheapest": cheapest["price"], "count": len(items)
            }
            # 调试：记录酒店 API 返回的可选字段质量
            h0 = items[0]
            debug_fields = {k: h0.get(k, "❌缺失") for k in ("star", "decoration_time", "main_pic", "jump_url", "rating")}
            print(f"  🔍 酒店字段样例: {debug_fields}")
        else:
            results[key] = {"items": [], "source": source, "cheapest": None, "count": 0}
            print(f"  ⚠️ hotel: 查询无数据/失败")
    except Exception as e:
        results["hotel"] = {"items": [], "source": "error", "cheapest": None, "count": 0}
        print(f"  ⚠️ hotel 异常: {e}")

    results["available"] = bool(results)
    context["flyai_prices"] = results
    n = sum(1 for v in results.values() if isinstance(v, dict) and v.get("cheapest"))
    print(f"  ✅ FlyAI 物价查询完成: {n} 品类有数据")
    return context


def step_56_transport_decision(context, amap=None):
    """基于实际地理位置和实时票价，用 LLM 综合决策最佳交通方式。

    覆盖 Step 0 Goal解析中 LLM 凭常识猜测的 transport 值。
    决策因素（按权重）：
      1. start_city → city 的实际驾车距离
      2. 机票/高铁实时最低价（FlyAI 数据）
      3. 预算约束
      4. 出行人数
    """
    print(f"\n{'='*50}")
    print(f"Step 5.6/9: 交通方式重评估 🚗✈️🚄")
    print(f"{'='*50}")

    prefs = context.get("preferences", {})
    current_transport = prefs.get("transport", "").strip()
    start_city = prefs.get("start_city", "")
    city = context.get("city", "")
    people_count = prefs.get("people_count", 2)
    budget = prefs.get("budget", "")
    flyai = context.get("flyai_prices", {})

    if not start_city or not city:
        print("  ⏭️  缺出发城市或目标城市，跳过交通重评估")
        return context

    if not amap:
        from utils.amap_api import AMapClient
        amap = AMapClient()

    # 1. 计算实际距离
    start_coord = amap.geocode(start_city)
    dest_coord = amap.geocode(city)
    if not start_coord or not dest_coord:
        print("  ⚠️  地理编码失败，跳过交通重评估")
        return context

    # Haversine 直线距离
    import math
    R = 6371
    lng1, lat1 = math.radians(start_coord[0]), math.radians(start_coord[1])
    lng2, lat2 = math.radians(dest_coord[0]), math.radians(dest_coord[1])
    dlng, dlat = lng2 - lng1, lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    line_dist = R * 2 * math.asin(math.sqrt(a))

    # 驾车距离（高德 API 更准）
    drive_dist, drive_dur = line_dist, line_dist / 80 * 60  # 默认80km/h
    try:
        route = amap.direction_driving(start_coord, dest_coord)
        if route:
            drive_dist = route.get("distance", drive_dist * 1000) / 1000
            drive_dur = route.get("duration", drive_dur * 60) / 60
    except Exception:
        pass

    print(f"  📏 直线距离: {line_dist:.0f}km")
    print(f"  🚗 驾车距离: {drive_dist:.0f}km / {drive_dur:.0f}min")

    # 2. 提取实时票价信息
    flight_price = None
    train_price = None
    if flyai.get("available"):
        fd = flyai.get("flight", {})
        if fd.get("cheapest"):
            flight_price = fd["cheapest"]
        td = flyai.get("train", {})
        if td.get("cheapest"):
            train_price = td["cheapest"]

    # 3. LLM 综合决策
    from utils.llm import call_deepseek
    prompt = f"""你是一个交通规划专家。根据以下信息，为本次旅行推荐最佳交通方式。

【出发地】{start_city}
【目的地】{city}
【驾车距离】{drive_dist:.0f}km（约 {drive_dur:.0f} 分钟）
【出行人数】{people_count} 人
【预算】{budget or '未指定'}
【机票最低价】{'¥' + str(flight_price) + '/人' if flight_price else '无数据'}
【高铁最低价】{'¥' + str(train_price) + '/人' if train_price else '无数据'}
【原定方式】{current_transport or '未指定'}

决策规则：
1. < 150km：推荐自驾（最灵活）
2. 150-400km：推荐高铁（省时省力），也可自驾（有车的话）
3. 400-900km：推荐高铁（性价比最高），如果机票特别便宜且机场方便可坐飞机
4. > 900km：推荐飞机（否则太累），如果价格过高也可考虑高铁卧铺
5. 有实时票价数据时，优先选择性价比最高的方式：
   - 机票¥{flight_price or '?'}/人 vs 高铁¥{train_price or '?'}/人，算总价（×{people_count}人）
6. 预算有限时，优先选最省钱的合理方式

输出格式（纯JSON，无需多余文字）：
{{"transport": "自驾|高铁|飞机", "reason": "不超过30字的原因说明"}}"""

    try:
        result = call_deepseek("交通规划专家。返回纯JSON。", prompt, temperature=0.2, max_tokens=500)
        if isinstance(result, dict):
            new_transport = result.get("transport", "").strip()
            reason = result.get("reason", "")
            if new_transport in ("自驾", "高铁", "飞机"):
                old = current_transport or "未指定"
                print(f"  🚗 原定: {old} → 🎯 推荐: {new_transport}（{reason}）")
                if current_transport and new_transport != current_transport:
                    print(f"  🔄 覆盖原定交通方式: {old} → {new_transport}")
                elif not current_transport:
                    print(f"  ✅ 自动决策交通方式: {new_transport}")
                prefs["transport"] = new_transport
                context["preferences"] = prefs
                # 更新 flyai 查询：如果决策变了，重新查询正确的品类
                if flyai.get("available"):
                    if new_transport == "飞机" and not flyai.get("flight", {}).get("items"):
                        print(f"  🔄 追加查询机票价格...")
                        from utils.flyai_api import FlyAIApiClient
                        fc = FlyAIApiClient()
                        items, src = fc.query_flight(start_city, city, context.get("start_date", ""))
                        if items:
                            flyai["flight"] = {"items": items, "source": src, "cheapest": items[0]["price"], "count": len(items)}
                            context["flyai_prices"] = flyai
                    elif new_transport == "高铁" and not flyai.get("train", {}).get("items"):
                        print(f"  🔄 追加查询高铁价格...")
                        from utils.flyai_api import FlyAIApiClient
                        fc = FlyAIApiClient()
                        items, src = fc.query_train(start_city, city, context.get("start_date", ""))
                        if items:
                            flyai["train"] = {"items": items, "source": src, "cheapest": items[0]["price"], "count": len(items)}
                            context["flyai_prices"] = flyai
            else:
                print(f"  ⚠️ LLM 返回异常交通方式: {new_transport}，保留原值")
        else:
            print(f"  ⚠️ LLM 返回非 dict: {result}")
    except Exception as e:
        print(f"  ⚠️ LLM 交通决策失败: {e}，保留原方式")

    print(f"  ✅ 最终交通方式: {prefs.get('transport', '未指定')}")
    return context
