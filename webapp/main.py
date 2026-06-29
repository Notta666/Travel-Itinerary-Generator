"""
Travel-Itinerary-Generator · Web App
=====================================
FastAPI 后端，支持异步任务模式：
  POST   /generate    → 提交任务，返回 task_id
  GET    /status/{id}  → 查询任务状态
  GET    /result/{id}  → 获取生成结果（brochure HTML / 报告）
"""

import sys, os, json, uuid, time, threading, shutil, glob, asyncio

# 确保能导入项目模块
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI旅行攻略", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 任务存储（内存，重启丢失）
TASKS = {}
OUTPUTS_DIR = os.path.join(PROJECT, "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


def _run_pipeline_task(task_id, goal_text, enabled_steps=None, people=None, budget=None):
    """在后台线程中执行 pipeline"""
    try:
        from pipeline.run_pipeline import _parse_goal, run_pipeline
        TASKS[task_id]["status"] = "running"

        # 解析 goal
        city, days, pois, prefs = _parse_goal(goal_text)

        # 覆盖为 Web UI 用户输入的人数和预算
        ui_people = people if people is not None else 2
        
        if budget is not None:
            ui_budget_str = f"共{budget}元"
        else:
            total_est = 1500 * ui_people * max(days or 2, 1)
            ui_budget_str = f"共{total_est}元"
            
        prefs["people_count"] = ui_people
        prefs["budget"] = ui_budget_str

        # 设置定制步骤列表
        if enabled_steps is not None:
            prefs["enabled_steps"] = enabled_steps

        # 运行 pipeline（会调用 DeepSeek + 高德API）
        context = run_pipeline(city, days, manual_pois=pois, prefs=prefs)

        # 收集结果
        result = {
            "city": city,
            "days": days,
            "brochure": None,
            "report": None,
        }

        # 读取 brochure HTML
        if context.get("brochure_path") and os.path.exists(context["brochure_path"]):
            with open(context["brochure_path"], "r", encoding="utf-8") as f:
                result["brochure"] = f.read()
            result["brochure_path"] = context["brochure_path"]

        # 读取报告 MD
        if context.get("report_path") and os.path.exists(context["report_path"]):
            with open(context["report_path"], "r", encoding="utf-8") as f:
                result["report"] = f.read()

        TASKS[task_id].update({"status": "completed", "result": result})

    except Exception as e:
        import traceback
        TASKS[task_id].update({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc(),
        })


@app.get("/", response_class=HTMLResponse)
async def index():
    """首页"""
    return HTMLResponse(INDEX_HTML)


@app.post("/generate")
async def generate(data: dict):
    """提交生成任务"""
    goal = (data.get("goal") or "").strip()
    enabled_steps = data.get("steps")  # 获取勾选的步骤列表
    people = data.get("people")
    budget = data.get("budget")
    if not goal:
        raise HTTPException(400, "请输入目的地描述")
    task_id = uuid.uuid4().hex[:12]
    TASKS[task_id] = {"status": "pending", "goal": goal, "created": time.time()}
    # 在后台线程中执行（不阻塞HTTP响应）
    thread = threading.Thread(target=_run_pipeline_task, args=(task_id, goal, enabled_steps, people, budget), daemon=True)
    thread.start()
    return {"task_id": task_id, "status": "pending"}


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    """查询任务状态"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    resp = {
        "status": task["status"],
        "goal": task.get("goal", ""),
        "created": task.get("created", 0),
    }
    if task["status"] == "completed":
        resp["result"] = task.get("result", {})
    if task["status"] == "failed":
        resp["error"] = task.get("error", "")
    return resp


@app.get("/result/{task_id}", response_class=HTMLResponse)
async def get_result(task_id: str):
    """获取完整手册页面"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] != "completed":
        raise HTTPException(400, f"任务未完成，当前状态: {task['status']}")
    brochure_html = task.get("result", {}).get("brochure", "")
    if not brochure_html:
        return HTMLResponse("<h2>手册生成中，请稍后查看</h2>")
    return HTMLResponse(brochure_html)


@app.get("/download/{task_id}")
async def download(task_id: str):
    """下载手册HTML文件"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    path = task.get("result", {}).get("brochure_path", "")
    if not path or not os.path.exists(path):
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=os.path.basename(path), media_type="text/html")


# ------------------------------------------------------------
# 首页 HTML（内嵌）
# ------------------------------------------------------------
INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<title>AI 智能随心游 · 一键规划行程</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@400;500;700;900&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Noto Sans SC', 'Inter', sans-serif;
  background: linear-gradient(135deg, #FFF5F5 0%, #F5F3FF 50%, #EBF3FF 100%);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 20px 60px;
  background-attachment: fixed;
  color: #2c3e50;
}
.wrapper {
  width: 100%;
  max-width: 580px;
  transition: all .3s ease;
}
@media (min-width: 768px) {
  body { padding: 60px 40px 80px; }
  .wrapper { max-width: 720px; }
}

/* Header */
.header {
  text-align: center;
  margin-bottom: 32px;
  position: relative;
}
.badges {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.badge {
  padding: 5px 14px;
  border-radius: 50px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.7);
  color: #6366f1;
  border: 1px solid rgba(99, 102, 241, 0.15);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.badge.highlight {
  background: rgba(255, 36, 66, 0.08);
  color: #ff2442;
  border-color: rgba(255, 36, 66, 0.15);
}
.title-tag {
  display: inline-block;
  font-size: 12px;
  font-weight: 700;
  color: #ff2442;
  background: rgba(255, 36, 66, 0.08);
  padding: 4px 14px;
  border-radius: 50px;
  margin-bottom: 12px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
}
.title-main {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 40px;
  font-weight: 900;
  color: #1e1b4b;
  line-height: 1.2;
  letter-spacing: 1px;
  margin-bottom: 8px;
}
.title-main span {
  background: linear-gradient(135deg, #ff2442 30%, #8b5cf6 90%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.title-sub {
  font-size: 15px;
  font-weight: 500;
  color: #475569;
  opacity: 0.85;
}

/* Input Area (Glassmorphism) */
.input-glass {
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: 28px;
  padding: 24px;
  box-shadow: 0 20px 40px -15px rgba(31, 38, 135, 0.08), 0 1px 3px rgba(0, 0, 0, 0.01);
  margin-bottom: 16px;
  transition: border-color 0.3s;
}
.input-glass:focus-within {
  border-color: rgba(255, 36, 66, 0.3);
}
.input-glass .mockup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.mockup-dots { display: flex; gap: 6px; }
.dot { width: 9px; height: 9px; border-radius: 50%; }
.dot.r { background: #ff5f56; }
.dot.y { background: #ffbd2e; }
.dot.g { background: #27c93f; }
.mockup-label {
  font-family: 'Outfit', sans-serif;
  font-size: 11px;
  font-weight: 700;
  color: #8b5cf6;
  letter-spacing: 1px;
}
.input-row { display: flex; gap: 10px; }
.input-row input {
  flex: 1;
  padding: 14px 20px;
  border-radius: 16px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  background: rgba(255, 255, 255, 0.9);
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 15px;
  font-weight: 500;
  color: #1e293b;
  outline: none;
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.01);
  transition: all 0.25s ease;
}
.input-row input::placeholder { color: #94a3b8; font-weight: 400; }
.input-row input:focus {
  border-color: rgba(255, 36, 66, 0.4);
  box-shadow: 0 0 0 4px rgba(255, 36, 66, 0.08), inset 0 2px 4px rgba(0,0,0,0.01);
  background: #fff;
}
.input-row button {
  padding: 14px 28px;
  border-radius: 16px;
  border: none;
  background: linear-gradient(135deg, #ff2442 0%, #ff4b60 100%);
  color: #fff;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 6px 20px -4px rgba(255, 36, 66, 0.35);
  transition: all .2s ease;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 6px;
}
.input-row button:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px -2px rgba(255, 36, 66, 0.45);
}
.input-row button:active {
  transform: translateY(1px);
  box-shadow: 0 4px 12px -4px rgba(255, 36, 66, 0.35);
}
.input-row button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.params-row {
  display: flex;
  gap: 16px;
  margin-top: 16px;
  margin-bottom: 8px;
}
.param-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.param-item label {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 4px;
}
.param-item input {
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  background: rgba(255, 255, 255, 0.9);
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 14px;
  font-weight: 500;
  color: #1e293b;
  outline: none;
  transition: all 0.25s ease;
}
.param-item input::placeholder {
  color: #94a3b8;
  font-weight: 400;
}
.param-item input:focus {
  border-color: rgba(255, 36, 66, 0.4);
  box-shadow: 0 0 0 4px rgba(255, 36, 66, 0.08);
  background: #fff;
}
@media (max-width: 580px) {
  .params-row {
    flex-direction: column;
    gap: 12px;
  }
}

/* Examples */
.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 24px;
  justify-content: center;
}
.examples span {
  padding: 6px 16px;
  border-radius: 50px;
  font-size: 13px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(0, 0, 0, 0.04);
  color: #475569;
  cursor: pointer;
  box-shadow: 0 2px 5px rgba(0,0,0,0.01);
  transition: all .2s ease;
}
.examples span:hover {
  transform: translateY(-2px);
  background: #fff;
  border-color: rgba(255, 36, 66, 0.2);
  color: #ff2442;
  box-shadow: 0 4px 10px rgba(255, 36, 66, 0.06);
}

/* Features Grid */
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 24px;
}
.card {
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 22px;
  padding: 18px;
  box-shadow: 0 10px 20px -5px rgba(0, 0, 0, 0.01);
  transition: all .25s ease;
}
.card:hover {
  transform: translateY(-3px);
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 12px 28px -5px rgba(31, 38, 135, 0.05);
  border-color: rgba(255, 255, 255, 0.8);
}
.card-icon { font-size: 26px; margin-bottom: 8px; }
.card-title { font-size: 15px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
.card-desc { font-size: 12px; font-weight: 500; color: #64748b; line-height: 1.5; }

/* Loading UI */
#loading {
  display: none;
  text-align: center;
  padding: 48px 24px;
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-radius: 28px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 20px 40px -15px rgba(31, 38, 135, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.6);
}
.loader {
  width: 50px;
  height: 50px;
  margin: 0 auto 20px;
  border: 4px solid rgba(255, 36, 66, 0.08);
  border-top-color: #ff2442;
  border-radius: 50%;
  animation: spin .8s cubic-bezier(0.5, 0.1, 0.4, 0.9) infinite;
}
@keyframes spin { to { transform: rotate(360deg) } }
#loading p.loading-title { font-size: 16px; font-weight: 700; color: #1e293b; margin-bottom: 6px; }
#loading .hint { font-size: 13px; font-weight: 500; color: #64748b; margin-bottom: 20px; }
.quote-container {
  min-height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 12px auto;
  max-width: 320px;
}
.quote-text {
  font-size: 14px;
  font-weight: 600;
  color: #7c3aed;
  background: rgba(124, 58, 237, 0.06);
  padding: 6px 16px;
  border-radius: 30px;
  border: 1px solid rgba(124, 58, 237, 0.1);
  display: inline-block;
  transition: opacity 0.4s ease, transform 0.4s ease;
  opacity: 1;
  transform: translateY(0);
}
.quote-text.fade-out {
  opacity: 0;
  transform: translateY(-8px);
}
.quote-text.fade-in {
  opacity: 0;
  transform: translateY(8px);
}
.progress-bar {
  width: 220px;
  height: 6px;
  margin: 16px auto 0;
  background: rgba(0, 0, 0, 0.04);
  border-radius: 10px;
  overflow: hidden;
}
.progress-bar-inner {
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, #ff2442, #8b5cf6);
  border-radius: 10px;
  animation: progress 120s linear forwards;
}
@keyframes progress { to { width: 85% } }

/* Result Frame */
#result { display: none; width: 100%; }
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.result-header h2 { font-size: 20px; font-weight: 800; color: #1e293b; display: inline-flex; align-items: center; gap: 8px; }
.result-header a {
  padding: 8px 20px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid rgba(0, 0, 0, 0.08);
  color: #475569;
  text-decoration: none;
  font-size: 13px;
  font-weight: 700;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02);
  transition: all .2s;
}
.result-header a:hover {
  border-color: rgba(255, 36, 66, 0.2);
  color: #ff2442;
  box-shadow: 0 6px 12px -2px rgba(255, 36, 66, 0.08);
}
#brochureFrame {
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.06);
  background: #fff;
}
#brochureFrame iframe { width: 100%; height: 80vh; border: none; display: block; }

/* Footer */
.footer {
  text-align: center;
  margin-top: 32px;
  display: flex;
  justify-content: center;
  gap: 8px;
  align-items: center;
}
.footer span {
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(0, 0, 0, 0.03);
  color: #64748b;
  letter-spacing: 0.5px;
}
.footer .brand { font-family: 'Outfit', sans-serif; color: rgba(0,0,0,0.25); }

@media (max-width: 480px) {
  .title-main { font-size: 32px; }
  .input-row { flex-direction: column; gap: 8px; }
  .input-row button { width: 100%; justify-content: center; }
  .grid { grid-template-columns: 1fr; }
  .badge { font-size: 10px; padding: 4px 10px; }
}

/* Pipeline Customization Style */
.pipeline-customization {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed rgba(0, 0, 0, 0.08);
}
.custom-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 700;
  color: #475569;
  cursor: pointer;
  user-select: none;
}
.custom-title:hover {
  color: #ff2442;
}
.custom-options {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.option-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
  padding: 8px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.4);
  border: 1px solid rgba(0, 0, 0, 0.02);
  transition: all 0.2s;
}
.option-item:hover {
  background: rgba(255, 255, 255, 0.85);
  border-color: rgba(99, 102, 241, 0.15);
}
.option-item input[type="checkbox"] {
  margin-top: 4px;
  width: 16px;
  height: 16px;
  accent-color: #ff2442;
  cursor: pointer;
}
.option-details {
  display: flex;
  flex-direction: column;
}
.option-name {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
}
.option-desc {
  font-size: 11px;
  color: #64748b;
  line-height: 1.4;
  margin-top: 2px;
}

/* User Guide Style */
.user-guide-card {
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 24px;
  padding: 18px 24px;
  margin-top: 24px;
  margin-bottom: 8px;
  box-shadow: 0 10px 25px -10px rgba(0, 0, 0, 0.03);
}
.guide-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 15px;
  font-weight: 800;
  color: #1e1b4b;
  cursor: pointer;
  user-select: none;
}
.guide-header:hover {
  color: #ff2442;
}
.guide-content {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  border-top: 1px dashed rgba(0, 0, 0, 0.08);
  padding-top: 14px;
}
.guide-step {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.step-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ff2442, #8b5cf6);
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 10px rgba(255, 36, 66, 0.2);
}
.step-body {
  flex: 1;
}
.step-title {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 3px;
}
.step-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}
</style>
</head>
<body>

<div class="wrapper">
  <div class="header">
    <div class="badges">
      <span class="badge">🤖 AI 智能规划</span>
      <span class="badge highlight">📸 小红书美食避雷</span>
      <span class="badge">🗺️ Leaflet 交互路线</span>
    </div>
    <div class="title-tag">Smart Trip Planner</div>
    <div class="title-main">随心游 <span>AI旅行攻略</span></div>
    <div class="title-sub">说出你的旅行想法，一键生成图文并茂的手账式攻略</div>
  </div>

  <div class="input-glass">
    <div class="mockup-header">
      <div class="mockup-dots">
        <span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
      </div>
      <span class="mockup-label">AI PLANNER PROMPT</span>
    </div>
    <div class="input-row">
      <input id="goalInput" type="text" placeholder="输入目的地，例如「安吉周末自驾漂流」" onkeydown="if(event.key==='Enter')generate()">
      <button id="genBtn" onclick="generate()">规划行程 ✨</button>
    </div>
    
    <div class="params-row">
      <div class="param-item">
        <label for="peopleInput">👥 出行人数 (人)</label>
        <input id="peopleInput" type="number" min="1" placeholder="默认 2 人">
      </div>
      <div class="param-item">
        <label for="budgetInput">💰 总预算 (元)</label>
        <input id="budgetInput" type="number" min="0" placeholder="默认按 1500/人/天计算">
      </div>
    </div>

    <!-- Pipeline 步骤定制 -->
    <div class="pipeline-customization">
      <div class="custom-title" onclick="toggleCustomization()">
        <span>⚙️ Pipeline 步骤配置 (非核心步骤可选)</span>
        <span id="toggleIcon">➖</span>
      </div>
      <div class="custom-options" id="customOptions">
        <label class="option-item">
          <input type="checkbox" id="step_research" checked>
          <div class="option-details">
            <span class="option-name">小红书调研 📕 (Step 2)</span>
            <span class="option-desc">抓取网红打卡景点与推荐美食（如未连接 OpenCLI 扩展会自动秒跳过，无多余等待）</span>
          </div>
        </label>
        <label class="option-item">
          <input type="checkbox" id="step_enrich" checked>
          <div class="option-details">
            <span class="option-name">POI 地址丰富 🏛️ (Step 4)</span>
            <span class="option-desc">反查高德详细地址及片区信息，验证美食精确坐标</span>
          </div>
        </label>
        <label class="option-item">
          <input type="checkbox" id="step_distance" checked>
          <div class="option-details">
            <span class="option-name">驾车距离矩阵 📏 (Step 5)</span>
            <span class="option-desc">计算两点间驾车距离与时间，以优化每日行驶排序</span>
          </div>
        </label>
        <label class="option-item">
          <input type="checkbox" id="step_tips" checked>
          <div class="option-details">
            <span class="option-name">出行建议与天气 🌤️ (Step 8.5)</span>
            <span class="option-desc">获取打包清单、穿衣视觉指南以及未来 3-7 天天气预测</span>
          </div>
        </label>
      </div>
    </div>
  </div>

  <div class="examples" id="exampleTags">
    <span onclick="fill(this.dataset.goal)" data-goal="安吉周末漂流自驾">🏔️ 安吉漂流</span>
    <span onclick="fill(this.dataset.goal)" data-goal="杭州两天一夜带爸妈">👨‍👩‍👧 杭州亲子</span>
    <span onclick="fill(this.dataset.goal)" data-goal="莫干山避暑自驾">🌲 莫干山避暑</span>
    <span onclick="fill(this.dataset.goal)" data-goal="千岛湖三天度假">🏖️ 千岛湖度假</span>
  </div>

  <div class="grid">
    <div class="card"><div class="card-icon">📖</div><div class="card-title">精美图文手册</div><div class="card-desc">自动配图生成卡片行程，打卡避雷一应俱全</div></div>
    <div class="card"><div class="card-icon">🗺️</div><div class="card-title">随心交互地图</div><div class="card-desc">景点、餐厅、酒店分图层展示，按日清晰展示</div></div>
    <div class="card"><div class="card-icon">🍳</div><div class="card-title">真实美食推荐</div><div class="card-desc">融合小红书双通道调研，扫街美食精挑细选</div></div>
    <div class="card"><div class="card-icon">⚖️</div><div class="card-title">辩论式路线优化</div><div class="card-desc">高效派与悠闲派多轮对抗演算法，不走冤枉路</div></div>
  </div>

  <div id="loading">
    <div class="loader"></div>
    <p class="loading-title">🤖 AI 正在规划你的专属攻略...</p>
    <p class="hint">正在进行小红书多源分析与高德路线优化，预计需要 1-2 分钟</p>
    <div class="quote-container">
      <span class="quote-text" id="quoteText">正在翻小红书… 你负责偷懒，我负责做攻略 ✨</span>
    </div>
    <div class="progress-bar"><div class="progress-bar-inner"></div></div>
  </div>

  <div id="result">
    <div class="result-header">
      <h2>📖 攻略已就绪</h2>
      <a id="downloadLink" href="#">下载离线手册 ⬇</a>
    </div>
    <div id="brochureFrame">
      <iframe id="brochureIframe"></iframe>
    </div>
  </div>

  <!-- 使用说明 -->
  <div class="user-guide-card">
    <div class="guide-header" onclick="toggleGuide()">
      <span>📖 AI 随心游使用说明</span>
      <span id="guideToggleIcon">➕</span>
    </div>
    <div class="guide-content" id="guideContent" style="display: none;">
      <div class="guide-step">
        <div class="step-num">1</div>
        <div class="step-body">
          <div class="step-title">输入您的旅行灵感</div>
          <div class="step-desc">在上方输入目的地及特殊要求，如“安吉周末漂流自驾”、“带爸妈杭州两天一日，要轻松”等。系统会自动分析天数、预算和偏好。</div>
        </div>
      </div>
      <div class="guide-step">
        <div class="step-num">2</div>
        <div class="step-body">
          <div class="step-title">定制您的专属流程</div>
          <div class="step-desc">通过勾选“Pipeline 步骤配置”，您可以定制运行流程。如果需要最快的生成速度，可以取消勾选“小红书调研”等耗时步骤。</div>
        </div>
      </div>
      <div class="guide-step">
        <div class="step-num">3</div>
        <div class="step-body">
          <div class="step-title">获取高颜值手账攻略</div>
          <div class="step-desc">生成完毕后，系统将展示融合 Leaflet 交互地图的图文旅行手册，您可以在线任意切换景点、美食、酒店，还可以点击下载 HTML 离线查看。</div>
        </div>
      </div>
    </div>
  </div>

  <div class="footer">
    <span class="brand">Hermes Travel Engine</span>
    <span>v1.2.0</span>
  </div>
</div>

<script>
// 丰富示例库
var TAG_POOL = [
  {emoji:'🏔️', label:'安吉漂流',     goal:'安吉周末漂流自驾'},
  {emoji:'👨‍👩‍👧', label:'杭州亲子',     goal:'杭州两天一夜带爸妈'},
  {emoji:'🌲',  label:'莫干山避暑',   goal:'莫干山避暑自驾'},
  {emoji:'🏖️', label:'千岛湖度假',   goal:'千岛湖三天度假'},
  {emoji:'🌊',  label:'去看海',       goal:'三天两夜去看海'},
  {emoji:'🏛️', label:'北京三日',     goal:'北京三天两夜预算3000'},
  {emoji:'🎋',  label:'江南水乡',     goal:'乌镇西塘两天一夜'},
  {emoji:'🏯',  label:'苏州园林',     goal:'苏州园林周末两日游'},
  {emoji:'🌋',  label:'黄山奇景',     goal:'黄山两天一夜'},
  {emoji:'🏝️', label:'三亚度假',     goal:'三亚五天四晚'},
  {emoji:'🌶️', label:'成都美食',     goal:'成都三天两夜美食之旅'},
  {emoji:'🚢',  label:'厦门鼓浪屿',   goal:'厦门鼓浪屿三天两夜'},
  {emoji:'🏔️', label:'大理丽江',     goal:'大理丽江七日游'},
  {emoji:'🎡',  label:'上海迪士尼',   goal:'上海迪士尼周末'},
  {emoji:'🐟',  label:'舟山吃海鲜',   goal:'舟山群岛看海吃海鲜'},
  {emoji:'🙏',  label:'普陀山祈福',   goal:'普陀山两天一夜'},
  {emoji:'🍺',  label:'青岛啤酒',     goal:'青岛啤酒海鲜三日'},
  {emoji:'🏞️', label:'桂林阳朔',     goal:'桂林阳朔三天漂流'},
  {emoji:'🌃',  label:'重庆夜景',     goal:'重庆洪崖洞三天两夜'},
  {emoji:'🏕️', label:'宏村写生',     goal:'宏村西递古村两天'},
  {emoji:'🧘',  label:'泡温泉',       goal:'泡温泉两天一夜'},
  {emoji:'🏎️', label:'自驾游',       goal:'浙江周末自驾游'},
  {emoji:'🍵',  label:'龙井问茶',     goal:'杭州龙井村一日游'},
  {emoji:'🎿',  label:'滑雪',         goal:'滑雪两天一夜'},
];

function pickRandom(n){
  var shuffled=TAG_POOL.slice().sort(function(){return Math.random()-0.5});
  return shuffled.slice(0,n);
}

function rotateTags(){
  var container=document.getElementById('exampleTags');
  if(!container) return;
  var tags=pickRandom(4);
  container.innerHTML=tags.map(function(t){
    return '<span data-goal="'+t.goal+'" onclick="fill(this.dataset.goal)">'+t.emoji+' '+t.label+'</span>';
  }).join('');
}

document.addEventListener('DOMContentLoaded',function(){
  rotateTags();
  setInterval(rotateTags,8000); // 稍微加长轮换时间，减少眼花缭乱感
});

function fill(t){document.getElementById('goalInput').value=t;}

var quoteTimer = null;
var QUOTES = [
  "正在翻小红书… 你负责偷懒，我负责做攻略 ✨",
  "让 AI 替你卷，你只管出发 🚗",
  "别急，好的路线值得等 🗺️",
  "大数据已经把这届网友的宝藏路线都扒出来了 🔍",
  "懒人改变世界——包括旅行方式 🌍",
  "正在避开所有排队两小时的网红踩雷点 🙅‍♂️",
  "打工人，你的无痛旅行攻略正在打包中 📦",
  "特种兵还是度假党？AI 正在帮你做最优解 ⚖️",
  "攻略我来做，你只需要负责发朋友圈美照 📸",
  "路线正在疯狂对齐中，马上出发！🚀",
  "世界那么大，懒得做攻略？交给我啦 🗺️",
  "正在为您挑选本地人私藏的宝藏街角 ☕",
  "不做冤大头，避雷指南已加入豪华午餐 🍋",
  "身体和灵魂，总有一个在期待这份攻略 💫",
  "正在用大数据为你编织一场说走就走的梦 🦄",
  "行程规划中…… 已经闻到远方的空气了 🍃",
  "不塞车、不排队、不踩雷的完美路线正在生成中 🚗"
];

var LOADING_TEMPLATE = `
  <div class="loader"></div>
  <p class="loading-title">🤖 AI 正在规划你的专属攻略...</p>
  <p class="hint">正在进行小红书多源分析与高德路线优化，预计需要 1-2 分钟</p>
  <div class="quote-container">
    <span class="quote-text" id="quoteText">正在翻小红书… 你负责偷懒，我负责做攻略 ✨</span>
  </div>
  <div class="progress-bar"><div class="progress-bar-inner"></div></div>
`;

function startQuoteRotation() {
  if (quoteTimer) clearInterval(quoteTimer);
  var quoteEl = document.getElementById('quoteText');
  if (!quoteEl) return;
  var lastIndex = 0;
  
  function nextQuote() {
    var nextIdx;
    do {
      nextIdx = Math.floor(Math.random() * QUOTES.length);
    } while (nextIdx === lastIndex && QUOTES.length > 1);
    lastIndex = nextIdx;
    var text = QUOTES[nextIdx];
    
    quoteEl.classList.add('fade-out');
    setTimeout(function() {
      quoteEl.innerText = text;
      quoteEl.classList.remove('fade-out');
      quoteEl.classList.add('fade-in');
      void quoteEl.offsetWidth; // 触发回流
      quoteEl.classList.remove('fade-in');
    }, 400); // 对应 CSS 0.4s 过渡
  }
  
  quoteTimer = setInterval(nextQuote, 6000); // 每 6 秒轮换一次
}

async function generate(){
  var goal=document.getElementById('goalInput').value.trim();
  if(!goal) return;
  var btn=document.getElementById('genBtn');
  btn.disabled=true;
  
  if (quoteTimer) {
    clearInterval(quoteTimer);
    quoteTimer = null;
  }
  
  var loadingEl = document.getElementById('loading');
  loadingEl.innerHTML = LOADING_TEMPLATE;
  loadingEl.style.display='block';
  document.getElementById('result').style.display='none';
  
  startQuoteRotation();
  
  // 重启进度条动画
  var bar = document.querySelector('.progress-bar-inner');
  bar.style.animation='none';
  void bar.offsetWidth; // 触发回流
  bar.style.animation='progress 120s linear forwards';

  // 获取人数和总预算
  var peopleVal = document.getElementById('peopleInput').value.trim();
  var budgetVal = document.getElementById('budgetInput').value.trim();
  var people = peopleVal ? parseInt(peopleVal, 10) : null;
  var budget = budgetVal ? parseFloat(budgetVal) : null;

  // 获取定制启用的步骤
  var steps = [];
  if(document.getElementById('step_research').checked) steps.push('research');
  if(document.getElementById('step_enrich').checked) steps.push('enrich');
  if(document.getElementById('step_distance').checked) steps.push('distance');
  if(document.getElementById('step_tips').checked) steps.push('tips');

  try{
    var resp=await fetch('/generate',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({goal:goal, steps:steps, people:people, budget:budget})
    });
    var data=await resp.json();
    var taskId=data.task_id;
    var attempts=0;
    while(attempts<120){
      await new Promise(r=>setTimeout(r,3000));
      var sr=await fetch('/status/'+taskId);
      var st=await sr.json();
      if(st.status==='completed'){
        document.getElementById('brochureIframe').src='/result/'+taskId;
        document.getElementById('downloadLink').href='/download/'+taskId;
        document.getElementById('result').style.display='block';
        document.getElementById('loading').style.display='none';
        document.getElementById('goalInput').value='';
        if (quoteTimer) {
          clearInterval(quoteTimer);
          quoteTimer = null;
        }
        break;
      }else if(st.status==='failed'){
        if (quoteTimer) {
          clearInterval(quoteTimer);
          quoteTimer = null;
        }
        document.getElementById('loading').innerHTML='<p>❌ 生成失败</p><p style="font-size:13px;color:#666;margin-top:8px;">'+st.error+'</p>';
        break;
      }
      attempts++;
    }
  }catch(e){
    if (quoteTimer) {
      clearInterval(quoteTimer);
      quoteTimer = null;
    }
    document.getElementById('loading').innerHTML='<p>❌ 请求失败: '+e.message+'</p>';
  }
  btn.disabled=false;
}

function toggleCustomization() {
  var opts = document.getElementById('customOptions');
  var icon = document.getElementById('toggleIcon');
  if(opts.style.display === 'none') {
    opts.style.display = 'flex';
    icon.innerText = '➖';
  } else {
    opts.style.display = 'none';
    icon.innerText = '➕';
  }
}

function toggleGuide() {
  var content = document.getElementById('guideContent');
  var icon = document.getElementById('guideToggleIcon');
  if(content.style.display === 'none') {
    content.style.display = 'flex';
    icon.innerText = '➖';
  } else {
    content.style.display = 'none';
    icon.innerText = '➕';
  }
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    print("🌍 AI旅行攻略 Web App 启动中...")
    print("   访问地址: http://localhost:8080")
    print("   按 Ctrl+C 停止")
    uvicorn.run(app, host="0.0.0.0", port=8080, timeout_keep_alive=600)
