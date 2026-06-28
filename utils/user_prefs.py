"""
用户偏好记忆系统
================
持久化用户偏好到 data/user_prefs.json
自动学习：目的地城市、偏好关键词、交通方式、预算范围
"""
import os, json, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFS_FILE = os.path.join(BASE, "data", "user_prefs.json")


def _load():
    if os.path.exists(PREFS_FILE):
        try:
            with open(PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"visited_cities": [], "preferences": {}, "transports": [], "budgets": []}


def _save(data):
    os.makedirs(os.path.dirname(PREFS_FILE), exist_ok=True)
    with open(PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_prefs():
    """获取用户所有偏好"""
    return _load()


def update_from_goal(city, prefs):
    """根据一次 goal 解析结果更新偏好"""
    data = _load()

    # 记录访问城市（最近10个，去重保留顺序）
    if city and city not in data["visited_cities"]:
        data["visited_cities"].insert(0, city)
        data["visited_cities"] = data["visited_cities"][:10]

    # 偏好关键词
    p = prefs.get("preference", "")
    if p and p != "无":
        key = p.lower()
        data["preferences"][key] = data["preferences"].get(key, 0) + 1

    # 交通方式
    t = prefs.get("transport", "")
    if t and t not in data["transports"]:
        data["transports"] = (data["transports"] + [t])[-5:]

    # 预算
    b = prefs.get("budget", "")
    if b and b not in data["budgets"]:
        data["budgets"] = (data["budgets"] + [b])[-3:]

    _save(data)


def get_suggestions(city=""):
    """根据历史偏好给出建议（用于--goal未指定时填充）"""
    data = _load()
    suggestions = {}

    if data["preferences"]:
        # 最常出现的偏好
        top_pref = max(data["preferences"], key=data["preferences"].get)
        suggestions["preference"] = top_pref

    if data["transports"]:
        suggestions["transport"] = data["transports"][-1]

    if data["budgets"]:
        suggestions["budget"] = data["budgets"][-1]

    return suggestions


if __name__ == "__main__":
    # 测试
    update_from_goal("安吉", {"transport": "自驾", "preference": "漂流", "budget": "2人4000"})
    print(json.dumps(get_prefs(), ensure_ascii=False, indent=2))
    print("建议:", get_suggestions())
