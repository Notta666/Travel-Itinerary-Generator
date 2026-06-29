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
| 🎯 **自然语言输入** | `--goal "浙江周末自驾"`，LLM 自动解析为结构化参数 |
| ⚡ **3倍并发提速** | 地理编码、距离矩阵、报告建议与图片获取均已**多线程并行化**，运行耗时缩短 3 倍！ |
| ⚙️ **Pipeline 步骤定制** | Web 端支持勾选/取消非核心步骤（如跳过小红书调研），自由在“极速生成”与“极致内容”间切换 |
| 🏨 **交互酒店选择** | 图文手册中支持手动勾选切换酒店，卡片自动更新，地图路线同步实时更新与连线 |
| 🛑 **优雅中断保护** | 运行过程中按 `Ctrl+C` 触发二次确认交互，避免误触丢失已生成的中间成果 |
| ⚡ **实时进度推送** | Web 端已升级为 SSE 实时推送步骤进度，告别轮询等待 |
| 🗺️ **交互式地图** | Leaflet 地图按日切换，支持景点/餐厅/住宿三图层，路线连线清晰指引 |
| 📝 **Jinja2 模板引擎** | 图文手册采用 Jinja2 模板渲染，告别 300 行 f-string 拼接噩梦 |
| 🧪 **测试覆盖** | 5 个测试文件含 40 个测试用例（goal 解析、预算、配置、API 客户端、天气） |
| 🍽️ **美食+景点一体** | 小红书双通道调研 + 高德坐标验证，对抗辩论规划路线 |
| 💰 **预算管理** | 支持总预算/日均预算两种模式，自动按天分配 |
| 🌤️ **天气预报** | 未来3天高德实时预报，超3天历史平均降级 |
| 💡 **出行建议** | 基于季节/目的地/偏好的专业建议（漂流/登山/穿搭打卡/亲子等） |
| 🖼️ **自动配图** | 高德→360图片→百度/Bing 四级图片降级，7天缓存 |
| 🌙 **深色/浅色主题** | 一键切换，打印适配 |
| 📱 **单文件HTML** | 无需服务器，浏览器直接打开，手机友好 |

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 高德开放平台 Web 服务 API Key（[免费申请](https://lbs.amap.com/)）
- DeepSeek API Key（[官网获取](https://platform.deepseek.com/)）
- （可选）Chrome + OpenCLI 扩展 → 小红书调研增强

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

### Web App (FastAPI 网页端)

提供 FastAPI 网页界面，提供可视化交互与步骤定制，支持浏览器提交任务：

```bash
# 启动 Web App 服务器
python webapp/main.py
```

访问 `http://localhost:8080`，即可：
1. **定制可选生成步骤**：勾选/取消小红书调研、POI地址丰富、驾车距离矩阵和出行建议，自由权衡速度与内容。
2. **查看内置使用说明**：页面底部提供详尽的使用说明与指引，方便新用户快速上手。
3. **查看与下载离线攻略**：任务提交后，提供后台异步进度条，完成后网页端直接预览交互手册，并支持一键下载单文件 HTML 离线查看。

---

## 🏗️ 项目架构

```
Travel-Itinerary-Generator/
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
│   ├── research.py            # 小红书调研工具（OpenCLI 搜索+精读）
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
| 景点/美食 | 小红书（搜索+精读） | 🥇 主数据源 |
| POI坐标验证 | 高德地图 API | 🥈 辅助验证 |
| 酒店 | 高德周边搜索 | 🥈 |
| 天气 | 高德天气 API | 🥈 |
| 图片 | 高德→360图片→百度/Bing | 🥉 降级检索 |
| 路线规划 | DeepSeek API | 决策引擎 |

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

## ⚠️ 注意事项

1. **API Key 安全**：`.env` 文件已加入 `.gitignore`，切勿提交真实 Key（含硬编码 Key 的提交会立即暴露）
2. **高德 API 限额**：个人开发者每日约 5000 次调用，个人使用足够
3. **DeepSeek API 费用**：deepseek-chat 模型价格低廉，单次攻略约 ¥0.1-0.3
4. **小红书调研**：需 Chrome 浏览器 + OpenCLI 扩展，断连时自动重连；如不可用则降级为手动POI模式
5. **POI重名与跨城偏差问题**：如"江南天池"可能定位到广西，代码已有城市偏差检测+V5搜索兜底。在多城市行程中，系统能够通过 LLM 自动将景点和美食映射归入其所属具体城市限制下地理编码，防止如“顺德清晖园”匹配到广州同名或类似商户。
6. **图片获取**：高德图片为空时自动降级到百度/Bing搜索，7天文件缓存

---

## 🙏 致谢与引用

### 致敬项目

- [**hiyeshu/trip-map-builder**](https://github.com/hiyeshu/trip-map-builder) — 三阶段旅行规划工作流（规划→调研→地图），本项目的小红书调研和单文件HTML模板理念深受其启发
- [**Hatari130/map-creator**](https://github.com/Hatari130/map-creator) — 结合 GIS+GPT 的城市打卡地图生成器，启发了本项目的海报风格手册和图片获取方案
- [**Drfccv/AI-Trip-Planner**](https://github.com/Drfccv/AI-Trip-Planner) — 基于 LLM+高德 API 的旅行规划器，验证了技术路线的可行性
- [**Panniantong/agent-reach**](https://github.com/Panniantong/agent-reach) — AI Agent 互联网渠道工具，提供小红书/B站/Reddit 等调研能力
- [**jackwener/OpenCLI**](https://github.com/jackwener/OpenCLI) — 浏览器桥接工具，支撑小红书内容采集

### 技术依赖

- [高德开放平台 Web 服务 API](https://lbs.amap.com/) — POI 搜索、地理编码、路径规划、静态地图、天气查询
- [DeepSeek API](https://platform.deepseek.com/) — 对抗性辩论路线规划、出行建议生成
- [Leaflet.js](https://leafletjs.com/) — 开源交互式地图库
- [OpenStreetMap](https://www.openstreetmap.org/) — 免费地图数据
- [FastAPI](https://fastapi.tiangolo.com/) — Web 应用框架

### 参考理念

- **对抗性辩论模式** — 受投资领域"多空辩论"方法论启发，用于旅行路线规划的多视角融合
- **工程控制论** — 受 Wiener 控制论启发，项目中 Pipeline 的前馈加载、积分控制、自监控闭环等设计模式
- **Glassmorphism 设计语言** — 受 Apple Design System 和 Glassmorphism 设计趋势影响
- **单文件 HTML 分发** — 受 trip-map-builder 和 singlefile 项目影响，零依赖部署

---

## 📄 License

MIT License — 详见 [LICENSE](LICENSE) 文件

---

## 🤝 贡献

欢迎 Issue 和 PR！详见 [CONTRIBUTING.md](CONTRIBUTING.md)
