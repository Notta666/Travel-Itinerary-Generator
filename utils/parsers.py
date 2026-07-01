import re, time

def _parse_budget(budget_str, days=2, people_count=2):
    """解析预算字符串，返回(每人每天预算, 总预算)"""
    if not budget_str:
        return (None, None)
    nums = re.findall(r'\d+', budget_str.replace(',', ''))
    if not nums:
        return (None, None)
    budget_vals = [int(n) for n in nums if int(n) >= 100]
    if not budget_vals:
        return (None, None)
    total = max(budget_vals)

    is_daily = any(x in budget_str for x in ['天', '日', 'daily', '每天', '每日'])
    is_per_person = any(x in budget_str for x in ['人均', '每人', '每人每天', '人均每天', '单人', '/人'])

    specified_people = people_count
    match_people = re.search(r'(\d+|两|三|四|五|六)人', budget_str)
    if match_people:
        p_word = match_people.group(1)
        if p_word == '两':
            specified_people = 2
        elif p_word == '三':
            specified_people = 3
        elif p_word == '四':
            specified_people = 4
        elif p_word.isdigit():
            specified_people = int(p_word)

    if is_daily:
        if is_per_person:
            daily_per_person = total
        else:
            daily_per_person = total // max(specified_people, 1)
    else:
        if is_per_person:
            daily_per_person = total // max(days, 1)
        else:
            daily_per_person = total // (max(specified_people, 1) * max(days, 1))

    total_trip_budget = daily_per_person * max(days, 1) * people_count
    return (max(daily_per_person, 1), total_trip_budget)

def _parse_goal(goal_text):
    """用LLM将自然语言目标解析为结构化参数，自动补全缺省信息"""
    from utils.tips import _season
    season_name, season_desc = _season()
    prompt = f"""你是一个旅行规划助手。将用户的自然语言需求解析为结构化JSON。
自动补全所有缺失信息，做出合理默认选择。

【用户需求】
{goal_text}

【解析规则】
- city: 提取城市名。如果只给了省份，选该省最热门旅游城市。如果给了模糊描述(如"南方""看海")，推荐合适城市。
- multi_cities: 【重要】如果 days >= 5 或目的地是省份/区域名（如"浙江""云南""四川"），输出多城市列表，按地理位置顺路排列，每个城市停留 1-3 天。如果 days < 5 且目的地是具体城市，输出空数组 []。
- start_city: 提取出发城市/起点城市。如果用户没有规定出发地点或未提及，输出空字符串 ""。
- days: 提取天数。如果给了"周末"→2，如果给了模糊时间→推荐天数，默认2。
- start_date: 出行日期(格式: YYYY-MM-DD)。如果用户提到了具体日期(如'7/5-7/6'或'7月5日')，请结合当前日期所在的年份(当前为2026年)解析出开始日期(例如'2026-07-05')。如果未提供，默认写今天({time.strftime("%Y-%m-%d")})。
- pois: 提取或推荐该城市最值得去的景点/地标(3-8个)，只要景点名不要餐厅。如果用户没指定，根据目的地自动推荐。
- transport: 提取交通方式("自驾"/"高铁"/"飞机")。如果没给,<200km默认自驾,200-800km高铁,>800km飞机。
- budget: 预算描述。如果用户没给，默认"两人共3000/天（含住宿/交通/饮食/门票）"
- preference: 偏好描述(如"亲子","情侣","美食","休闲"),空字符串表示无特殊偏好。
- accommodation: 住宿区域或酒店名，根据行程路线推荐顺路区域，少绕路。如果没给，根据行程路线推荐合适区域.
- people_count: 提取出行人数。例如"我们四个人" -> 4，"三口之家" -> 3。如果未明示，默认输出 2。

【当前季节】{season_name}（{season_desc}），推荐相应季节的景点与活动。

输出纯JSON，严格按以下格式，不要多余文字：
{{"city":"城市名","multi_cities":["城市1","城市2"],"start_city":"出发城市","days":2,"start_date":"YYYY-MM-DD","pois":["景点1","景点2"],"transport":"方式","budget":"描述","preference":"描述","accommodation":"描述","people_count":2}}"""

    try:
        from utils.llm import call_deepseek
        result = call_deepseek("你是一个旅行规划助手。返回纯JSON。", prompt, temperature=0.3, max_tokens=2000)
        if isinstance(result, dict):
            city = result.get("city", "上海")
            start_city = result.get("start_city", "")
            days = int(result.get("days", 2))
            pois = result.get("pois", [])
            transport = result.get("transport", "")
            budget = result.get("budget", "")
            preference = result.get("preference", "")
            accommodation = result.get("accommodation", "")
            start_date = result.get("start_date", "")
            people_count = int(result.get("people_count", 2))
            multi_cities = result.get("multi_cities", [])
            print(f"\\n🎯 目标解析结果:")
            print(f"   出发城市: {start_city or '未指定(将通过IP定位)'}")
            print(f"   目的地: {city}")
            if multi_cities:
                print(f"   多城市: {' → '.join(multi_cities)}")
            print(f"   出行日期: {start_date}")
            print(f"   天数: {days}")
            print(f"   人数: {people_count} 人")
            print(f"   交通: {transport or '未指定'}")
            print(f"   预算: {budget or '不限'}")
            print(f"   偏好: {preference or '无'}")
            print(f"   住宿: {accommodation}" if accommodation else "   住宿: 未指定")
            print(f"   POI: {', '.join(pois[:8])}")
            print(f"   多城市: {' → '.join(multi_cities)}" if multi_cities else "")
            return city, days, pois, {
                "transport": transport,
                "budget": budget,
                "preference": preference,
                "accommodation": accommodation,
                "start_date": start_date,
                "start_city": start_city,
                "people_count": people_count,
                "multi_cities": multi_cities,
                "_budget_parsed": _parse_budget(budget, days, people_count),
            }
    except Exception as e:
        print(f"  ⚠️ 目标解析失败: {e}，使用默认参数")
    return "上海", 2, [], {}