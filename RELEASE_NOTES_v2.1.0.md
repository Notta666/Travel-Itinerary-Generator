# Release Notes - v2.1.0

AI 驱动智能旅行攻略生成器 `v2.1.0` 正式发布！本次更新重点提升了 **Web App 稳定性**、**图片搜索精度** 和 **用户体验**。

---

## ✨ 新功能

### ⏹️ 规划行程按钮二次点击可取消
- 任务运行中按钮变为红色 **"⏹️ 取消规划"**
- 再次点击即通过 `POST /cancel/{task_id}` 中断 pipeline
- 每个步骤前检查取消标记，优雅退出并清理资源
- 任务完成/失败后自动恢复为 "🚀 规划行程"

### 🖼️ 图片搜索增加省份上下文
- 新增 `_CITY_PROVINCE` 城市→省份映射（覆盖 71 个城市/地区）
- 景点搜索关键词从 `外滩` → `上海市上海外滩`
- 美食搜索关键词从 `陶陶居` → `广东省广州陶陶居 美食`
- 高德 API 保持 `city+name` 格式（利用 region 参数限制）
- Web 搜索引擎（360/百度/Bing）使用 `省份+城市+名称` 高精度格式

---

## 🐛 问题修复

- **WebApp 500 Internal Server Error**：`TemplateResponse(request, name, context)` 签名调用修复，之前传入了 `(name, context)` 导致 Jinja2 cache_key 拿到 dict 崩溃
- **`signal.signal()` 后台线程崩溃**：Web App 后台线程调用 pipeline 时因 `signal()` 必须在主线程执行而崩溃，已加主线程守卫

---

## 📦 如何升级

```bash
git pull origin main
```

## 依赖安装

```bash
python -m pip install -r requirements.txt
```

## 启动 Web App

```bash
python webapp/main.py
# 访问 http://localhost:8080
```
