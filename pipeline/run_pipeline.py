import sys, os, time, copy, argparse, logging, threading
from concurrent.futures import ThreadPoolExecutor

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
from utils.research import XiaoHongShu
from utils.parsers import _parse_goal

# Import refactored steps
from pipeline.steps.init import step_1_init
from pipeline.steps.research import step_2_research
from pipeline.steps.geocode import step_3_geocode
from pipeline.steps.enrich import step_4_enrich
from pipeline.steps.distance_matrix import step_5_distance_matrix
from pipeline.steps.pricing_and_transport import step_55_flyai_pricing, step_56_transport_decision
from pipeline.steps.planner import step_6_plan_itinerary
from pipeline.steps.query_tickets import step_7_query_tickets
from pipeline.steps.report import step_8_generate_report
from pipeline.steps.tips import step_85_tips
from pipeline.steps.deliver import step_9_deliver

# Multi-city orchestrator
from pipeline.multi_city_orchestrator import run_multi_city

logger = logging.getLogger("travel_pipeline")
amap = AMapClient()
xhs = XiaoHongShu()

class PipelineStoppedError(Exception):
    pass

def _check_stop(cancel_event, step_name=""):
    if cancel_event and cancel_event.is_set():
        raise PipelineStoppedError(f"User cancelled before {step_name}")

class StepTimer:
    def __init__(self, name, timings_list):
        self.name = name
        self.timings_list = timings_list
    def __enter__(self):
        self.t0 = time.time()
        return self
    def __exit__(self, *_):
        elapsed = time.time() - self.t0
        self.timings_list.append((self.name, elapsed))
        print(f"  ⏱️  {self.name} 耗时: {elapsed:.1f}s")

def _print_timing_summary(timings):
    if not timings: return
    total = sum(t for _, t in timings)
    print(f"\\n{'='*55}\\n⏱️  各步骤耗时汇总\\n{'='*55}")
    for name, elapsed in timings:
        pct = elapsed / total * 100 if total > 0 else 0
        bar = '█' * int(pct / 5) + '░' * (20 - int(pct / 5))
        print(f"  {name:<23s} {elapsed:>6.1f}s {pct:>5.1f}%  {bar}")
    print(f"{'='*55}\\n  总计: {total:>6.1f}s  100%\\n{'='*55}")

