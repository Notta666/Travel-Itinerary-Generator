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

自动完成：**目的地决策 → POI推荐 → 地理编码 → 美食调研 → 路线规划 → 预算分配 → 酒店推荐 → 出行建议 → 图文手册生成**

---

## ✨ 核心特性

| 特性 | 说明 |
|:---|:---|
| 🎯 **自然语言输入** | `--goal "浙江周末自驾"`，LLM 自动解析为结构化参数 |
| 🗺️ **交互式地图** | Leaflet 地图按日切换，景点蓝标/餐厅橙标 |
| 🍽️ **美食+景点一体** | 高德扫街榜推荐餐厅，对抗辩论规划路线（多角度融合） |
| 🏨 **住宿推荐** | 按每日路线自动搜索附近高评分酒店 |
| 💰 **预算管理** | 默认 2 人 ¥3000/天，支持自定义总预算或日均预算 |
| 💡 **出行建议** | 基于季节/目的地/偏好的专业建议（漂流/登山/亲子等） |
| 🌙 **深色/浅色主题** | 一键切换，打印适配 |
| 📱 **单文件HTML** | 无需服务器，浏览器直接打开，手机友好 |

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 高德开放平台 Web 服务 API Key（[免费申请](https://lbs.amap.com/)）
- DeepSeek API Key（[官网获取](https://platform.deepseek.com/)）
- （可选）Chrome + OpenCLI 扩展 → 小红书调研功能

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

# 小红书调研模式（需 Chrome + OpenCLI）
python pipeline/run_pipeline.py --city 上海 --research
```

### 产出文件

执行后在 `outputs/` 目录得到：

| 文件 | 格式 | 说明 |
|:---|:---|:---|
| `{城市}_brochure_xxx.html` | **单文件HTML** | 图文手册+地图+预算+酒店+出行建议 |
| `{城市}_travel_xxx.md` | Markdown | 纯文本攻略报告 |

---

## 🏗️ 项目架构

```
Travel-Itinerary-Generator/
├── pipeline/
│   └── run_pipeline.py    # 9步工序链入口
├── utils/
│   ├── amap_api.py        # 高德地图API封装
│   ├── brochure.py        # 图文手册生成器
│   ├── llm.py             # DeepSeek API 调用
│   ├── research.py        # 小红书调研工具
│   └── tips.py            # 出行建议生成
├── data/
│   └── references/        # POI码表、城市编码表
├── outputs/               # 生成产物
└── web/
    └── template.html      # 独立地图模板
```

### Pipeline 工序链

```
用户输入 → Step 1 参数初始化
         → Step 2 小红书调研（可选）
         → Step 3 POI地理编码（高德API）
         → Step 4 POI丰富+美食调研（扫街榜）
         → Step 5 距离矩阵
         → Step 6 对抗性辩论路线规划（DeepSeek）
         → Step 7 （已合并至Step 9）
         → Step 8 攻略报告
         → Step 8.5 出行建议（DeepSeek）
         → Step 9 图文手册生成 → 交付
```

---

## ⚙️ 配置说明

### 环境变量

在 `.env` 文件中配置：

```env
DEEPSEEK_API_KEY=sk-your-key-here
AMAP_KEY=your-gaode-api-key-here
```

高德 API Key 需要在[控制台](https://console.amap.com/)开通以下服务：
- 地理编码/逆地理编码
- 搜索 API（V5）
- 路径规划
- 静态地图

### 预算规则

| 情况 | 默认值 |
|:---|:---:|
| 未指定预算 | 2人 · ¥3000/天 |
| 指定"总预算4000" + 2天 | ¥2000/天 |
| 指定"每天3000" | ¥3000/天 |

---

## ⚠️ 注意事项

1. **API Key 安全**：`.env` 文件已加入 `.gitignore`，切勿提交真实 Key
2. **高德 API 限额**：个人开发者每日约 5000 次调用，个人使用足够
3. **DeepSeek API 费用**：deepseek-chat 模型价格低廉，单次攻略约 ¥0.1-0.3
4. **OpenCLI 小红书**：需 Chrome 浏览器 + OpenCLI 扩展，详见 [Agent-Reach](https://github.com/Panniantong/agent-reach)

---

## 🙏 致谢与引用

### 致敬项目

- [**hiyeshu/trip-map-builder**](https://github.com/hiyeshu/trip-map-builder) — 三阶段旅行规划工作流（规划→调研→地图），本项目的小红书调研和单文件HTML模板理念深受其启发
- [**Hatari130/map-creator**](https://github.com/Hatari130/map-creator) — 结合 GIS+GPT 的城市打卡地图生成器，启发了本项目的海报风格手册和图片获取方案
- [**Drfccv/AI-Trip-Planner**](https://github.com/Drfccv/AI-Trip-Planner) — 基于 LLM+高德 API 的旅行规划器，验证了技术路线的可行性
- [**Panniantong/agent-reach**](https://github.com/Panniantong/agent-reach) — AI Agent 互联网渠道工具，提供小红书/B站/Reddit 等调研能力
- [**jackwener/OpenCLI**](https://github.com/jackwener/OpenCLI) — 浏览器桥接工具，支撑小红书内容采集

### 技术依赖

- [高德开放平台 Web 服务 API](https://lbs.amap.com/) — POI 搜索、地理编码、路径规划、静态地图
- [DeepSeek API](https://platform.deepseek.com/) — 对抗性辩论路线规划、出行建议生成
- [Leaflet.js](https://leafletjs.com/) — 开源交互式地图库
- [OpenStreetMap](https://www.openstreetmap.org/) — 免费地图数据

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
