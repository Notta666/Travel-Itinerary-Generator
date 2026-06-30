# Changelog

All notable changes to this project will be documented in this file.

## [2.0.1] - 2026-06-30
### Fixed
- **Web App crash in background threads**: `run_pipeline()` called `signal.signal()` in non-main threads when running via the FastAPI web app (`webapp/main.py`), crashing with `ValueError: signal only works in main thread`. This affected all web app users (e.g. Xiaohongshu visitors) who triggered a generation. Signal registration/restoration is now guarded by `threading.current_thread() is threading.main_thread()`, so Ctrl+C handling works in CLI mode while web app background threads run safely.

### Changed
- `pipeline/run_pipeline.py`: `signal.signal()` calls (lines 704-706, 808) wrapped with main-thread guard; `original_handler` defaults to `None` and only restored when previously captured.

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
