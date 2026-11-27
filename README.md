# 🗺️ Travel-Itinerary-Generator

> AI 驱动的智能旅行攻略生成器 — 输入目的地，自动产出图文并茂的交互式旅游手册

---

## 🎯 项目定位

一句话说出你的旅行想法，剩下的交给 AI：

```bash
python pipeline/run_pipeline.py --goal "浙江周末自驾漂流"
python pipeline/run_pipeline.py --goal "想去看海"
python pipeline/run_pipeline.py --goal "带爸妈去南方"
```

自动完成：**目的地决策 → 小红书调研 → POI推荐 → 地理编码 → 美食对接 → 路线规划 → 预算分配 → 酒店推荐 → 出行建议 → 图文手册生成**

---

## ✨ 核心特性

| 特性 | 说明 |
|:---|:---|
| 🎯 **自然语言输入** | `--goal \"浙江周末自驾"`，LLM 自动解析为结构化参数 |
| ⚡ **3倍并发提速** | 地理编码、距离矩阵、报告建议与图片获取均已多线程并行化，运行耗时缩短 3 倍 |
| 🏙️ **多城市串联** | 省份+≥5天行程自动规划多城市路线，如浙江10日→杭州+绍兴+宁波+乌镇+千岛湖 |
| ✈️ **飞猪实时预订** | 一键预订总览模块，展示高铁车次/航班号/酒店/门票详情及直达飞猪预订链接 |
| 🚗 **交通智能决策** | 基于高德实际驾车距离+实时票价+预算，LLM 综合推荐高铁/飞机/自驾 |
| 🍽️ **避雷过滤** | 小红书评论+全网口碑双重过滤，标记"全网黑"级游客陷阱并一票否决 |
| 🏨 **交互酒店选择** | 图文手册中支持手动勾选切换酒店，卡片自动更新，地图路线同步实时更新与连线 |
| 🗺️ **交互式地图** | Leaflet 地图按日切换，支持景点/餐厅/住宿三图层，路线连线清晰指引 |
| 🖼️ **自动配图** | 高德→360图片→百度/Bing 四级图片降级，7天缓存 |
| 🌙 **深色/浅色主题** | 一键切换，打印适配 |
| 📱 **单文件HTML** | 无需服务器，浏览器直接打开，手机友好 |

---

## 🚀 快速开始

### 环境要求

