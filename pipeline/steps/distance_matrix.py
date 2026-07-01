import sys, os, json, time, copy, re, datetime, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("travel_pipeline")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.amap_api import AMapClient
amap = AMapClient()

def step_5_distance_matrix(context):
    """高德驾车路径规划API: 计算POI间距离/时长"""
    print(f"\n{'='*50}")
    print(f"Step 5/9: 距离矩阵 📏")
    print(f"{'='*50}")
    pois = context["poi_enriched"]
    if len(pois) < 2:
        print("  ⚠️ POI不足, 跳过")
        return context
    tuples = [(p["name"], p["location"][0], p["location"][1]) for p in pois]
    if hasattr(amap, 'distance_matrix_parallel'):
        matrix = amap.distance_matrix_parallel(tuples, max_workers=4)
    else:
        matrix = amap.distance_matrix(tuples)
    context["distance_matrix"] = matrix
    labels, mat = matrix["labels"], matrix["matrix"]
    print(f"  矩阵: {len(labels)}x{len(labels)}")
    for i in range(len(labels)):
        for j in range(i+1, min(i+3, len(labels))):
            d = mat[i][j]
            if d and d.get("distance"):
                print(f"    {labels[i][:12]:12s} -> {labels[j][:12]:12s}  {d['distance']/1000:.1f}km / {d['duration']//60}min")
    return context
