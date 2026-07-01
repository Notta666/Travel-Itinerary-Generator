import os
import json
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.llm import LLMClient

def build():
    print("🤖 Starting one-time LLM survey to build static POI database...")
    client = LLMClient(provider="deepseek")
    
    prompt = """你是一个中国旅游地理专家。请为中国至少 80 个主要旅游城市（包括所有省会城市、直辖市、计划单列市以及热门旅游城市如三亚、丽江、大理、桂林、黄山、舟山、绍兴、顺德等）列出它们各自最著名、最热门的 8 个旅游景点。

请务必保证：
1. 城市名字为中文简写（例如“北京”、“上海”、“广州”、“深圳”、“杭州”、“宁波”、“舟山”、“绍兴”等，不要带“市”或“区”字）。
2. 每个城市必须正好有 8 个中文景点名称，用数组表示。
3. 必须输出为一个完整的 JSON 对象，键为城市名，值为景点列表数组，例如：
{
  "北京": ["故宫博物院", "天坛", "颐和园", "八达岭长城", "南锣鼓巷", "颐和园", "什刹海", "圆明园"],
  "三亚": ["亚龙湾", "天涯海角", "蜈支洲岛", "南山文化旅游区", "大小洞天", "大东海", "亚龙湾热带天堂森林公园", "三亚湾"]
}
不要包含任何 MarkDown 标记或多余的文字，只返回合法的 JSON 字符串。
"""
    
    try:
        # Call the LLM to get the JSON content
        res = client.call("旅游地理专家。返回纯JSON。", prompt, response_format={"type": "json_object"})
        
        # Parse it to validate correctness
        if isinstance(res, str):
            res = json.loads(res.strip())
            
        if not isinstance(res, dict) or len(res) < 30:
            raise ValueError(f"Generated data is invalid or too small: {type(res)}, keys count: {len(res) if isinstance(res, dict) else 0}")
            
        # Ensure data folder exists
        data_dir = os.path.join(PROJECT_ROOT, "data")
        os.makedirs(data_dir, exist_ok=True)
        
        output_path = os.path.join(data_dir, "default_pois.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
            
        print(f"✅ Success! Static POI database built with {len(res)} cities.")
        print(f"📍 Saved to: {output_path}")
        
    except Exception as e:
        print(f"❌ Failed to build static POI database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    build()