- Python 3.13（CI 与 Docker 同版本）
- 高德开放平台 Web 服务 API Key（[免费申请](https://lbs.amap.com/)）
- DeepSeek API Key（[官网获取](https://platform.deepseek.com/)）
- （如需小红书调研功能）Chrome 浏览器 + OpenCLI 扩展（[安装指南](https://github.com/jackwener/OpenCLI)）

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/Notta666/Travel-Itinerary-Generator.git
cd Travel-Itinerary-Generator

# 2. 安装依赖
python -m pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env 填入你的 Key：
#   DEEPSEEK_API_KEY=sk-your-key
#   AMAP_KEY=your-gaode-key
```

### 使用

```bash
# 最简模式 — 告诉 AI 你想去哪
python pipeline/run_pipeline.py --goal "浙江周末自驾"

# 精确模式 — 手动指定参数
python pipeline/run_pipeline.py --city 安吉 --days 2 --pois "大竹海,云上草原"

# 混合模式 — goal 解析 + 参数覆盖
python pipeline/run_pipeline.py --goal "出去玩" --city 杭州 --days 3
```

### 产出文件

执行后在 `outputs/` 目录得到：

| 文件 | 格式 | 说明 |
|:---|:---|:---|
| `{城市}_brochure_xxx.html` | **单文件HTML** | 图文手册（封面+每日行程+出行建议+天气预报+酒店推荐+交互地图） |
| `{城市}_travel_xxx.md` | Markdown | 纯文本攻略报告 |

### 导出：日历 / GPX / KML / PDF

每次生成会在手册同目录额外输出 `{城市}_brochure_xxx.ics`、`.gpx`、`.kml`（手册顶部也有对应按钮；Web 端经 `/download/{task_id}/{ics|gpx|kml}` 下载）：

| 格式 | 内容 | 导入方法 |
|:---|:---|:---|
| `.ics` | 每个景点/餐厅一个日历事件（有钟点为定时事件，时区 Asia/Shanghai；否则全天事件），含交通、备注、价格及来源 | **Google 日历**：设置 → 导入和导出 → 导入，选择 `.ics` 并选目标日历；**Apple 日历**：双击 `.ics` 或 文件 → 导入，选择目标日历 |
| `.gpx` | 每天一条路线（`<rte>`），按游览顺序排列的途经点 | **奥维互动地图 / 两步路**：导入轨迹/路线文件选 `.gpx`；其它支持 GPX 1.1 的 App 同理 |
| `.kml` | 每天一个文件夹，含地点标记与当天连线 | **Google My Maps**：新建地图 → 导入，选择 `.kml`；奥维、两步路也支持 KML |
| PDF | 手册页点击“打印 / 存为 PDF”（浏览器打印对话框选“另存为 PDF”），已内置打印样式 | —— |

注意：没有坐标的地点不会进入 GPX/KML（文件中注明被跳过数量）；坐标为高德 GCJ-02 坐标系，直接叠加到 WGS-84 底图（如 Google 地图）可能有数百米偏移，国内地图 App 内无此问题。

### Web App (FastAPI 网页端)

提供 FastAPI 网页界面，提供可视化交互与步骤定制，支持浏览器提交任务：

```bash
# 启动 Web App 服务器（两种方式等价）
python webapp/main.py
# 或从项目根目录经 ASGI 入口启动：
# uvicorn main:app --host 127.0.0.1 --port 8080
```

访问 `http://localhost:8080`，即可：
1. **定制可选生成步骤**：勾选/取消小红书调研、POI地址丰富、驾车距离矩阵和出行建议，自由权衡速度与内容。
2. **查看内置使用说明**：页面底部提供详尽的使用说明与指引，方便新用户快速上手。
3. **查看与下载离线攻略**：任务提交后，提供后台异步进度条，完成后网页端直接预览交互手册，并支持一键下载单文件 HTML 离线查看。

> 服务网络与安全：WebApp 默认监听 `0.0.0.0:8080`（可通过环境变量 `HOST` / `PORT` 配置，如 `HOST=127.0.0.1` 仅本机访问）。公网部署时可通过设置 `API_TOKEN` 环境变量启用鉴权保护，系统同时内置了 per-IP 速率限制（默认 10 次/分钟）。跨域访问受 CORS 策略保护（开发模式需同时设置 `CORS_ORIGINS=*` 与 `CORS_ALLOW_ALL=1`）。

### Docker 运行

```bash
cp .env.example .env          # 填入 DEEPSEEK_API_KEY / AMAP_KEY（.env 不会被打入镜像）
docker compose up -d --build  # 构建并后台启动
# 访问 http://127.0.0.1:8000
docker compose logs -f app    # 查看日志
docker compose down           # 停止
```

- 容器内监听 `0.0.0.0:8000`，宿主机默认仅绑定 `127.0.0.1`（如需局域网访问请自行修改 `docker-compose.yml` 的端口映射，并务必配置 `API_TOKEN`）。
- `./data` 与 `./outputs` 以卷挂载，任务数据库与生成产物保存在宿主机；健康检查为 `GET /health`。
- 容器以非 root 用户（uid 1000）运行；Linux 下请确保挂载目录对该用户可写。

### 日志

通过环境变量 `LOG_FORMAT` 切换日志格式（`pipeline/` 与 `webapp/` 统一使用 `utils/log.py`）：

| 取值 | 说明 |
|:---|:---|
| `text`（默认） | 仅输出消息本体，保持原 CLI 观感 |
| `json` | 每行一条 JSON：`ts, level, logger, msg, task_id, step, elapsed_ms`，便于收集与检索 |

可选 `LOG_LEVEL`（默认 `INFO`）。示例：`LOG_FORMAT=json python webapp/main.py`。

### 测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -q   # 183 项测试，覆盖 Goal 解析/预算/地理编码/手册模板完整性等
```

---

## 🏗️ 项目架构

```
projects/travel-itinerary-generator/
├── pipeline/
│   ├── run_pipeline.py        # 工序链入口（--goal 自然语言解析）
│   └── steps/
│       ├── research.py        # Step 2: 小红书调研（已提取模块化）
│       └── planner.py         # Step 6: 对抗辩论路线规划（已提取模块化）
├── utils/
│   ├── amap_api.py            # 高德地图API封装（地理编码/POI搜索/路径规划）
│   ├── brochure/              # 图文手册生成器
│   │   ├── __init__.py        #   generate_brochure() 入口
│   │   ├── renderer.py        #   Jinja2 模板渲染
│   │   └── templates/         #   brochure.html 模板
│   ├── config.py              # 统一 API Key 管理
│   ├── llm.py                 # LLMClient 多后端抽象（DeepSeek + 占位）
│   ├── research.py            # 小红书调研工具（OpenCLI → LLM 降级）
│   ├── tips.py                # 出行建议生成器
│   ├── weather.py             # 高德天气查询
│   ├── image_fetcher.py       # 多引擎图片获取（高德→360→百度→Bing）
│   ├── user_prefs.py          # 用户偏好记忆系统
├── webapp/
│   ├── main.py                # FastAPI 网页应用（SSE + SQLite 持久化）
│   ├── templates/index.html   # 前端模板（独立于后端）
│   └── static/
│       ├── style.css          # 独立样式表
│       └── app.js             # 独立前端逻辑
├── tests/
│   ├── test_goal_parser.py    # 目标解析测试
│   ├── test_budget_parser.py  # 预算解析测试
│   ├── test_config.py         # 配置加载测试
│   ├── test_amap_client.py    # AMap 客户端测试（Mock HTTP）
│   └── test_weather.py        # 天气模块测试
├── data/
│   └── references/            # POI码表、城市编码表
└── outputs/                   # 生成产物
```

### Pipeline 工序链
```
用户输入
  → Step 0  [核心] Goal解析（DeepSeek自然语言→结构化参数）
  → Step 1  [核心] 初始化参数 + 加载用户偏好
  → Step 2  [可选] 小红书调研（景点+美食双通道，搜索+精读Top5）
  → Step 3  [核心] POI地理编码（高德API批量并行）
  → Step 4  [可选] POI丰富 + 美食对接（高德逆地理编码与美食验证）
  → Step 5  [可选] 距离矩阵（高德驾车路线规划批量并行）
  → Step 6  [核心] 对抗性辩论路线规划（DeepSeek Bull/Bear/Fusion）
  → Step 7  （已合并至Step 9）
  → Step 8  [核心] 攻略报告生成 (Markdown)
  → Step 8.5 [可选] 出行建议 + 天气预报（DeepSeek+高德天气）
  → Step 9  [核心] 图文手册生成 → 整合封面/地图/酒店/预算/天气/出行建议 (HTML)
```

> [!NOTE]
> 非核心的 **[可选]** 步骤均可在 Web App 页面前端自由勾选控制是否生效，或在调用 `run_pipeline(..., prefs={"enabled_steps": [...]})` 时通过列表配置传入。禁用可选步骤将大幅缩短生成时间，提供更快的降级响应。

---

## 🌐 数据源说明

| 数据 | 来源 | 优先级 |
|:---|:---|:---:|
| 景点/美食 | 小红书（OpenCLI 浏览器自动化 → LLM 降级） | 🥇 主数据源 |
| POI坐标验证 | 高德地图 API | 🥈 辅助验证 |
| 酒店 | 高德周边搜索 | 🥈 |
| 天气 | 高德天气 API | 🥈 |
| 图片 | 高德→360图片→百度/Bing | 🥉 降级检索 |
| 路线规划 | DeepSeek API | 决策引擎 |

---

## 🕒 数据来源与时效

手册中的价格、门票、营业时间、天气、交通时刻都可溯源：每条数据旁标注「来源 · 更新于 MM-DD HH:mm」，超过时效的数据会灰显并提示「可能已变化，出行前请核实」。手册页脚有「数据说明」小节。

| 数据 | 来源标记 | 默认时效（TTL） |
|:---|:---|:---:|
| 机票/高铁/酒店价格、景点门票 | `flyai`（飞猪 FlyAI）/ `amap`（高德兜底） | 24 小时 |
| 交通时刻 | `flyai` | 24 小时 |
| 营业时间 | `amap`（高德 `business.opentime_*`） | 30 天 |
| 天气 | `weather:amap` / `weather:open-meteo`（往年同期参考） | 6 小时 |
| 大模型生成的价格 | `llm` → 标注「AI 估算，请核实」 | 24 小时 |

- 数据结构：原字段不变，另增并行字段 `price_meta` / `cost_meta` / `opening_hours_meta` / `meta`，形如 `{"value", "source", "fetched_at", "ttl_hours"}`（见 `utils/provenance.py`）。缓存命中时 `fetched_at` 是缓存写入时间，而不是当前时间。
- POI 存在性校验：没有高德 id 的景点会按「名称+城市」二次检索；查无的景点标注「未在地图中检索到，请核实」并排到后面；检索失败（网络问题）视为未知，不降权。

---

## ⚙️ 配置说明

### 环境变量

在 `.env` 文件中配置：

```env
DEEPSEEK_API_KEY=«redacted:sk-…»
AMAP_KEY=your-gaode-api-key-here
```

高德 API Key 需要在[控制台](https://console.amap.com/)开通以下服务：
- 地理编码/逆地理编码
- 搜索 API（V5）
- 路径规划
- 静态地图
- 天气查询

### 预算规则

| 情况 | 默认值 |
|:---|:---:|
| 未指定预算 | 2人 · ¥3000/天 |
| 指定"总预算4000" + 2天 | ¥2000/天 |
| 指定"每天3000" | ¥3000/天 |
| 含"共"字（如"两人共4000"） | 识别为总预算，自动÷天数 |

---

## ⚠️ 法律声明与注意事项

### 📜 法律声明

本项目**不包含任何爬虫代码**，小红书调研功能通过用户**自行安装的 Chrome 浏览器 + OpenCLI 扩展**实现，本质上是模拟用户手动浏览公开网页的行为，数据来源于用户个人浏览会话中的公开信息。用户需自行确保使用方式符合相关平台的服务条款及当地法律法规。

### ⚠️ 注意事项

1. **API Key 安全**：`.env` 文件已加入 `.gitignore`，切勿提交真实 Key（含硬编码 Key 的提交会立即暴露）
2. **WebApp 网络与鉴权**：默认监听 `0.0.0.0:8080`（可通过 `HOST` 变量配置为 `127.0.0.1` 仅本机访问）。公网部署建议配置 `API_TOKEN` 环境变量启用 Token 鉴权保护 API 额度，且跨域仅在设置 `CORS_ORIGINS=*` 配合 `CORS_ALLOW_ALL=1` 时开启全局允许。
3. **高德 API 限额**：个人开发者每日约 5000 次调用，个人使用足够
4. **DeepSeek API 费用**：deepseek-chat 模型价格低廉，单次攻略约 ¥0.1-0.3
5. **小红书调研**：基于 OpenCLI（Chrome 浏览器扩展），模拟用户手动浏览公开笔记。首次使用需安装 Chrome 扩展。**不涉及侵入式爬虫、不绕过登录验证、不批量抓取数据**
6. **POI重名与跨城偏差问题**：如"江南天池"可能定位到广西，代码已有城市偏差检测+V5搜索兜底。在多城市行程中，系统能够通过 LLM 自动将景点和美食映射归入其所属具体城市限制下地理编码，防止如"顺德清晖园"匹配到广州同名或类似商户。
7. **图片获取**：高德图片为空时自动降级到百度/Bing搜索，7天文件缓存

---

## 🙏 致谢

### 核心依赖

- [**飞猪 FlyAI 开放平台**](https://flyai.open.fliggy.com/) — 机票/高铁/酒店/门票实时价格查询，是本项目「一键预订总览」模块的核心数据引擎，提供结构化 segments（车次号/航班号/航站楼）及跳转预订能力
- [**高德开放平台 Web 服务 API**](https://lbs.amap.com/) — POI 搜索、地理编码、路径规划、静态地图、天气查询
- [**DeepSeek API**](https://platform.deepseek.com/) — 对抗性辩论路线规划、Goal 解析、出行建议生成
- [**Leaflet.js**](https://leafletjs.com/) — 开源交互式地图库（CDN 引入）
- [**OpenStreetMap**](https://www.openstreetmap.org/) — 免费地图数据
- [**FastAPI**](https://fastapi.tiangolo.com/) — Web 应用框架
- [**jackwener/OpenCLI**](https://github.com/jackwener/OpenCLI) — 浏览器桥接工具，小红书数据采集引擎
- [**Panniantong/agent-reach**](https://github.com/Panniantong/agent-reach) — AI Agent 互联网渠道工具，提供小红书/B站/Reddit 等调研能力

---

## 📄 License

MIT License — 详见 [LICENSE](LICENSE) 文件

---

## 🤝 贡献

欢迎 Issue 和 PR！详见 [CONTRIBUTING.md](CONTRIBUTING.md)
