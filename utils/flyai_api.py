"""
飞猪 FlyAI 开放平台 API 封装
=============================
专为 AI Agent 设计的旅行数据查询 SDK。

基于 @fly-ai/flyai-cli CLI 工具，通过 subprocess 调用。

能力：
  - ✈️ query_flight: 机票实时价格查询
  - 🚄 query_train: 高铁/火车实时价格查询
  - 🏨 query_hotel: 酒店实时价格查询
  - 🎯 query_poi: 景点信息查询
  - 🎫 query_poi_ticket: 门票价格级联提取（正则→LLM→搜索→降级）

缓存策略（分级 TTL）：
  - flight/hotel: 30分钟（价格浮动快）
  - train: 24小时（国铁定价固定）
  - poi: 7天（门票极少变动）

使用方式:
    from utils.flyai_api import FlyAIApiClient
    client = FlyAIApiClient()
    flights, source = client.query_flight("上海", "杭州", "2026-07-04")
"""
import os
import re
import json
import time
import hashlib
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("travel_pipeline")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FlyAIApiClient:
    """飞猪 FlyAI API 客户端封装"""

    # 全局安装的 flyai CLI 路径
    CLI_BINARY = os.path.join(
        os.environ.get("USERPROFILE", os.environ.get("HOME", "")),
        "AppData", "Roaming", "npm", "flyai.cmd"
    )

    # 品类独立缓存 TTL（秒）
    DEFAULT_TTLS = {
        "flight": 1800,      # 机票实时价格 — 30分钟
        "hotel": 1800,       # 酒店实时价格 — 30分钟
        "train": 86400,      # 高铁/火车 — 24小时（国铁定价几乎不变）
        "poi": 604800,       # 景点/门票 — 7天
    }

    def __init__(self, cache_dir=None, ttls=None):
        self.cache_dir = cache_dir or os.path.join(BASE_DIR, "data", "cache", "flyai")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.ttls = {**self.DEFAULT_TTLS, **(ttls or {})}
        self._cli_available = None  # 懒检测
        self.risk_blocked = False  # 标记是否已被风控封锁

    # ------------------------------------------------------------------
    # 环境检测
    # ------------------------------------------------------------------

    def check_environment(self, force=False):
        """静默检测 Node.js + flyai CLI 可用性

        Returns:
            bool: True 表示可用，False 表示不可用
        """
        if self._cli_available is not None and not force:
            return self._cli_available
        try:
            r = subprocess.run(
                [self.CLI_BINARY, "search-flight", "--help"],
                capture_output=True, text=True, timeout=5, errors="replace"
            )
            self._cli_available = r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            self._cli_available = False
        return self._cli_available

    # ------------------------------------------------------------------
    # 分级缓存系统
    # ------------------------------------------------------------------

    def _get_cache_path(self, cmd_type, params):
        """参数哈希化防文件名冲突，每个品类独立子文件"""
        param_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        param_hash = hashlib.md5(param_str.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{cmd_type}_{param_hash}.json")

    def _read_cache(self, cmd_type, cache_path):
        """读取缓存，校验 TTL"""
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            elapsed = time.time() - data.get("cached_at", 0)
            ttl = self.ttls.get(cmd_type, 1800)
            if elapsed < ttl:
                return data.get("result")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"读取 FlyAI 缓存失败: {e}")
        return None

    def _write_cache(self, cmd_type, cache_path, result):
        """写入缓存（带时间戳）"""
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "cached_at": time.time(),
                    "cmd_type": cmd_type,
                    "result": result,
                }, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"写入 FlyAI 缓存失败: {e}")

    # ------------------------------------------------------------------
    # 核心 CLI 执行器（防御性编程）
    # ------------------------------------------------------------------

    def _run_cli(self, args):
        """核心防御性子进程执行器

        Features:
            - 12秒超时防死锁
            - ANSI 转义符清洗
            - 正则提取首个 JSON 对象（防 npm 日志污染）
            - 针对 429 Rate Limit 限流的指数退避重试逻辑
            - 完整异常捕获链

        Args:
            args: CLI 参数列表，不含 binary（如 ["search-flight", "--origin=上海", ...]）

        Returns:
            dict|list|None: 解析后的 JSON 结果
        """
        if getattr(self, "risk_blocked", False):
            return None
        cmd = [self.CLI_BINARY] + args
        retries = 3
        backoff = 2.0
        
        for attempt in range(retries):
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    errors="replace"
                )
                if res.returncode != 0:
                    stderr = res.stderr or ""
                    if "429" in stderr or "Rate limit exceeded" in stderr:
                        if attempt < retries - 1:
                            logger.warning(f"FlyAI CLI 触发限流 (429)，将在 {backoff} 秒后进行第 {attempt+1} 次重试...")
                            time.sleep(backoff)
                            backoff *= 2
                            continue
                    elif "403" in stderr or "451" in stderr or "Abnormal access behavior" in stderr:
                        logger.warning(f"  ⚠️ FlyAI 接口触发平台风控限制，已自动切换为本地/高德数据源降级兜底。")
                        self.risk_blocked = True
                        return None
                    
                    stderr_snippet = stderr[:200]
                    logger.warning(
                        f"FlyAI CLI 异常退出 (code={res.returncode}): {stderr_snippet}"
                    )
                    return None

                raw = res.stdout or ""

                # 清洗 ANSI 转义字符
                clean = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", raw).strip()

                # 正则提取首个 JSON 对象/数组（防 npm 日志/版本提示等杂质）
                json_match = re.search(r"(\{.*\}|\[.*\])", clean, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(1))
                return json.loads(clean) if clean else None

            except subprocess.TimeoutExpired:
                logger.error(f"FlyAI CLI 超时 (30s): {cmd[1]}")
                break
            except json.JSONDecodeError as e:
                snippet = (res.stdout if "res" in dir() else "")[:100]
                logger.error(f"FlyAI JSON 解析失败: {e} | 输出前100字符: {snippet}")
                break
            except FileNotFoundError:
                logger.error("FlyAI CLI 未安装: 请执行 npm i -g @fly-ai/flyai-cli")
                self._cli_available = False
                break
            except Exception as e:
                logger.error(f"FlyAI CLI 异常: {e}")
                break

        return None

    # ------------------------------------------------------------------
    # 公共查询方法
    # ------------------------------------------------------------------

    def query_flight(self, origin, destination, date, max_price=None, sort_type=3):
        """查询机票实时价格

        返回 items 中每个 item 包含:
        - price: 最低价
        - journeys: 行程段数组，每段含 dep/arr 机场/时间/航班号
        - jump_url: 预订链接
        """
        params = {"origin": origin, "destination": destination, "date": date}
        cache_path = self._get_cache_path("flight", params)

        # 1. 尝试缓存
        cached = self._read_cache("flight", cache_path)
        if cached:
            return cached, "cache"

        # 2. 实时查询
        args = [
            "search-flight",
            f"--origin={origin}",
            f"--destination={destination}",
            f"--dep-date={date}",
            f"--sort-type={sort_type}",
        ]
        if max_price:
            args.append(f"--max-price={max_price}")

        raw = self._run_cli(args)
        if raw:
            items = raw.get("data", {}).get("itemList", [])
            result = []
            for item in items:
                ticket_price = item.get("ticketPrice")
                if ticket_price:
                    journeys = item.get("journeys", [])
                    # 提取直达段详情
                    segs = []
                    for j in journeys:
                        for s in j.get("segments", []):
                            segs.append({
                                "flight_no": s.get("marketingTransportNo", ""),
                                "airline": s.get("marketingTransportName", ""),
                                "seat_class": s.get("seatClassName", ""),
                                "dep_airport": s.get("depStationName", ""),
                                "dep_terminal": s.get("depTerm", ""),
                                "dep_time": s.get("depDateTime", ""),
                                "arr_airport": s.get("arrStationName", ""),
                                "arr_terminal": s.get("arrTerm", ""),
                                "arr_time": s.get("arrDateTime", ""),
                                "duration_min": s.get("duration", ""),
                                "journey_type": j.get("journeyType", ""),
                            })
                    result.append({
                        "price": float(ticket_price),
                        "segments": segs,
                        "jump_url": item.get("jumpUrl", ""),
                    })
            if result:
                self._write_cache("flight", cache_path, result)
                return result, "live"

        return None, "fail"

    def query_train(self, origin, destination, date, max_price=None):
        """查询高铁/火车实时价格

        返回 items 中每个 item 包含:
        - price: 票价
        - segments: 行程段，每段含车次号/出发站+时间/到达站+时间/座位等级
        - jump_url: 预订链接
        """
        params = {"origin": origin, "destination": destination, "date": date}
        cache_path = self._get_cache_path("train", params)

        cached = self._read_cache("train", cache_path)
        if cached:
            return cached, "cache"

        args = [
            "search-train",
            f"--origin={origin}",
            f"--destination={destination}",
            f"--dep-date={date}",
        ]
        if max_price:
            args.append(f"--max-price={max_price}")

        raw = self._run_cli(args)
        if raw:
            items = raw.get("data", {}).get("itemList", [])
            result = []
            for item in items:
                price = item.get("price")
                if price:
                    journeys = item.get("journeys", [])
                    segs = []
                    for j in journeys:
                        for s in j.get("segments", []):
                            segs.append({
                                "train_no": s.get("marketingTransportNo", ""),
                                "train_type": s.get("marketingTransportName", ""),
                                "seat_class": s.get("seatClassName", ""),
                                "dep_station": s.get("depStationName", ""),
                                "dep_time": s.get("depDateTime", ""),
                                "arr_station": s.get("arrStationName", ""),
                                "arr_time": s.get("arrDateTime", ""),
                                "duration_min": s.get("duration", ""),
                                "journey_type": j.get("journeyType", ""),
                            })
                    result.append({
                        "price": float(price),
                        "segments": segs,
                        "jump_url": item.get("jumpUrl", ""),
                    })
            if result:
                self._write_cache("train", cache_path, result)
                return result, "live"

        return None, "fail"

    def query_hotel(self, dest_name, checkin, checkout, keywords=None, max_price=None, people_count=2):
        """查询酒店实时价格

        自动按人数计算所需房间数: ceil(people_count / 2)

        Args:
            dest_name: 城市/目的地（如"杭州"或"西湖"）
            checkin: 入住日期 YYYY-MM-DD
            checkout: 离店日期 YYYY-MM-DD
            keywords: 关键词（如"西湖附近"）
            max_price: 每间夜价格上限
            people_count: 出行人数

        Returns:
            (result_list or None, source): source='live'/'cache'/'fail'
        """
        rooms = max(1, (people_count + 1) // 2)

        params = {
            "dest": dest_name, "checkin": checkin,
            "checkout": checkout, "rooms": rooms,
        }
        cache_path = self._get_cache_path("hotel", params)

        cached = self._read_cache("hotel", cache_path)
        if cached:
            return cached, "cache"

        args = [
            "search-hotel",
            f"--dest-name={dest_name}",
            f"--check-in-date={checkin}",
            f"--check-out-date={checkout}",
        ]
        if keywords:
            args.append(f"--key-words={keywords}")
        if max_price:
            args.append(f"--max-price={max_price}")

        raw = self._run_cli(args)
        if raw:
            items = raw.get("data", {}).get("itemList", [])
            result = []
            for item in items:
                price_raw = item.get("price", "")
                price_val = 0
                if price_raw:
                    price_str = re.sub(r"[¥￥,，\s]", "", str(price_raw))
                    try:
                        price_val = float(price_str) * rooms
                    except ValueError:
                        price_val = 0
                result.append({
                    "name": item.get("name", ""),
                    "price": price_val,
                    "rating": item.get("rating", ""),
                    "star": item.get("star", ""),
                    "address": item.get("address", ""),
                    "decoration_time": item.get("decorationTime", ""),
                    "rooms": rooms,
                    "jump_url": item.get("jumpUrl", ""),
                    "main_pic": item.get("mainPic", ""),
                    "jump_url": item.get("jumpUrl", "") or item.get("detailUrl", ""),
                })
            if result:
                self._write_cache("hotel", cache_path, result)
                return result, "live"

        return None, "fail"

    def query_poi(self, city, keyword=None):
        """查询景点基本信息

        Args:
            city: 城市
            keyword: 关键词（如"西湖"），为空则查询城市所有热门景点

        Returns:
            (result_list or None, source)
        """
        params = {"city": city, "keyword": keyword or ""}
        cache_path = self._get_cache_path("poi", params)

        cached = self._read_cache("poi", cache_path)
        if cached:
            return cached, "cache"

        args = ["search-poi", f"--city={city}"]
        if keyword:
            args.append(f"--keyword={keyword}")

        raw = self._run_cli(args)
        if raw:
            items = raw.get("data", {}).get("itemList", [])
            result = []
            for item in items:
                result.append({
                    "name": item.get("name", ""),
                    "level": item.get("level", ""),
                    "type": item.get("type", ""),
                    "address": item.get("address", ""),
                    "description": item.get("description", ""),
                })
            if result:
                self._write_cache("poi", cache_path, result)
                return result, "live"

        return None, "fail"

    def query_poi_ticket_booking(self, poi_name, city):
        """获取景点门票预订链接（ai-search 兜底）

        FlyAI 未提供门票预订 API，通过 ai-search 搜索可预订的平台链接。

        Returns:
            str or None: 预订URL（飞猪/携程等），None 表示未找到
        """
        queries = [
            f"{city}{poi_name}门票预订",
            f"{poi_name}门票",
        ]
        for query in queries:
            if getattr(self, "risk_blocked", False):
                break
            time.sleep(3.5)  # 主动限速防429/403
            try:
                raw = self._run_cli(["ai-search", f"--query={query}"])
                if raw and isinstance(raw, dict):
                    text = json.dumps(raw, ensure_ascii=False)
                    # 提取预订链接：fliggy / ctrip / trip.com 等
                    urls = re.findall(
                        r'(https?://(?:www\.)?(?:fliggy|feizhu|ctrip|trip|mafengwo|qunar)'
                        r'\.(?:com|cn)[^\s"\'<>]*)',
                        text
                    )
                    if urls:
                        return urls[0].rstrip(",.，)")
            except Exception:
                continue
        return None

    def query_poi_ticket(self, poi_name, city):
        """级联获取门票价格（4级降级）

        1st: regex 正则提取 POI 描述中的金额
        2nd: ai-search 自然语言搜索兜底
        3rd: 返回 None（百分比估算降级）

        Args:
            poi_name: 景点名称
            city: 城市

        Returns:
            dict or None: {"price_min": N, "price_max": N, "source": "regex|ai_search|fail"}
                          source='fail' 时表示需降级到百分比估算
        """
        # 1st: 从 POI 缓存中提取描述
        cache_dir = os.path.join(BASE_DIR, "data", "cache", "flyai")
        if os.path.exists(cache_dir):
            try:
                for fname in os.listdir(cache_dir):
                    if fname.startswith("poi_"):
                        with open(os.path.join(cache_dir, fname), "r", encoding="utf-8") as f:
                            data = json.load(f)
                        for item in (data.get("result", []) if isinstance(data, dict) and "result" in data else
                                     (data if isinstance(data, list) else [])):
                            if isinstance(item, dict) and poi_name in item.get("name", ""):
                                desc = item.get("description", "")
                                prices = re.findall(r"(?:¥|￥|价格|票价)?\s*(\d{2,4})\s*(?:元|/人|起)", desc)
                                if prices:
                                    vals = sorted(int(p) for p in prices if int(p) > 5)
                                    if vals:
                                        return {
                                            "price_min": vals[0],
                                            "price_max": vals[-1],
                                            "source": "regex",
                                        }
            except (OSError, json.JSONDecodeError):
                pass

        # 2nd: ai-search 自然语言搜索（多格式尝试，通过 time.sleep 降频防429）
        query_templates = [
            f"{city}{poi_name}门票价格",
            f"{poi_name}门票",
        ]
        for query in query_templates:
            if getattr(self, "risk_blocked", False):
                break
            time.sleep(3.5)  # 主动限速降频防403
            try:
                raw = self._run_cli(["ai-search", f"--query={query}"])
                if raw and isinstance(raw, dict):
                    text = json.dumps(raw, ensure_ascii=False)
                    # 宽泛提取：数字+元/人/起/张/位
                    prices = re.findall(r"(?:¥|￥|价格|票价|门票)?\s*(\d{2,4})\s*(?:元|/人|/张|/位|起)", text)
                    if prices:
                        vals = sorted(int(p) for p in prices if int(p) > 5)
                        if vals:
                            return {
                                "price_min": vals[0],
                                "price_max": vals[-1],
                                "source": "ai_search",
                            }
            except Exception:
                continue

        # 3rd: 降级
        return {"price_min": None, "price_max": None, "source": "fail"}

    # ------------------------------------------------------------------
    # 批量查询（并行）
    # ------------------------------------------------------------------

    def query_all(self, flight=None, train=None, hotel=None, poi_list=None):
        """并行查询所有品类价格

        Args:
            flight: (origin, destination, date) 或 None
            train: (origin, destination, date) 或 None
            hotel: (city, checkin, checkout, dest_name, people_count) 或 None
            poi_list: [(name, city), ...] 或 None

        Returns:
            dict: {
                "flight": (result, source),
                "train": (result, source),
                "hotel": (result, source),
                "tickets": [(name, ticket_dict)],
            }
        """
        result = {}

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {}

            if flight:
                futures["flight"] = ex.submit(
                    self.query_flight, flight[0], flight[1], flight[2]
                )
            if train:
                futures["train"] = ex.submit(
                    self.query_train, train[0], train[1], train[2]
                )
            if hotel:
                h = hotel
                futures["hotel"] = ex.submit(
                    self.query_hotel, h[0], h[1], h[2],
                    h[3] if len(h) > 3 else None,
                    h[4] if len(h) > 4 else None,
                    h[5] if len(h) > 5 else 2,
                )

            for key, future in futures.items():
                try:
                    result[key] = future.result()
                except Exception as e:
                    logger.warning(f"FlyAI 并行查询 {key} 失败: {e}")
                    result[key] = (None, "fail")

            # 门票查询
            if poi_list:
                ticket_results = []
                for name, city in poi_list:
                    try:
                        ticket_results.append((name, self.query_poi_ticket(name, city)))
                    except Exception as e:
                        ticket_results.append((name, {"price_min": None, "price_max": None, "source": "fail"}))
                result["tickets"] = ticket_results

        return result


# ---- 独立测试 ----
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    client = FlyAIApiClient()

    print("=" * 60)
    print("FlyAIApiClient 集成测试")
    print("=" * 60)

    # 环境检测
    ok = client.check_environment(force=True)
    print(f"\n🔍 环境检测: {'✅ 可用' if ok else '❌ 不可用'}")

    if not ok:
        print("请安装 flyai-cli: npm i -g @fly-ai/flyai-cli")
        exit(1)

    # 机票查询
    print("\n✈️  机票: 上海→杭州 2026-07-04")
    flights, source = client.query_flight("上海", "杭州", "2026-07-04")
    if flights:
        cheapest = min(flights, key=lambda x: x["price"])
        print(f"  最低价: ¥{cheapest['price']}  ({source})")
        for f in flights[:3]:
            print(f"  ¥{f['price']:.0f} | {f['journeys'][0]['segments'][0]['depDateTime']} → ...")
    else:
        print(f"  ❌ 查询失败 ({source})")

    # 高铁查询
    print("\n🚄  高铁: 上海→杭州 2026-07-04")
    trains, source = client.query_train("上海", "杭州", "2026-07-04")
    if trains:
        print(f"  最低价: ¥{trains[0]['price']:.0f}  ({source})")
        for t in trains[:3]:
            seg = t["journeys"][0]["segments"][0]
            print(f"  ¥{t['price']:.0f} | {seg.get('marketingTransportNo','')} {seg['depDateTime']}→{seg['arrDateTime']}")
    else:
        print(f"  ❌ 查询失败 ({source})")

    # 酒店查询
    print("\n🏨  酒店: 杭州 2026-07-04~07-05 2人")
    hotels, source = client.query_hotel("杭州", "2026-07-04", "2026-07-05", people_count=2)
    if hotels:
        cheapest = min(hotels, key=lambda x: x["price"]) if hotels else None
        print(f"  最便宜: ¥{cheapest['price']:.0f}/{cheapest['rooms']}间  ({source})")
        for h in hotels[:3]:
            print(f"  ¥{h['price']:.0f} | {h['name'][:20]} ⭐{h['rating']}")
    else:
        print(f"  ❌ 查询失败 ({source})")

    # 门票查询
    print("\n🎫  门票: 西湖")
    ticket = client.query_poi_ticket("西湖", "杭州")
    if ticket["source"] != "fail":
        print(f"  ¥{ticket['price_min']}~{ticket['price_max']}  ({ticket['source']})")
    else:
        print("  未获取到门票价格")

    print("\n✅ 测试完成")
