"""
出行建议与注意事项生成器
========================
基于目的地、季节、偏好、交通方式，用LLM生成实用出行建议。
"""
import os, json, time

def _month_name():
    return time.strftime("%m月")

def _season():
    m = int(time.strftime("%m"))
    if 3 <= m <= 5: return "春季(3-5月)", "春暖花开，早晚温差大"
    if 6 <= m <= 8: return "夏季(6-8月)", "高温多雨，需防暑防晒防蚊虫"
    if 9 <= m <= 11: return "秋季(9-11月)", "秋高气爽，昼夜温差大"
    return "冬季(12-2月)", "寒冷干燥，需保暖防滑"

def generate_tips(city="上海", days=2, transport="", preference="", budget="", start_city=""):
    """生成出行建议，返回 {general: [...], preference_tips: [...], daily_tips: [...], emergency: ""}"""
    month, season_desc = _season()
    season_name = month.split("(")[0] if "(" in month else month

    prompt = f"""你是一个出行安全、旅行贴士与拍照穿搭专家。根据以下信息生成实用建议。

【起点/出发城市】{start_city or '未指定'}
【目的地】{city}
【天数】{days}天
【当前季节】{season_name}（{season_desc}）
【交通方式】{transport or '未指定'}
【用户偏好】{preference or '无特殊偏好'}
【预算】{budget or '不限'}

【通用建议与拍照穿搭要求】
1. 基于{city}的{city}气候特点给出针对性建议
2. 列出必备物品清单（身份证、充电宝、防晒等）
3. 给出{season_name}的着装和防护建议。
4. **【拍照打卡与穿搭要求】**：在 "preference_tips" 或 "general" 中，必须包含：
   - 至少一条【📷 绝美拍照打卡机位】：结合{city}热门景点的具体取景位置和拍照角度（例如：“云上草原彩虹滑道起点往下20米处，俯拍最出片”）。
   - 至少一条【👗 视觉出片穿搭指南】：针对该季节与风景，推荐适合拍照的衣服颜色与搭配风格（例如：“建议穿着亮黄色或纯白连衣裙，在绿色森林背景下对比度极佳”）。

【偏好专项建议要求】
如果是"{preference}"，请专门针对该活动给出准备建议：
- 漂流：换洗衣物、防水袋、拖鞋、手机防水套、防晒
- 爬山/徒步：登山鞋、补给水、体力分配、膝盖保护
- 亲子游：推车、哺乳室、儿童票、游乐设施安全
- 带爸妈：步速控制、休息频率、无障碍设施、慢性病药
- 情侣：浪漫餐厅推荐时段、拍照攻略
- 团建：分组建议、集合点、备用方案
- 如果无特殊偏好则给出通用休闲建议

【每日提醒】
根据行程天数和{city}特点，给出一条每日核心提醒

输出纯JSON，严格按以下格式：
{{{{
  "general": ["建议1","建议2","建议3","建议4","建议5"],
  "preference_tips": ["偏好/拍照/穿搭建议1","偏好/拍照/穿搭建议2","偏好/拍照/穿搭建议3"],
  "daily_tips": ["Day1提醒","Day2提醒"],
  "emergency": "极端天气应急方案"
}}}}"""

    default = {
        "general": [
            f"📱 提前下载{city}离线地图，避免信号弱时迷路",
            "🧴 夏季出行请做好防晒（SPF50+），携带遮阳帽/伞",
            "💧 随身携带饮用水，户外活动每人至少1L",
            "🔋 充电宝必备，导航+拍照耗电量大",
            "🆔 随身携带身份证，部分景点需实名入园"
        ],
        "preference_tips": ["根据个人偏好准备相应装备"],
        "daily_tips": [f"Day{i+1}: 注意合理安排时间" for i in range(days)],
        "emergency": "关注当地天气预报，如遇极端天气及时调整行程"
    }

    try:
        from utils.llm import call_deepseek
        result = call_deepseek("你是出行安全专家。返回纯JSON。", prompt, temperature=0.4, max_tokens=3000)
        if isinstance(result, dict):
            # 确保字段完整
            for key in default:
                if key not in result or not result[key]:
                    result[key] = default[key]
            return result
    except Exception as e:
        print(f"  ⚠️ 出行建议生成失败: {e}")
    return default