def run_pipeline(city, days=2, use_research=False, manual_pois=None, prefs=None, progress_callback=None, multi_cities=None, cancel_event=None):
    pipeline_t0 = time.time()
    timings = []
    
    _report = lambda step, msg, pct: progress_callback and progress_callback(step, msg, pct)

    if not prefs:
        prefs = {}

    multi_cities_list = multi_cities or prefs.get("multi_cities", [])

    # If Multi-City mode, route to the Multi-City Orchestrator
    if multi_cities_list and len(multi_cities_list) > 1:
        try:
            _check_stop(cancel_event, "Step 1")
            _report("init", "Step 1/9: 初始化 (多城市模式)", 5)
            with StepTimer("Step 1 初始化", timings):
                context = run_multi_city(run_pipeline, city, days, use_research, manual_pois, prefs, progress_callback, multi_cities_list, cancel_event)
            
            # Resume post-city aggregation steps
            _check_stop(cancel_event, "Step 8")
            _report("report", "Step 8/9: 攻略报告 📝", 65)
            enabled_steps = prefs.get("enabled_steps", ["research", "enrich", "distance", "flyai", "tips"])
            
            if "tips" in enabled_steps:
                with StepTimer("Step 8+8.5 报告+建议", timings):
                    with ThreadPoolExecutor(max_workers=2) as ex:
                        f8 = ex.submit(step_8_generate_report, copy.deepcopy(context))
                        f85 = ex.submit(step_85_tips, copy.deepcopy(context))
                        ctx8 = f8.result()
                        ctx85 = f85.result()
                    context["report_path"] = ctx8.get("report_path")
                    context["travel_tips"] = ctx85.get("travel_tips", {})
                    context["weather"] = ctx85.get("weather", {})
            else:
                with StepTimer("Step 8 报告", timings):
                    context = step_8_generate_report(context)
                    context["travel_tips"] = {}
                    context["weather"] = {}

            main_city = multi_cities_list[0]
            sub_cities = multi_cities_list[1:]
            context['city'] = f"{main_city}+{'+'.join(sub_cities)}"

            _check_stop(cancel_event, "Step 9")
            _report("deliver", "Step 9/9: 交付完成 ✅", 80)
            with StepTimer("Step 9 图文手册", timings):
                context = step_9_deliver(context)

        except PipelineStoppedError as e:
            print(f"\\n🛑 Pipeline 已停止: {e}\\n  已完成的步骤成果已保留。")
        finally:
            print(f"\\n⏱️  Pipeline 总耗时: {time.time() - pipeline_t0:.1f}s")
            _print_timing_summary(timings)
        _report("done", "✅ 全部完成", 100)
        return context

    # ------------------ Single City Pipeline ------------------
    try:
        start_city = prefs.get("start_city", "")
        if not start_city:
            print("🔍 检测到未指定出发地，正在获取您的实时位置...")
            start_city = amap.get_ip_location()
            if start_city:
                print(f"📍 成功获取您的实时位置为起点: {start_city}")
            else:
                print("⚠️ 实时位置获取失败，默认不设置起点")
                start_city = ""
            prefs["start_city"] = start_city

        enabled_steps = prefs.get("enabled_steps", ["research", "enrich", "distance", "flyai", "tips"])

        _check_stop(cancel_event, "Step 1")
        _report("init", "Step 1/9: 初始化", 5)
        with StepTimer("Step 1 初始化", timings):
            context = step_1_init(city, days, preferences=prefs, manual_pois=manual_pois)

        _check_stop(cancel_event, "Step 2")
        _report("research", "Step 2/9: 小红书调研 🔍", 10)
        if "research" in enabled_steps:
            with StepTimer("Step 2 小红书调研", timings):
                context = step_2_research(context, xhs=xhs, progress_callback=progress_callback)
        else:
            print("⏭️  跳过 Step 2 小红书调研 (用户配置禁用)")
            context.update({"research_notes": [], "note_contents": [], "xhs_pois": {"sights": [], "foods": []}, "xhs_sight_names": [], "xhs_food_data": []})

        _check_stop(cancel_event, "Step 3")
        _report("geocode", "Step 3/9: POI地理编码 🗺️", 25)
        with StepTimer("Step 3 POI地理编码", timings):
            context = step_3_geocode(context, manual_pois)

        _check_stop(cancel_event, "Step 4")
        _report("enrich", "Step 4/9: POI丰富+美食 🍽️", 35)
        if "enrich" in enabled_steps:
            with StepTimer("Step 4 POI丰富+美食", timings):
                context = step_4_enrich(context)
        else:
            print("⏭️  跳过 Step 4 POI丰富+美食 (用户配置禁用)")
            context["poi_enriched"] = [{"name": p["name"], "location": list(p["location"]), "address": "", "district": "", "nearby_food": []} for p in context["poi_geocoded"]]
            context["food_recommendations"] = []

        _check_stop(cancel_event, "Step 5")
        _report("distance", "Step 5/9: 距离矩阵 📏", 45)
        if "distance" in enabled_steps:
            with StepTimer("Step 5 距离矩阵", timings):
                context = step_5_distance_matrix(context)
        else:
            print("⏭️  跳过 Step 5 距离矩阵 (用户配置禁用)")
            context["distance_matrix"] = {"matrix": [], "labels": []}

        _check_stop(cancel_event, "Step 5.5")
        if "flyai" in enabled_steps:
            with StepTimer("Step 5.5 FlyAI实时物价", timings):
                context = step_55_flyai_pricing(context)
        else:
            context.setdefault("flyai_prices", {"available": False})

        _check_stop(cancel_event, "Step 5.6")
        _report("transport_decision", "Step 5.6/9: 交通方式重评估 🚗✈️🚄", 48)
        with StepTimer("Step 5.6 交通决策", timings):
            context = step_56_transport_decision(context, amap=amap)

        _check_stop(cancel_event, "Step 6")
        _report("plan_itinerary", "多方案路线辩论规划 ✨", 50)
        with StepTimer("Step 6 路线辩论规划", timings):
            context = step_6_plan_itinerary(context, amap=amap, progress_callback=progress_callback)

        _check_stop(cancel_event, "Step 7")
        _report("pricing", "Step 7/9: 景点门票查询 🎫", 55)
        with StepTimer("Step 7 门票查询", timings):
            context = step_7_query_tickets(context)

        _check_stop(cancel_event, "Step 8")
        _report("report", "Step 8/9: 攻略报告 📝", 65)
        if "tips" in enabled_steps:
            with StepTimer("Step 8+8.5 报告+建议", timings):
                with ThreadPoolExecutor(max_workers=2) as ex:
                    f8 = ex.submit(step_8_generate_report, copy.deepcopy(context))
                    f85 = ex.submit(step_85_tips, copy.deepcopy(context))
                    ctx8 = f8.result()
                    ctx85 = f85.result()
                context["report_path"] = ctx8.get("report_path")
                context["travel_tips"] = ctx85.get("travel_tips", {})
                context["weather"] = ctx85.get("weather", {})
        else:
            with StepTimer("Step 8 报告", timings):
                context = step_8_generate_report(context)
                context["travel_tips"] = {}
                context["weather"] = {}

        _check_stop(cancel_event, "Step 9")
        _report("deliver", "Step 9/9: 交付完成 ✅", 80)
        with StepTimer("Step 9 图文手册", timings):
            context = step_9_deliver(context)

    except PipelineStoppedError as e:
        print(f"\\n🛑 Pipeline 已停止: {e}\\n  已完成的步骤成果已保留。")
    finally:
        print(f"\\n⏱️  Pipeline 总耗时: {time.time() - pipeline_t0:.1f}s")
        _print_timing_summary(timings)

    _report("done", "✅ 全部完成", 100)
    return context


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="旅游攻略生成 Pipeline (Refactored)")
    parser.add_argument("--city", default="", help="目的地城市")
    parser.add_argument("--days", type=int, default=0, help="行程天数")
    parser.add_argument("--research", action="store_true", help="开启小红书调研")
    parser.add_argument("--pois", default="", help="手动POI,逗号分隔")
    parser.add_argument("--goal", default="", help="自然语言目标描述(如'浙江周末自驾')")
    parser.add_argument("--start-city", default="", help="出发城市")
    args = parser.parse_args()

    # Manual cancel event for CLI testing
    cancel_evt = threading.Event()

    if args.goal:
        city, days, pois, prefs = _parse_goal(args.goal)
        if args.city: city = args.city
        if args.days: days = args.days
        if args.pois: pois = [p.strip() for p in args.pois.split(",") if p.strip()]
        if args.start_city: prefs["start_city"] = args.start_city
        print(f"\\n{'='*50}\\n🎯 目标: {args.goal}\\n{'='*50}")
        run_pipeline(city, days, args.research, pois, prefs, cancel_event=cancel_evt)
    else:
        city = args.city or "上海"
        days = args.days or 2
        pois = [p.strip() for p in args.pois.split(",") if p.strip()] if args.pois else None
        prefs = {"start_city": args.start_city} if args.start_city else None
        run_pipeline(city, days, args.research, pois, prefs, cancel_event=cancel_evt)
