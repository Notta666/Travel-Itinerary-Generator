"""
小红书调研工具模块
===================
基于 Agent-Reach + OpenCLI + Chrome 进行小红书搜索

使用方式:
    from utils.research import XiaoHongShu
    xhs = XiaoHongShu()
    notes = xhs.search("上海美食推荐", limit=5)
"""

import subprocess, json, re, os, time, shutil

def _find_opencli():
    """查找 opencli 可执行文件路径"""
    # 优先检查 PATH 中的绝对路径
    which = shutil.which("opencli")
    if which:
        return os.path.abspath(which)
    # 常见全局安装位置
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
    """小红书搜索工具 (依赖 OpenCLI + Chrome)"""

    def __init__(self):
        self.connected = False
        self._check_opencli()

    def _check_opencli(self):
        """检查 OpenCLI 是否可用"""
        if not _OPENCLI:
            print("⚠️  OpenCLI 未安装或未在 PATH 中，小红书搜索将不可用")
            return
        try:
            r = subprocess.run([_OPENCLI, "doctor"], capture_output=True, text=True, timeout=5)
            if "Extension: not connected" in r.stdout or "FAIL" in r.stdout:
                print("⚠️  OpenCLI 扩展未连接, 小红书搜索不可用")
            else:
                self.connected = True
        except FileNotFoundError:
            print("⚠️  OpenCLI 未安装, 小红书搜索不可用")
        except Exception as e:
            print(f"⚠️  OpenCLI 检查失败: {e}")

    def search(self, query, limit=5, city=""):
        """
        小红书搜索
        query: 搜索关键词 (如 "上海美食推荐")
        limit: 返回笔记数 (默认5)
        city: 城市限定 (可选, 如 "上海")
        返回: [{rank, author, title, likes, url, published_at}]
        """
        if not _OPENCLI:
            print("⚠️  OpenCLI 未安装，跳过小红书搜索")
            return []
        if not self.connected:
            print("⚠️  OpenCLI 扩展未连接/不可用，跳过小红书搜索以节省时间")
            return []
        
        # 净化查询，防止命令注入与越权参数传递
        query = re.sub(r'[\r\n\t;|<>&`$]', '', query)
        query = query.strip()
        if query.startswith("-"):
            query = "./" + query
            
        if city:
            query = f"{city}{query}"
        try:
            r = subprocess.run(
                [_OPENCLI, "xiaohongshu", "search", query, "-f", "yaml", "--limit", str(limit)],
                capture_output=True, text=True, timeout=30
            )
            output = r.stdout.strip()
            if not output:
                return []
            return self._parse_yaml_results(output)
        except subprocess.TimeoutExpired:
            print(f"⏱️  小红书搜索超时: {query}")
            return []
        except Exception as e:
            print(f"❌ 小红书搜索失败: {e}")
            return []

    def search_food(self, city, limit=5):
        """搜索城市美食攻略"""
        return self.search(f"{city}美食推荐", limit=limit)

    def search_tourist(self, city, limit=5):
        """搜索城市旅游攻略"""
        return self.search(f"{city}旅游攻略", limit=limit)

    def search_itinerary(self, city, days=3, limit=5):
        """搜索城市行程规划"""
        return self.search(f"{city}{days}日游攻略", limit=limit)

    def get_comments(self, note_url, limit=10):
        """获取小红书笔记评论（使用 YAML 格式解析）"""
        if not _OPENCLI:
            return []
        if not self.connected:
            return []
        try:
            r = subprocess.run(
                [_OPENCLI, "xiaohongshu", "comments", note_url, "-f", "yaml", "--limit", str(limit)],
                capture_output=True, text=True, timeout=20
            )
            output = r.stdout.strip()
            if not output:
                return []
            
            # YAML格式首列也是 `- rank:`，可以直接复用 _parse_yaml_results 解析器
            raw_comments = self._parse_yaml_results(output)
            # 兼容 `text` 键
            parsed = []
            for rc in raw_comments:
                parsed.append({
                    "author": rc.get("author", "匿名"),
                    "text": rc.get("text", rc.get("title", "")), # title 或 text 字段
                    "likes": int(rc.get("likes", 0)) if rc.get("likes") else 0
                })
            return parsed
        except Exception as e:
            print(f"⚠️ 获取小红书评论失败: {e}")
            return []


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
                    # YAML折叠值标记，下一行是真正的值
                    current["_fold_" + key] = True
                    current[key] = ""
                elif key.startswith("_fold_"):
                    # 上一行是折叠标记，清理
                    pass
                elif value and value != "null":
                    # 检查是否URL（如 https://... 被误解析为 key: value）
                    if key in ("http", "https"):
                        # 这是折叠URL的续行
                        for k in list(current.keys()):
                            if k.startswith("_fold_"):
                                real_key = k[6:]
                                current[real_key] = line.strip().strip("'\"")
                                del current[k]
                                break
                    else:
                        current[key] = value
            elif line.strip().startswith("http") or line.strip().startswith("//"):
                # URL行，可能属于前面的折叠键
                for k in list(current.keys()):
                    if k.startswith("_fold_"):
                        real_key = k[6:]
                        current[real_key] = line.strip().strip("'\"")
                        del current[k]
                        break
        if current and current.get("title"):
            notes.append(current)
        return notes

    def read_note_content(self, note_url):
        """
        精读小红书笔记内容（通过Jina Reader）
        返回: {title, author, content_text}
        """
        import urllib.request
        try:
            url = "https://r.jina.ai/" + urllib.request.quote(note_url, safe='/:?=&')
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            # 提取正文
            lines = raw.split("\n")
            content = "\n".join(line for line in lines
                               if line.strip() and "cookie" not in line.lower() and len(line.strip()) > 10)
            return {
                "url": note_url,
                "content": content[:2000],
            }
        except Exception as e:
            return {"url": note_url, "content": f"[读取失败: {e}]"}


# ---- 测试 ----
if __name__ == "__main__":
    xhs = XiaoHongShu()
    print("=== 搜索上海美食 ===")
    notes = xhs.search_food("上海", limit=3)
    for n in notes:
        print(f"  [{n.get('rank','?')}] {n.get('title','无标题')}")
        print(f"      作者: {n.get('author','?')} | 👍 {n.get('likes','?')} | {n.get('published_at','?')}")
        print(f"      链接: {n.get('url','?')}")
        print()
