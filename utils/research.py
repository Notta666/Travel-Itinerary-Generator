"""
小红书调研工具模块
==================
核心引擎：
  1. OpenCLI — 基于 Chrome 扩展，负责抓取真实笔记与评论。
  2. LLM 仿真（降级兜底）— 当 OpenCLI 未连接或抓取失败时，大模型自动生成高仿真笔记与防雷评价。

使用方式:
    from utils.research import XiaoHongShu
    xhs = XiaoHongShu()
    notes = xhs.search("上海美食推荐", limit=5)
"""
import subprocess
import json
import re
import os
import time
import shutil
import base64
import tempfile
import urllib.request


def _find_opencli():
    """查找 opencli 可执行文件路径"""
    which = shutil.which("opencli")
    if which:
        return os.path.abspath(which)
    candidates = [
        os.path.expanduser("~/AppData/Roaming/npm/opencli"),
        os.path.expanduser("~/AppData/Roaming/npm/opencli.cmd"),
        os.path.expanduser("~/.npm-global/bin/opencli"),
    ]
    for p in candidates:
        abs_p = os.path.abspath(p)
        if os.path.isfile(abs_p) or os.path.isfile(abs_p + ".cmd"):
            return abs_p if os.path.isfile(abs_p) else abs_p + ".cmd"
    return None


_OPENCLI = _find_opencli()


