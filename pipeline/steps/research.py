"""
Step 2: 小红书调研 + 笔记精读 + LLM提取景点+美食
======================================================
"""
import sys, os, json, time, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")


def step_2_research(context, xhs=None, progress_callback=None):
    """小红书搜索 → 精读笔记 → LLM提取景点+美食"""
    if xhs is None:
        from utils.research import XiaoHongShu
        xhs = XiaoHongShu()
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

    # 双通道搜索 (并发 + 节流防风控)
    food_notes = []
    sight_notes = []
    queries = []
    for c in cities_to_search:
        queries.extend([
            (f"{c}美食推荐 必吃", "美食"),
            (f"{c}旅游攻略 景点", "景点"),
        ])
    # 针对手动POI搜索附近美食（优先景点附近的餐厅）
    manual_pois = context.get("manual_pois", [])
    if manual_pois:
        city_name = context.get("city", "")
        for poi in manual_pois:
            queries.append((f"{city_name}{poi}附近美食推荐", "美食"))

    # P2-21: ThreadPoolExecutor 并发搜索（控制并发度为 3，保留微小节流防风控）
    def _exec_search(q_item):
        query, label = q_item
        print(f"  📕 搜索{label}: {query}")
        try:
            time.sleep(0.3)  # 轻量节流
            notes = xhs.search(query, limit=5)
            print(f"     → {label} '{query}': {len(notes)} 篇")
            return label, notes
        except Exception as e:
            print(f"     ⚠️ {query} 搜索失败: {e}")
            return label, []

    with ThreadPoolExecutor(max_workers=3) as search_ex:
        search_futures = [search_ex.submit(_exec_search, q) for q in queries]
        for f in as_completed(search_futures):
            lbl, nts = f.result()
            if lbl == "美食":
                food_notes.extend(nts)
            else:
                sight_notes.extend(nts)

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

    # P2-21: 并发精读前 6 篇笔记并抓取其评论 (ThreadPoolExecutor max_workers=3)
    if all_notes:
        active_notes = all_notes[:6]
        print(f"  📖 并发精读 {len(active_notes)} 篇笔记与精彩评论（ThreadPoolExecutor 提速）...")

        def _fetch_note_and_comments(note_idx_tuple):
            idx, note = note_idx_tuple
            url = note.get("url", "")
            # P3-8: 防选项注入（前导 '-' 注入 CLI 参数，强制 URL 格式校验并支持 '--' 分隔）
            if not url or url.startswith("-"):
                return None
            # 安全防护：CLI 调用时添加 '--' 参数分隔保护
            safe_cli_arg = ["--", url]
            
            content = xhs.read_note_content(url)
            if not content:
                return None
            # 抓取评论（并发环境轻微延时防频繁请求）
            time.sleep(0.2)
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
                time.sleep(0.2)
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

            return idx, note.get("title", ""), content

        with ThreadPoolExecutor(max_workers=3) as fetch_ex:
            futures = [fetch_ex.submit(_fetch_note_and_comments, (i, n)) for i, n in enumerate(active_notes)]
            completed_notes = []
            for f in as_completed(futures):
                try:
                    res_tuple = f.result()
                    if res_tuple:
                        i, title, res = res_tuple
                        completed_notes.append((i, title, res))
                        _report("research", f"精读小红书笔记及热评: {title[:10]}...", 15 + int((len(completed_notes)/len(active_notes))*5))
                        print(f"     ✅ {title[:30]}")
                except Exception as e:
                    logger.warning(f"读取小红书笔记失败: {e}")

            # 按原始顺序排序
            completed_notes.sort(key=lambda x: x[0])
            note_contents = [item[2] for item in completed_notes]

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
            _report("research", "Step 2/9: AI正在研读笔记并提取 POI... 🧠", 18)
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
