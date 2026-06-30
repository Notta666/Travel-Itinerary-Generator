# Changelog

All notable changes to this project will be documented in this file.

## [2.0.1] - 2026-06-30
### Fixed
- **Web App crash in background threads**: `run_pipeline()` called `signal.signal()` in non-main threads when running via the FastAPI web app (`webapp/main.py`), crashing with `ValueError: signal only works in main thread`. This affected all web app users (e.g. Xiaohongshu visitors) who triggered a generation. Signal registration/restoration is now guarded by `threading.current_thread() is threading.main_thread()`, so Ctrl+C handling works in CLI mode while web app background threads run safely.

### Changed
- `pipeline/run_pipeline.py`: `signal.signal()` calls (lines 704-706, 808) wrapped with main-thread guard; `original_handler` defaults to `None` and only restored when previously captured.

## [2.2.0] - 2026-06-30
### Added
- **Playwright 小红书引擎**：新建 `utils/playwright_xhs.py` 模块，基于 Playwright + Chromium 替代 OpenCLI。`utils/research.py` 重构为双引擎策略（Playwright 首选 → OpenCLI 降级），开机自检自动切换
- **交互式登录工具**：`playwright_xhs.py --login` 打开浏览器窗口让用户手动登录小红书，登录态保存至 `data/xhs_storage.json` 复用

### Changed
- `utils/research.py`：`XiaoHongShu` 类重构，Playwright 作为主引擎，OpenCLI 保留为降级方案
- `requirements.txt`：新增 `playwright>=1.40.0`

## [2.1.2] - 2026-06-30
### Fixed
- **DeepSeek JSON 被截断**：7 天以上行程输出 JSON 超过 max_tokens 被截断，解析失败后降级到规则引擎生成通用垃圾行程。Bull/Bear 提至 6000、Fusion 提至 8000（拉满 DeepSeek 上限）
- **预算输入框歧义**：placeholder 写"默认按 1500/人/天计算"让人误解为日预算，实际是总预算。改为"填写总预算，如 5000（留空按 1500/人/天估算）"

### Changed
- `pipeline/steps/planner.py`：max_tokens Bull/Bear 4000→6000，Fusion 6000→8000

## [2.1.1] - 2026-06-30
### Fixed
- **图片出图率低**：`_fetch_photos()` 全局 `_last_fetch_time` 无锁竞争导致多线程并发时限流失效，部分请求被限流返回空。新增 `threading.Lock` 保护限流状态，Web 搜索引擎额外加 0.15s 间隔避免触发风控
- **Gaode 图片被 HTTPS 转换搞崩**：高德图片服务器 `store.is.autonavi.com` 不支持 HTTPS，强制转换后全挂。改为仅非高德来源的 HTTP 才转 HTTPS
- **WebApp 按钮交互不生效**：旧服务进程一直运行未重启，静态文件被浏览器缓存。新增 `?v=2.1.1` 缓存爆破参数，修复重置时未清理 `boxShadow` 和 `cancel-state` CSS 类的问题
- **Footer 版本号**：`v1.2.0` → `v2.1.0`

### Changed
- `utils/brochure/__init__.py`：`_fetch_photos()` 增加线程锁 + HTTPS 智能转换 + 双层降级（省份精确→city+name 兜底）
- `webapp/static/app.js`：修复 `resetButton()` 未清理样式残留
- `webapp/static/style.css`：新增 `.cancel-state` 样式
- `webapp/templates/index.html`：静态文件加 `v=2.1.1` 缓存参数

## [2.1.0] - 2026-06-30
### Added
- **规划行程按钮二次点击可取消**：任务运行中按钮变红"⏹️ 取消规划"，再次点击调用 `POST /cancel/{task_id}` 中断 pipeline，每个步骤前检查取消标记（`CancelledError`），清理取消标记后优雅退出
- **图片搜索增加省份上下文**：新增 `_CITY_PROVINCE` 映射（71 城），`_get_search_query()` 构建 `省份+城市+名称` 搜索词。景点搜索如 `上海市上海外滩`、`浙江省杭州西湖`；美食追加 ` 美食` 后缀如 `广东省广州陶陶居 美食`
- **端到端测试**：`tests/test_amap_client.py` 新增限流/重试测试

