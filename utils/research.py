"""
小红书调研工具模块
==================
双引擎策略：
  1. Playwright（首选）— 基于 Chromium 浏览器自动化，更稳定
  2. OpenCLI（降级）  — 基于 Chrome 扩展，Playwright 不可用时自动切换

使用方式:
    from utils.research import XiaoHongShu
    xhs = XiaoHongShu()
    notes = xhs.search("上海美食推荐", limit=5)
"""
import subprocess, json, re, os, time, shutil
from utils.playwright_xhs import PlaywrightXHS, HAS_PLAYWRIGHT


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
    """小红书搜索工具（双引擎：Playwright → OpenCLI 降级）"""

    def __init__(self):
        self.connected = False
        self._engine = None  # "playwright" or "opencli"
        self._pw_client = None
        self._check_engines()

    def _check_engines(self):
        """检测可用引擎，Playwright 优先"""
        # 1. 检测 Playwright
        if HAS_PLAYWRIGHT:
            try:
                pw = PlaywrightXHS(headless=True)
                if pw._launch():
                    pw._close()
                    self._pw_client = PlaywrightXHS(headless=True)
                    self._engine = "playwright"
                    self.connected = True
                    print("   ✅ 小红书引擎: Playwright")
                    return
            except Exception:
                pass

        # 2. 降级到 OpenCLI
        if _OPENCLI:
            try:
                r = subprocess.run([_OPENCLI, "doctor"], capture_output=True, text=True, timeout=5)
                if "Extension: not connected" not in r.stdout and "FAIL" not in r.stdout:
                    self._engine = "opencli"
                    self.connected = True
                    print("   ✅ 小红书引擎: OpenCLI（降级）")
                    return
            except Exception:
                pass

        print("   ⚠️ 小红书不可用：Playwright 未启动且 OpenCLI 未连接")

    # ================================================================
    # 搜索
    # ================================================================

    def search(self, query, limit=5, city=""):
        """搜索小红书笔记"""
        if city:
            query = f"{city}{query}"
        if self._engine == "playwright" and self._pw_client:
            try:
                notes = self._pw_client.search(query, limit)
                if notes:
                    return notes
            except Exception:
                print("  ⚠️ Playwright 搜索失败，尝试降级到 OpenCLI...")
                self._engine = None
                self._check_engines()

        # OpenCLI 降级
        if self._engine == "opencli" and _OPENCLI:
            return self._search_opencli(query, limit)

        return []

    def _search_opencli(self, query, limit=5):
        """使用 OpenCLI 搜索"""
        query = re.sub(r'[\r\n\t;|<>&`$]', '', query).strip()
        if query.startswith("-"):
            query = "./" + query
        try:
            r = subprocess.run(
                [_OPENCLI, "xiaohongshu", "search", query, "-f", "yaml", "--limit", str(limit)],
                capture_output=True, text=True, timeout=30
            )
            output = r.stdout.strip()
            return self._parse_yaml_results(output) if output else []
        except subprocess.TimeoutExpired:
            print(f"⏱️  小红书搜索超时: {query}")
            return []
        except Exception as e:
            print(f"❌ 小红书搜索失败: {e}")
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
        if self._engine == "playwright" and self._pw_client:
            try:
                comments = self._pw_client.get_comments(note_url, limit)
                if comments:
                    return comments
            except Exception:
                pass

        if self._engine == "opencli" and _OPENCLI:
            return self._get_comments_opencli(note_url, limit)
        return []

    def _get_comments_opencli(self, note_url, limit=10):
        """使用 OpenCLI 获取评论"""
        try:
            r = subprocess.run(
                [_OPENCLI, "xiaohongshu", "comments", note_url, "-f", "yaml", "--limit", str(limit)],
                capture_output=True, text=True, timeout=20
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

    # ================================================================
    # 精读笔记（用 Jina Reader，与引擎无关）
    # ================================================================

    def read_note_content(self, note_url):
        """精读小红书笔记内容（通过 Jina Reader）"""
        import urllib.request
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
            # 如果能通过 Playwright 获取标题，补充进去
            title = ""
            if self._engine == "playwright" and self._pw_client:
                try:
                    pw_content = self._pw_client.read_note_content(note_url)
                    title = pw_content.get("title", "")
                    if pw_content.get("content"):
                        content = pw_content["content"]
                except Exception:
                    pass
            return {"url": note_url, "title": title, "content": content[:2000]}
        except Exception as e:
            return {"url": note_url, "content": f"[读取失败: {e}]"}

    # ================================================================
    # YAML 解析（OpenCLI 格式）
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
    notes = xhs.search_food("上海", limit=3)
    for n in notes:
        print(f"  [{n.get('rank','?')}] {n.get('title','无标题')[:30]}")
        print(f"      作者: {n.get('author','?')} | 👍 {n.get('likes','?')}")
        print(f"      链接: {n.get('url','?')}")
        print()
