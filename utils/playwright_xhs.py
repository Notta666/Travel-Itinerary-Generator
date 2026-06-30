"""
Playwright 小红书调研模块
========================
替代 OpenCLI 的浏览器自动化方案，基于 Playwright + Chromium。

使用方式:
    from utils.playwright_xhs import PlaywrightXHS
    xhs = PlaywrightXHS()
    notes = xhs.search("上海美食推荐", limit=5)
    if notes:
        content = xhs.read_note_content(notes[0]["url"])
        comments = xhs.get_comments(notes[0]["url"], limit=10)

首次使用需要手动登录小红书以保存登录态。
"""
import os, json, re, time, logging
from pathlib import Path

logger = logging.getLogger("travel_pipeline")

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# 登录态存储路径
BASE_DIR = Path(__file__).parent.parent
STORAGE_FILE = BASE_DIR / "data" / "xhs_storage.json"
STEALTH_JS = """
// 隐藏 Playwright/自动化特征
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
// 覆盖 chrome 对象
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {} };
// 覆盖权限查询
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""


class PlaywrightXHS:
    """基于 Playwright 的小红书采集工具"""

    def __init__(self, headless=True, storage_file=None):
        self.headless = headless
        self.storage_file = storage_file or str(STORAGE_FILE)
        self.browser = None
        self.context = None
        self._connected = False
        if not HAS_PLAYWRIGHT:
            logger.warning("Playwright 未安装，请执行: pip install playwright && playwright install chromium")
            return

    def _launch(self):
        """启动浏览器并加载登录态"""
        if self.browser:
            return True
        if not HAS_PLAYWRIGHT:
            return False
        try:
            self._pw = sync_playwright().start()
            self.browser = self._pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            # 加载登录态
            if os.path.exists(self.storage_file):
                self.context = self.browser.new_context(
                    storage_state=self.storage_file,
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                )
            else:
                self.context = self.browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                )
            # 注入反检测脚本
            self.context.add_init_script(STEALTH_JS)
            self._connected = True
            return True
        except Exception as e:
            logger.warning(f"Playwright 启动失败: {e}")
            return False

    def _close(self):
        """关闭浏览器"""
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if hasattr(self, '_pw'):
                self._pw.stop()
        except Exception:
            pass
        finally:
            self.browser = None
            self.context = None
            self._connected = False

    def _ensure_page(self):
        """获取或创建新页面"""
        if not self._connected and not self._launch():
            return None
        try:
            return self.context.new_page()
        except Exception:
            self._close()
            return None

    @property
    def connected(self):
        return self._connected

    # ================================================================
    # 公开接口
    # ================================================================

    def search(self, query, limit=10):
        """搜索小红书笔记"""
        if not self._ensure_page():
            return []
        page = self._ensure_page()
        if not page:
            return []

        results = []
        try:
            search_url = f"https://www.xiaohongshu.com/search_result?keyword={_urlencode(query)}&source=web_search_result_notes"
            page.goto(search_url, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # 等待笔记列表渲染
            try:
                page.wait_for_selector(".feeds_page, .note-item, section.note-item", timeout=10000)
            except Exception:
                pass

            # 滚动加载更多
            for _ in range(min(3, limit // 4 + 1)):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.5)

            # 提取笔记列表 —— 尝试多种选择器
            items = []
            for selector in [
                "a[href*='/explore/']",       # 链接选择器
                ".note-item a",                # 通用类选择器
                "section.note-item",           # 通用类选择器
            ]:
                items = page.query_selector_all(selector)
                if items and len(items) > 1:
                    break

            if not items:
                # 回退：从页面 HTML 中正则提取 note ID
                html = page.content()
                note_ids = re.findall(r'/explore/([a-f0-9]{24})', html)
                seen = set()
                for nid in note_ids:
                    if nid not in seen:
                        seen.add(nid)
                        url = f"https://www.xiaohongshu.com/explore/{nid}"
                        results.append({"url": url, "note_id": nid})
                        if len(results) >= limit:
                            break
            else:
                seen_urls = set()
                for item in items:
                    try:
                        href = item.get_attribute("href") or ""
                        if "/explore/" in href:
                            url = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}"
                            if url not in seen_urls:
                                seen_urls.add(url)
                                results.append({"url": url})
                                if len(results) >= limit:
                                    break
                    except Exception:
                        continue

            # 补充笔记标题、作者、点赞数等元信息
            for note in results:
                try:
                    info = self._extract_note_meta(page, note["url"])
                    if info:
                        note.update(info)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"小红书搜索失败: {e}")
        finally:
            page.close()

        return results[:limit]

    def get_comments(self, note_url, limit=20):
        """获取笔记评论"""
        if not self._ensure_page():
            return []

        comments = []
        page = None
        try:
            page = self.context.new_page()
            page.goto(note_url, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # 滚动以加载评论
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)

            # 提取评论
            html = page.content()

            # 尝试从 JSON 数据中提取评论
            # 小红书页面通常会在 window.__INITIAL_STATE__ 中包含评论数据
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # 递归查找评论列表
                    comments = self._extract_comments_from_state(data, limit)
                except (json.JSONDecodeError, Exception):
                    pass

            if not comments:
                # 回退：从 DOM 中提取评论
                comment_els = page.query_selector_all(".comment-item, .note-comment, [class*='comment']")
                for el in comment_els[:limit]:
                    try:
                        text = el.inner_text()[:200]
                        if text and len(text) > 5:
                            comments.append({"text": text})
                    except Exception:
                        continue

        except Exception as e:
            logger.warning(f"获取评论失败: {e}")
        finally:
            if page:
                page.close()

        return comments[:limit]

    def read_note_content(self, note_url):
        """精读笔记内容"""
        if not self._ensure_page():
            return {"url": note_url, "content": ""}

        page = None
        try:
            page = self.context.new_page()
            page.goto(note_url, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # 提取正文
            html = page.content()

            # 从 INITIAL_STATE 提取
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
            content_text = ""
            title = ""

            if match:
                try:
                    data = json.loads(match.group(1))
                    # 尝试常见的数据路径
                    note_data = (
                        data.get("note", {}) or
                        data.get("noteDetail", {}) or
                        data.get("noteCard", {}) or
                        {}
                    )
                    title = note_data.get("title", note_data.get("displayTitle", ""))
                    content_text = note_data.get("desc", note_data.get("description", ""))
                except Exception:
                    pass

            if not content_text:
                # 从 DOM 提取
                desc_el = page.query_selector(".note-scroller, .note-content, [class*='desc']")
                if desc_el:
                    content_text = desc_el.inner_text()[:2000]

            return {
                "url": note_url,
                "title": title,
                "content": content_text[:2000],
            }

        except Exception as e:
            logger.warning(f"精读笔记失败: {e}")
            return {"url": note_url, "content": f"[读取失败: {e}]"}
        finally:
            if page:
                page.close()

    # ================================================================
    # 内部方法
    # ================================================================

    def _extract_note_meta(self, page, note_url):
        """从笔记页面提取元信息（标题、作者、点赞数）"""
        try:
            # 打开笔记页面
            np = self.context.new_page()
            np.goto(note_url, wait_until="networkidle", timeout=15000)
            time.sleep(1.5)

            html = np.content()
            info = {"url": note_url}

            # 从 INITIAL_STATE 提取
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    note_data = (
                        data.get("note", {}) or
                        data.get("noteDetail", {}) or
                        data.get("noteCard", {}) or
                        {}
                    )
                    info["title"] = note_data.get("title", note_data.get("displayTitle", ""))
                    info["author"] = note_data.get("user", {}).get("nickname", "")
                    info["likes"] = note_data.get("interactInfo", {}).get("likedCount", "0")
                except Exception:
                    pass

            np.close()
            return info
        except Exception:
            return None

    def _extract_comments_from_state(self, data, limit):
        """从 __INITIAL_STATE__ JSON 中递归提取评论"""
        comments = []

        def _walk(obj, depth=0):
            if depth > 5:
                return
            if isinstance(obj, dict):
                # 如果有一个包含 text、author、likes 且以 comment 为键的条目
                if "text" in obj and "author" in obj:
                    comments.append({
                        "author": obj.get("author", ""),
                        "text": obj.get("text", ""),
                        "likes": obj.get("likes", 0),
                    })
                for v in obj.values():
                    _walk(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item, depth + 1)

        _walk(data)
        return comments[:limit]

    def save_login_state(self):
        """保存当前登录态（需要用户手动登录后调用）"""
        if not self.context:
            return False
        try:
            self.context.storage_state(path=self.storage_file)
            logger.info(f"登录态已保存至 {self.storage_file}")
            return True
        except Exception as e:
            logger.warning(f"保存登录态失败: {e}")
            return False

    def interactive_login(self):
        """交互式登录：打开浏览器让用户手动登录"""
        if not self._launch():
            return False
        # 关闭无头模式重新启动
        self._close()
        try:
            self._pw = sync_playwright().start()
            self.browser = self._pw.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self.context = self.browser.new_context(
                viewport={"width": 1440, "height": 900},
            )
            self.context.add_init_script(STEALTH_JS)
            page = self.context.new_page()
            page.goto("https://www.xiaohongshu.com", wait_until="networkidle", timeout=30000)
            print("\n🔑 请在打开的浏览器窗口中登录小红书")
            print("   登录完成后，按 Enter 键继续...")
            input()
            self.save_login_state()
            page.close()
            self._close()
            return True
        except Exception as e:
            logger.warning(f"交互式登录失败: {e}")
            return False


def _urlencode(s):
    """简单的 URL 编码（避免依赖 urllib）"""
    return s.replace(" ", "+").replace("&", "%26").replace("?", "%3F").replace("=", "%3D")


# ================================================================
# 快捷函数（兼容 research.py 接口）
# ================================================================

def search_xhs(query, limit=10):
    """快捷搜索"""
    client = PlaywrightXHS()
    try:
        return client.search(query, limit)
    finally:
        client._close()


def get_xhs_comments(note_url, limit=20):
    """快捷获取评论"""
    client = PlaywrightXHS()
    try:
        return client.get_comments(note_url, limit)
    finally:
        client._close()


if __name__ == "__main__":
    # 测试
    import sys
    if "--login" in sys.argv:
        client = PlaywrightXHS()
        client.interactive_login()
    else:
        notes = search_xhs("上海美食推荐", limit=3)
        print(f"搜索到 {len(notes)} 篇笔记:")
        for n in notes:
            print(f"  {n.get('title','?')[:30]} | 👍{n.get('likes','?')} | {n.get('url','')}")