### Fixed
- **WebApp 500 Internal Server Error**：`TemplateResponse(request, name, context)` 签名调用修复（Starlette 1.0.1 + Jinja2 3.1.6 兼容性），之前错误地传入了 `(name, context)` 导致 Jinja2 cache_key 拿到 dict 报 `TypeError: unhashable type: 'dict'`
- **`signal.signal()` 在后台线程中调用崩溃**：移至主线程初始化

### Changed
- `utils/image_fetcher.py` — `get_photos()` 新增 `category` 参数，高德用 `city+name`，Web 引擎用 `province+city+name`
- `utils/brochure/__init__.py` — `_fetch_photos()` 和 `_fetch_photos_batch()` 支持 3-tuple `(name, city, category)`，区分景点/美食搜图策略
- `webapp/static/app.js` — 全面重写任务状态管理，新增 `currentTaskId` / `cancelCurrentTask()` / `resetButton()`

## [2.0.0] - 2026-06-29
### Added
- **Pipeline modularization**: `step_2_research()` and `step_6_plan_itinerary()` extracted to `pipeline/steps/research.py` and `pipeline/steps/planner.py`
- **Unified API Key management**: `utils/config.py` centralizes all API key loading, eliminating 5 duplicate implementations across the codebase
- **LLMClient multi-provider abstraction**: `utils/llm.py` now supports provider abstraction with `LLMClient` class (DeepSeek backend), preserving `call_deepseek()` backward compatibility
- **Jinja2 template engine**: Brochure HTML generation migrated from 300-line f-string concatenation to `utils/brochure/templates/brochure.html` Jinja2 template
- **Frontend externalization**: `webapp/main.py` reduced from ~1080 to 351 lines — HTML/CSS/JS extracted to `webapp/templates/index.html`, `webapp/static/style.css`, `webapp/static/app.js`
- **Server-Sent Events (SSE)**: Webapp replaced 3-second polling with real-time `EventSource` streaming via FastAPI `StreamingResponse`
- **SQLite task persistence**: Webapp tasks persisted to `data/tasks.db` instead of in-memory dict (survives restart)
- **Progress callback mechanism**: `run_pipeline()` accepts `progress_callback(step, message, pct)` for real-time step tracking
- **LLM call retry**: `call_deepseek()` now has exponential backoff retry (max 3 attempts, 1s/2s/4s) for network/rate-limit failures
- **User preference learning**: `update_from_goal()` and `get_suggestions()` now active in `step_1_init()`
- **Test suite**: 5 test files with 40 tests covering goal parser, budget parser, config loader, AMap client (mocked), and weather
- **Dynamic lodging instruction**: Replaced hardcoded 5-day Guangzhou itinerary with `_build_lodging_instruction(context)` that adapts to any city/days/start_date
- **Dynamic season description**: Hardcoded "6月底夏季" replaced with `_season()` from `tips.py`
- **Dynamic city centers**: `city_centers` dict replaced with runtime geocoding via AMap API
- **`data/tasks.db`** added to `.gitignore`

### Changed
- `run_pipeline.py` reduced from 1408 to 954 lines (-32%) via steps extraction
- `webapp/main.py` reduced from 1083 to 351 lines (-68%) via frontend externalization
- `brochure.py` converted from single file to `utils/brochure/` package (`__init__.py` + `renderer.py` + Jinja2 template)
- Image fetch parallelism: `_fetch_photos_batch()` `max_workers` 2→4
- Fusion prompt now uses summarized Bull/Bear data instead of full JSON injection (reduced token usage)
- All 15 bare `except:` blocks replaced with specific exception types (`Exception`, `OSError`, `json.JSONDecodeError`)
- All 11 function-body imports moved to module level
- `requirements.txt` now declares `fastapi>=0.100.0`, `uvicorn>=0.23.0`, `jinja2>=3.0.0`

