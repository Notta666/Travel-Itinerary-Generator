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
| 🗺️ **交互式地图** | Leaflet 地图按日切换，支持景点/餐厅/住宿三图层 |
| 🍽️ **美食+景点一体** | 小红书双通道调研 + 高德坐标验证，对抗辩论规划路线 |
| 🏨 **住宿推荐** | 按每日路线自动搜索附近高评分酒店，地图独立标签切换 |
| 💰 **预算管理** | 支持总预算/日均预算两种模式，自动按天分配 |
| 🌤️ **天气预报** | 未来3天高德实时预报，超3天历史平均降级 |
| 💡 **出行建议** | 基于季节/目的地/偏好的专业建议（漂流/登山/亲子等） |
| 🖼️ **自动配图** | 高德→百度→Bing 三级图片降级，7天缓存 |
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

### Web App（可选）

提供 FastAPI 网页界面，支持浏览器提交任务：

```bash
python -m uvicorn webapp.main:app --host 0.0.0.0 --port 8080
```

访问 `http://localhost:8080`，输入自然语言即可一键生成攻略。支持异步后台执行、进度轮询、结果预览与下载。

---

## 🏗️ 项目架构

```
Travel-Itinerary-Generator/
├── pipeline/
│   └── run_pipeline.py    # 10步工序链入口（--goal 自然语言解析）
├── utils/
│   ├── amap_api.py        # 高德地图API封装（地理编码/POI搜索/路径规划）
│   ├── brochure.py        # 图文手册生成器（封面/地图/酒店/预算/天气）
│   ├── llm.py             # DeepSeek API 调用封装
│   ├── research.py        # 小红书调研工具（OpenCLI 搜索+精读）
│   ├── tips.py            # 出行建议生成器（通用/偏好/每日/应急）
│   ├── weather.py         # 高德天气查询（实况+预报+历史平均降级）
│   ├── image_fetcher.py   # 多引擎图片获取（高德→百度→Bing，7天缓存）
│   ├── user_prefs.py      # 用户偏好记忆系统（自动学习常去城市/交通/预算）
│   └── planner.py         # 对抗辩论规划器（备用独立入口）
├── webapp/
│   └── main.py            # FastAPI 网页应用（异步后台任务）
├── data/
│   └── references/        # POI码表、城市编码表、设计文档
├── outputs/               # 生成产物
└── web/
    └── template.html      # 独立地图模板
```

### Pipeline 工序链

```
用户输入
  → Step 0  Goal解析（DeepSeek自然语言→结构化参数）
  → Step 1  初始化参数 + 加载用户偏好
  → Step 2  小红书调研（景点+美食双通道，搜索+精读Top5）
  → Step 3  POI地理编码（高德API）
  → Step 4  POI丰富 + 美食对接（小红书数据直用，高德坐标验证）
  → Step 5  距离矩阵（高德驾车路线规划）
  → Step 6  对抗性辩论路线规划（DeepSeek Bull/Bear/Fusion）
  → Step 7  （合并至Step 9）
  → Step 8  攻略报告生成
  → Step 8.5 出行建议 + 天气预报（DeepSeek+高德天气）
  → Step 9  图文手册生成 → 输出封面/地图/酒店/预算/天气/出行建议
```

---

## 🌐 数据源说明

| 数据 | 来源 | 优先级 |
|:---|:---|:---:|
| 景点/美食 | 小红书（搜索+精读） | 🥇 主数据源 |
| POI坐标验证 | 高德地图 API | 🥈 辅助验证 |
| 酒店 | 高德周边搜索 | 🥈 |
| 天气 | 高德天气 API | 🥈 |
| 图片 | 高德→百度→Bing | 🥉 三级降级 |
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
5. **POI重名问题**：如"江南天池"可能定位到广西，代码已有城市偏差检测+V5搜索兜底
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
