# Changelog

All notable changes to this project will be documented in this file.

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
