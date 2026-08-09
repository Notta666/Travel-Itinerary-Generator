# v3.5.7 — 手册视觉修复 + 前端重构 + 安全加固

## ✨ 新增

- **根目录 ASGI 入口**：`main.py` 转发，支持 `uvicorn main:app` 从项目根启动
- **测试覆盖增强**：新增 3 个测试文件，测试套件 **45 项全部通过**（手册模板完整性 / 地理编码 / 规划器空坐标防御）

## 🐛 修复

- **手册出行建议字体大小不一**：每日提醒 `class="dt"` 与 Day 标题 `.dt` 类名冲突导致被放大为标题字号 → 独立 `tip-day` 类 + 统一字号
- **Day 卡片标题配色不协调**：蓝紫渐变 → 主题青绿系（hsl 172+），文字统一白色
- **Day 卡片文字未垂直居中**：`align-items:baseline` → `align-items:center` + `line-height:1` + padding 微调，字形级居中（偏移 ≤3px，CDP 实测）
- **安全**：`.gitignore` 补充 `webapp/tasks.db` / `.workbuddy/`；`reports/research_notes.md` 移出版本控制

## 🔄 变更

- **WebApp 前端重构**：样式变量体系、SSE 实时进度、主题切换、下载/取消按钮（AGY 交付 + 双轨审查）

## 🚀 升级方式

```bash
git pull
python -m pip install -r requirements.txt
python -m pytest tests/ -q        # 45 passed
python webapp/main.py             # 启动 WebApp → http://localhost:8080
```

> 安全默认：仅绑定 127.0.0.1:8080；CORS 白名单默认 localhost，可用 `CORS_ORIGINS` 环境变量控制。