class XiaoHongShu:
    """小红书搜索工具（OpenCLI 核心 + LLM 降级）"""

    def __init__(self):
        self.connected = bool(_OPENCLI)
        self._simulated_cache = {}
        if self.connected:
            print("   ✅ 小红书引擎: OpenCLI (Chrome Extension)")
        else:
            print("   ⚠️ 小红书不可用：未找到 OpenCLI，将默认使用大模型仿真降级")

    # ================================================================
    # 搜索
    # ================================================================

    def search(self, query, limit=5, city=""):
        """搜索小红书笔记"""
        if city:
            query = f"{city}{query}"
        
        notes = []
        if self.connected:
            notes = self._search_opencli(query, limit)

        # 禁用大模型兜底（遵照用户硬性要求，拿不到数据就返回空）
        if not notes:
            print(f"  ⚠️ 真实数据获取为空或失败：\"{query}\"，且已禁用LLM仿真模拟。")

        return notes

    def _search_opencli(self, query, limit=5):
        """使用 OpenCLI 搜索"""
        query = re.sub(r'[\r\n\t;|<>&`$]', '', query).strip()
        if query.startswith("-"):
            query = "./" + query
        try:
            r = subprocess.run(
                [_OPENCLI, "xiaohongshu", "search", query, "-f", "yaml", "--limit", str(limit)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
            )
            if r.returncode != 0:
                print(f"  ❌ opencli 搜索返回非零状态码 ({r.returncode}): {r.stderr.strip()[:200]}")
                return []
            output = r.stdout.strip()
            return self._parse_yaml_results(output) if output else []
        except subprocess.TimeoutExpired:
            print(f"⏱️  小红书搜索超时: {query}")
            return []
        except Exception as e:
            print(f"❌ 小红书搜索异常: {e}")
            return []

    def search_food(self, city, limit=5):
        return self.search(f"{city}美食推荐", limit=limit)

    def search_tourist(self, city, limit=5):
        return self.search(f"{city}旅游攻略", limit=limit)

    def search_itinerary(self, city, days=3, limit=5):
        return self.search(f"{city}{days}日游攻略", limit=limit)

    # ================================================================
    # 评论
    # ================================================================

    def get_comments(self, note_url, limit=10):
        """获取笔记评论"""
        if self.connected:
            return self._get_comments_opencli(note_url, limit)
        return []

    def _get_comments_opencli(self, note_url, limit=10):
        """使用 OpenCLI 获取评论"""
        try:
            r = subprocess.run(
                [_OPENCLI, "xiaohongshu", "comments", note_url, "-f", "yaml", "--limit", str(limit)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20
            )
            output = r.stdout.strip()
            if not output:
                return []
            raw = self._parse_yaml_results(output)
            parsed = []
            for rc in raw:
                parsed.append({
                    "author": rc.get("author", "匿名"),
                    "text": rc.get("text", rc.get("title", "")),
                    "likes": int(rc.get("likes", 0)) if rc.get("likes") else 0
                })
            return parsed
        except Exception as e:
            print(f"⚠️ 获取小红书评论失败: {e}")
            return []

    def download_note_images(self, note_url, max_images=3):
        """下载笔记的图片并返回 base64 编码列表"""
        if not self.connected:
            return []
            
        tmp_dir = tempfile.mkdtemp(prefix="xhs_img_")
        try:
            subprocess.run(
                [_OPENCLI, "xiaohongshu", "download", note_url, "-f", "yaml", "--output", tmp_dir],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
            )
            images = []
            if os.path.exists(tmp_dir):
                for root, _, files in os.walk(tmp_dir):
                    for file in sorted(files):
                        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                            filepath = os.path.join(root, file)
                            if os.path.getsize(filepath) < 5 * 1024 * 1024:
                                with open(filepath, "rb") as f:
                                    b64 = base64.b64encode(f.read()).decode("utf-8")
                                    images.append(b64)
                                if len(images) >= max_images:
                                    break
                    if len(images) >= max_images:
                        break
            return images
        except Exception as e:
            print(f"⚠️ 下载图片失败: {e}")
            return []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ================================================================
    # 精读笔记
    # ================================================================

    def read_note_content(self, note_url):
        """精读小红书笔记内容（OpenCLI 或 Jina Reader）"""
        # 优先通过 OpenCLI 获取
        if self.connected:
            try:
                r = subprocess.run(
                    [_OPENCLI, "xiaohongshu", "note", note_url, "-f", "json"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20
                )
                if r.returncode == 0 and r.stdout.strip():
                    data = json.loads(r.stdout.strip())
                    content_str = ""
                    for item in data:
                        if isinstance(item, dict) and item.get("field") == "content":
                            content_str = item.get("value", "")
                            break
                    if content_str:
                        return {"url": note_url, "title": "", "content": content_str}
            except Exception:
                pass # 失败则降级使用 Jina

        # Jina Reader 兜底抓取网页内容
        try:
            url = "https://r.jina.ai/" + urllib.request.quote(note_url, safe='/:?=&')
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            lines = raw.split("\n")
            content = "\n".join(
                line for line in lines
                if line.strip() and "cookie" not in line.lower() and len(line.strip()) > 10
            )
            return {"url": note_url, "title": "", "content": content[:2000]}
        except Exception as e:
            return {"url": note_url, "content": f"[读取失败: {e}]"}

    # ================================================================
    # LLM 仿真兜底
    # ================================================================

    def _generate_simulated_notes(self, query, limit=5):
        """利用 LLM 生成仿真的小红书笔记和评论进行高品质兜底"""
        import hashlib
        from utils.llm import LLMClient

        client = LLMClient(provider="deepseek")
        system_prompt = "你是一个小红书资深旅游博主和当地吃喝玩乐排雷达人。"
        user_prompt = f"""请为搜索词“{query}”生成 {limit} 篇高度逼真的仿真小红书笔记及相关用户评论。
要求：
1. 必须包含非常真实且具体的景点、餐厅或路边摊名字，切勿全是抽象概念。
2. 笔记内容中应包含真实的游玩攻略、体验细节，以及明确的干货和避雷吐槽（如排队拥挤、名气大但难吃、特定时间段人巨多等）。
3. 每篇笔记底部要配有 3-4 条极具口语化和互动感的用户评论，既要有极力推荐的赞同，也要有吐槽排队的避雷反馈。
4. 返回 JSON 格式，结构如下（严格符合 JSON 规范）：
{{
  "notes": [
    {{
      "title": "符合小红书风格的笔记标题",
      "author": "博主小红书昵称",
      "content": "笔记详细正文内容...",
      "comments": [
        {{"author": "互动网友A", "text": "评论或赞同内容...", "likes": 12}},
        {{"author": "路人吐槽B", "text": "排队排了俩小时，不值！真的建议别去...", "likes": 5}}
      ]
    }}
  ]
}}
请只返回上述结构的 JSON 数据。"""
        try:
            res = client.call(system_prompt, user_prompt, response_format={"type": "json_object"})
            if isinstance(res, str):
                match = re.search(r"(\{.*\})", res.strip(), re.DOTALL)
                if match:
                    clean_json = match.group(1)
                else:
                    clean_json = res.strip()
                data = json.loads(clean_json)
            else:
                data = res

            notes_list = data.get("notes", [])
            query_hash = hashlib.md5(query.encode("utf-8")).hexdigest()[:8]
            
            parsed_notes = []
            for i, n in enumerate(notes_list):
                sim_url = f"http://simulated/{query_hash}/{i}"
                self._simulated_cache[sim_url] = n
                parsed_notes.append({
                    "title": n.get("title", ""),
                    "url": sim_url,
                    "author": n.get("author", "匿名博主")
                })
            print(f"     ✅ 成功模拟生成了 {len(parsed_notes)} 篇小红书仿真笔记及评论数据")
            return parsed_notes
        except Exception as e:
            print(f"  ❌ 模拟小红书笔记数据生成失败: {e}")
            return []

    # ================================================================
    # 解析辅助
    # ================================================================

    def _parse_yaml_results(self, yaml_text):
        """解析 opencli 返回的 YAML 格式结果"""
        notes = []
        current = {}
        for line in yaml_text.split("\n"):
            line = line.rstrip()
            if line.startswith("- rank:"):
                if current and current.get("title"):
                    notes.append(current)
                current = {"rank": line.split(":")[1].strip()}
            elif ":" in line and current is not None:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip("'\"")
                if value == ">-":
                    current["_fold_" + key] = True
                    current[key] = ""
                elif key.startswith("_fold_"):
                    pass
                elif value and value != "null":
                    if key in ("http", "https"):
                        for k in list(current.keys()):
                            if k.startswith("_fold_"):
                                real_key = k[6:]
                                current[real_key] = line.strip().strip("'\"")
                                del current[k]
                                break
                    else:
                        current[key] = value
            elif line.strip().startswith("http") or line.strip().startswith("//"):
                for k in list(current.keys()):
                    if k.startswith("_fold_"):
                        real_key = k[6:]
                        current[real_key] = line.strip().strip("'\"")
                        del current[k]
                        break
        if current and current.get("title"):
            notes.append(current)
        return notes


# ---- 测试 ----
if __name__ == "__main__":
    xhs = XiaoHongShu()
    print("\n=== 搜索上海美食 ===")
    # PYTHONPATH=. python utils/research.py
    notes = xhs.search_food("上海", limit=3)
    for n in notes:
        print(f"  [{n.get('rank','?')}] {n.get('title','无标题')[:30]}")
        print(f"      作者: {n.get('author','?')} | 👍 {n.get('likes','?')}")
        print(f"      链接: {n.get('url','?')}")
        print()