### Removed
- `utils/planner.py` — dead code (fully replaced by Step 6 in run_pipeline.py)
- `web/template.html` — unused template
- `utils/brochure.py` — replaced by `utils/brochure/` package
- `data/cache/_qq_deliver.py` — one-off script, not part of project
- `data/MEMORY.md` — placeholder, no code references
- `step_7_render_html()` — no-op function
- `TEMPLATE_PATH`, `DATA_DIR`, `OUTPUTS_DIR` globals — refactored to local scope

## [1.2.1] - 2026-06-29
### Fixed
- Cross-city geocoding drift and image mismatch in multi-city itineraries (e.g. Shunde Qinghui Garden matching to Guangzhou Asia International Hotel, Zhuhai Qinglulu matching to Guangzhou Love Hotel).

### Added
- Specific city extraction in Step 2 (XHS extraction) for both sights and foods.
- Fast LLM city classification fallback in Step 3 (sights) and Step 4 (foods) for manual or default POIs to automatically map names to their destination cities before geocoding.

### Changed
- Step 3 and Step 4 geocoding logic to prioritize and restrict search boundaries to the exact target cities.

## [1.2.0] - 2026-06-29
### Added
- 360 Image Search (`image.so.com` JSON API) integration as primary fallback in `utils/image_fetcher.py` for highly robust landmark/restaurant images.
- Precise hotel selection logic: daily `accommodation_city` property in itinerary with coordinate filtering (45km radius) to avoid cross-city drift during transit days.
- City-scoped geocoding: each activity slot has a specific city designation, prefixing queries (e.g. "珠海金悦轩...") to prevent drift in border regions (e.g., Macau vs. Zhuhai).

### Changed
- Refactored brochure builder and budget calculator to fully support dynamic `people_count` and total daily budget calculations (removed hardcoded `2` factor).
- Enhanced fallback image cache to degrade gracefully using randomized beautiful CSS gradients when all image search engines fail.

## [1.1.0] - 2026-06-28
### Added
- Web App (`webapp/main.py`): FastAPI web interface with Y2K-style UI, async task execution
- `utils/weather.py`: Gaode weather API with real-time forecast and historical fallback
- `utils/image_fetcher.py`: Multi-engine image fetching (Gaode→Baidu→Bing) with 7-day cache
- `utils/user_prefs.py`: User preference memory system (auto-learn city/transport/budget)
- Interactive map hotel tab: green markers for hotel recommendations
- Mobile-responsive web app homepage with random rotating destination tags (24 locations)

### Changed
- Xiaohongshu research upgraded to dual-channel (food + attractions), now embedded as fixed Step 2
- brochure weather display fixed: now shows trip-date weather (not today's); beyond 3-day uses historical average
- Restaurant coordinate matching: list-format compatibility + 100km sanity check
- Budget parsing: "共" character triggers total budget ÷ days logic
- Geocoding disambiguation: city center deviation detection + V5 POI search fallback
- OpenCLI auto-reconnect on disconnect
- Hotel card layout: flex layout with aligned ratings/price/distance

### Security
- Removed hardcoded AMAP_KEY from `utils/image_fetcher.py` (was exposed as literal string)
- Removed hardcoded AMAP_KEY fallback from `utils/weather.py`

## [1.0.0] - 2026-06-28
### Added
- First public release of Travel-Itinerary-Generator.
- 9-step pipeline orchestration in `pipeline/run_pipeline.py`.
- Dynamic brochure HTML builder with integrated Leaflet maps in `utils/brochure.py`.
- Geocoding and places enrichment utilizing AMap (Gaode) Web Service API in `utils/amap_api.py`.
- Oppositional routing (Bull/Bear/Fusion) leveraging DeepSeek API in `utils/planner.py`.
- Tips and safety guides using LLM in `utils/tips.py`.
- OpenCLI小红书 crawler wrapper in `utils/research.py`.
- `.env.example`, `LICENSE`, `CONTRIBUTING.md`, and `requirements.txt` for open source readiness.

### Changed
- Refactored AMap API client and brochure builder to dynamically load API keys from environment/`.env` files instead of hardcoding them.
- Updated DeepSeek loading methods to secure project scope configurations.
- Sanitized filenames and terminal query inputs to mitigate path traversal and command injection threats.
- Added a robust rule-based planner fallback in Step 6 to handle API timeouts/network failures gracefully.
