"""
Step 2: 小红书调研 + 笔记精读 + LLM提取景点+美食
======================================================
"""
import sys, os, json, time, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")


def step_2_research(context, xhs=None, progress_callback=None):
    """小红书搜索 → 精读笔记 → LLM提取景点+美食"""
    _report = lambda step, msg, pct: progress_callback and progress_callback(step, msg, pct)
    _report("research", "Step 2/9: 小红书调研 🔍（景点+美食双通道）", 15)

    print(f"\n{'='*50}")
    print(f"Step 2/9: 小红书调研 🔍（景点+美食双通道）")
    print(f"{'='*50}")
    cities_to_search = context.get("multi_cities", [])
    if not cities_to_search:
        cities_to_search = [context["city"]]
    all_notes = []
    note_contents = []

    # 双通道搜索 (支持多城市循环)
    food_notes = []
    sight_notes = []
    queries = []
    for c in cities_to_search:
        queries.extend([
            (f"{c}美食推荐 必吃", "美食"),
            (f"{c}旅游攻略 景点", "景点"),
        ])
    for query, label in queries:
        print(f"  📕 搜索{label}: {query}")
        try:
            notes = xhs.search(query, limit=5)
            if label == "美食":
                food_notes.extend(notes)
            else:
                sight_notes.extend(notes)
            print(f"     → {len(notes)} 篇")
        except Exception as e:
            print(f"     ⚠️ {e}")
        time.sleep(3.0)  # 主动增加延时防风控

    # 去重并交替混合，确保精读时美食与景点数量均衡
    def _filter_unique(notes):
        unique = []
        for n in notes:
            t = n.get("title", "")
            if t and t not in seen:
                seen.add(t)
                unique.append(n)
        return unique

    seen = set()
    unique_food = _filter_unique(food_notes)
    unique_sight = _filter_unique(sight_notes)

    all_notes = []
    for f, s in zip(unique_food, unique_sight):
        all_notes.append(f)
        all_notes.append(s)
    
    min_len = min(len(unique_food), len(unique_sight))
    all_notes.extend(unique_food[min_len:])
    all_notes.extend(unique_sight[min_len:])
    all_notes = all_notes[:12]

    # 串行精读前 6 篇笔记并抓取其评论
    if all_notes:
        print(f"  📖 顺序精读 {min(6, len(all_notes))} 篇笔记与精彩评论（防风控降频）...")
        active_notes = all_notes[:6]

        def _fetch_note_and_comments(note):
            url = note.get("url", "")
            if not url:
                return None
            content = xhs.read_note_content(url)
            if not content:
                return None
            # 抓取评论
            time.sleep(1.0)
            comments = xhs.get_comments(url, limit=5)
            if comments:
                c_lines = []
                for c in comments:
                    txt = c.get("text", "").strip()
                    if txt:
                        c_lines.append(f"    - {c.get('author','匿名')}: {txt} (👍{c.get('likes',0)})")
                if c_lines:
                    content["content"] += "\n【精彩评论与用户避雷反馈】:\n" + "\n".join(c_lines)
            
            # 抓取图片并进行视觉分析 (如果有支持多模态的 Vision API Key)
            from utils.config import VISION_API_KEY, VISION_API_BASE, VISION_MODEL
            if VISION_API_KEY:
                time.sleep(1.0)
                images = xhs.download_note_images(url, max_images=3)
                if images:
                    from utils.llm import LLMClient
                    client = LLMClient(provider="openai", api_key=VISION_API_KEY, base_url=VISION_API_BASE, model=VISION_MODEL)
                    try:
                        vis_result = client.call(
                            system_prompt="你是一个图片内容分析助手，擅长提取图片中的旅游相关信息。",
                            user_prompt="请分析这些图片，提取出其中的餐厅环境、菜品、价目表、景点风景、排队情况等关键信息。尽量简短且抓取重点。",
                            images=images,
                            max_tokens=500
                        )
                        content["content"] += "\n【笔记图片视觉分析】:\n" + vis_result
                    except Exception as e:
                        print(f"⚠️ 当前模型({VISION_MODEL})不支持多模态视觉分析或调用失败，自动跳过图片解析: {e}")

            return content

        for note in active_notes:
            time.sleep(2.5)  # 每篇笔记之间主动等待 2.5s
            try:
                res = _fetch_note_and_comments(note)
                if res:
                    note_contents.append(res)
                    title = note.get("title", "")
                    print(f"     ✅ {title[:30]}")
            except Exception as e:
                logger.warning(f"读取小红书笔记失败: {e}")

    # LLM提取结构化景点+美食（含避雷/赞点）
    from utils.llm import call_deepseek
    xhs_pois = {"sights": [], "foods": []}
    if note_contents:
        notes_text = "\n\n".join(
            f"【笔记{i+1}】\n{n.get('content','')[:2500]}"
            for i, n in enumerate(note_contents)
        )
        extract_prompt = f"""你是一名旅行信息整理专家。从以下{context["city"]}的小红书笔记及用户真实评论中，提取所有提到的【景点】和【餐厅/美食】。
特别注意：评论中往往包含真实的排队时长、避雷吐槽或极力推荐，请务必从正文 and 评论中提炼每个景点的"真实避雷点"与"赞点"。

要求：
1. 景点包括：自然风光、地标建筑、公园、博物馆、古镇等
2. 餐厅包括：餐馆、小吃店、咖啡馆、茶室等
3. 每个条目给出名称和简短描述（为什么值得去）
4. 从评论和正文中搜集关于该景点的避雷吐槽（排队久、门票贵、虚假宣传等）和强烈推荐点，整理填入 complaints 和 highlights 中。如果没有则写"无"
5. 按推荐热度排序，最多各取10个
6. 【关键】请根据笔记内容或常识，判断该景点/餐厅【所属的具体城市名】（例如"广州"、&#34;顺德"、&#34;珠海"、&#34;澳门"等），并在 JSON 中填入 "city" 字段。
7. ⚠️ 【真实性校验】注意区分"博主推荐"和"真实用户评价"。如果某个餐厅或菜品在评论区出现大量负面反馈（难吃/贵/名过其实/游客陷阱），必须在 complaints 中明确标注。**像西湖醋鱼这种全网公认的名过其实、专坑游客的菜品，必须在 complaints 中标注"全网黑·游客陷阱"**。

笔记与评论内容：
{notes_text}

输出格式（纯JSON，不要额外文字）：
{{"sights": [{{"name":"名称","city":"该景点所在的具体城市(如 广州/顺德/珠海/澳门等)","reason":"推荐理由","complaints":"避雷点/真实排队或踩雷吐槽","highlights":"绝美机位/赞点"}}], 
 "foods": [{{"name":"名称","city":"该餐厅所在的具体城市(如 广州/顺德/珠海/澳门等)","reason":"推荐理由","cuisine":"菜系类型","complaints":"避雷点/口味吐槽","highlights":"必点菜/赞点"}}]}}"""

        try:
            result = call_deepseek("提取POI。返回纯JSON。", extract_prompt, temperature=0.1, max_tokens=3000)
            if isinstance(result, dict):
                xhs_pois["sights"] = result.get("sights", [])
                xhs_pois["foods"] = result.get("foods", [])

                # 保存景点与美食对应的具体城市映射
                sight_city_map = {}
                for s in xhs_pois["sights"]:
                    if "name" in s and "city" in s:
                        sight_city_map[s["name"]] = s["city"]
                context["sight_city_map"] = sight_city_map

                food_city_map = {}
                for f in xhs_pois["foods"]:
                    if "name" in f and "city" in f:
                        food_city_map[f["name"]] = f["city"]
                context["food_city_map"] = food_city_map

                print(f"  🤖 LLM提取: {len(xhs_pois['sights'])}个景点 + {len(xhs_pois['foods'])}家餐厅")
                for s in xhs_pois["sights"][:3]:
                    print(f"     🏛️ {s['name']} [{s.get('city','')}] (避雷: {s.get('complaints','无')})")
                for f in xhs_pois["foods"][:3]:
                    print(f"     🍴 {f['name']} [{f.get('city','')}] (避雷: {f.get('complaints','无')})")
        except Exception as e:
            print(f"  ⚠️ LLM提取失败: {e}")
    else:
        print("  ⚠️ 未获取到小红书笔记内容")

    # 默认值兜底
    context.setdefault("sight_city_map", {})
    context.setdefault("food_city_map", {})

    context["research_notes"] = all_notes
    context["note_contents"] = note_contents
    context["xhs_pois"] = xhs_pois
    # 从xhs提取的景点名列表（供step3地理编码用）
    context["xhs_sight_names"] = [s["name"] for s in xhs_pois["sights"]]
    context["xhs_food_data"] = xhs_pois["foods"]
    print(f"  完成: {len(all_notes)}篇笔记 → {len(xhs_pois['sights'])}个景点 + {len(xhs_pois['foods'])}家餐厅")
    _report("research", f"✅ 完成: {len(xhs_pois['sights'])}个景点 + {len(xhs_pois['foods'])}家餐厅", 20)
    return context
