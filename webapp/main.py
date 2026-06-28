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


def _run_pipeline_task(task_id, goal_text):
    """在后台线程中执行 pipeline"""
    try:
        from pipeline.run_pipeline import _parse_goal, run_pipeline
        TASKS[task_id]["status"] = "running"

        # 解析 goal
        city, days, pois, prefs = _parse_goal(goal_text)

        # 运行 pipeline（会调用 DeepSeek + 高德API，耗时 2-5 分钟）
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
    if not goal:
        raise HTTPException(400, "请输入目的地描述")
    task_id = uuid.uuid4().hex[:12]
    TASKS[task_id] = {"status": "pending", "goal": goal, "created": time.time()}
    # 在后台线程中执行（不阻塞HTTP响应）
    thread = threading.Thread(target=_run_pipeline_task, args=(task_id, goal), daemon=True)
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
<title>AI旅行攻略 · 一键生成</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Noto+Sans+SC:wght@400;500;700;900&family=Outfit:wght@600;700;800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{
  font-family:'Noto Sans SC','Inter',sans-serif;
  background:linear-gradient(135deg,#d4fc79 0%,#96e6a1 50%,#84fab0 100%);
  min-height:100vh;display:flex;flex-direction:column;align-items:center;
  padding:40px 20px 60px;
  background-attachment:fixed;
}
.wrapper{
  width:100%;max-width:520px;
  transition:max-width .3s;
}
@media(min-width:768px){
  body{padding:60px 40px 80px;}
  .wrapper{max-width:640px;}
}

/* Header */
.header{text-align:center;margin-bottom:24px;position:relative;}
.badges{display:flex;justify-content:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;}
.badge{
  padding:4px 12px;border-radius:50px;font-size:11px;font-weight:700;
  background:#fff;color:#000;border:2px solid #000;
  box-shadow:2px 2px 0 #000;
  display:inline-flex;align-items:center;gap:4px;
}
.title-tag{
  display:inline-block;font-size:20px;font-weight:900;
  background:#ffe600;color:#000;padding:4px 14px;border-radius:12px;
  border:2.5px solid #000;box-shadow:3px 3px 0 #000;
  margin-bottom:10px;letter-spacing:2px;
}
.title-main{
  font-size:48px;font-weight:900;color:#fff;line-height:1.1;letter-spacing:2px;
  text-shadow:4px 4px 0 #000,-1px -1px 0 #000,1px -1px 0 #000,-1px 1px 0 #000,1px 1px 0 #000;
  margin-bottom:4px;
}
.title-sub{font-size:16px;font-weight:700;color:#000;opacity:0.6;letter-spacing:1px;}

/* Input glass */
.input-glass{
  background:rgba(255,255,255,0.5);backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px);
  border:2.5px solid #000;border-radius:20px;padding:14px;
  box-shadow:4px 4px 0 #000;margin-bottom:10px;
}
.input-glass .mockup-header{
  display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;
}
.mockup-dots{display:flex;gap:4px;}
.dot{width:8px;height:8px;border-radius:50%;border:1.5px solid #000;}
.dot.r{background:#ff5f56;}
.dot.y{background:#ffbd2e;}
.dot.g{background:#27c93f;}
.mockup-label{
  font-family:'Outfit',sans-serif;font-size:10px;font-weight:800;color:#000;letter-spacing:0.5px;
}
.input-row{display:flex;gap:8px;}
.input-row input{
  flex:1;padding:10px 14px;border-radius:12px;
  border:2px solid #000;background:#fff;
  font-family:'Noto Sans SC',sans-serif;font-size:14px;font-weight:500;color:#000;
  outline:none;box-shadow:inset 1px 1px 4px rgba(0,0,0,0.05);
}
.input-row input::placeholder{color:#999;font-weight:400;}
.input-row button{
  padding:10px 20px;border-radius:12px;border:2px solid #000;
  background:#ff2442;color:#fff;
  font-family:'Noto Sans SC',sans-serif;font-size:14px;font-weight:800;
  cursor:pointer;box-shadow:2px 2px 0 #000;
  transition:all .15s;white-space:nowrap;
  display:flex;align-items:center;gap:4px;
}
.input-row button:hover{transform:translate(-1px,-1px);box-shadow:3px 3px 0 #000;}
.input-row button:active{transform:translate(1px,1px);box-shadow:1px 1px 0 #000;}
.input-row button:disabled{opacity:0.4;cursor:not-allowed;transform:none;}

/* Examples */
.examples{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px;}
.examples span{
  padding:4px 12px;border-radius:50px;font-size:12px;font-weight:700;
  background:#fff;border:2px solid #000;color:#000;
  cursor:pointer;box-shadow:2px 2px 0 #000;
  transition:all .15s;
}
.examples span:hover{transform:translate(-1px,-1px);box-shadow:3px 3px 0 #000;}

/* Features grid */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;}
.card{
  background:rgba(255,255,255,0.85);backdrop-filter:blur(8px);
  border:2.5px solid #000;border-radius:16px;padding:14px;
  box-shadow:3px 3px 0 #000;
}
.card-icon{font-size:20px;margin-bottom:4px;}
.card-title{font-size:14px;font-weight:800;color:#000;margin-bottom:2px;}
.card-desc{font-size:11px;font-weight:600;color:#444;line-height:1.4;}

/* Loading */
#loading{display:none;text-align:center;padding:40px 0;}
.loader{width:48px;height:48px;margin:0 auto 16px;
  border:4px solid rgba(0,0,0,0.1);
  border-top-color:#ff2442;border-radius:50%;
  animation:spin .7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
#loading p{font-size:15px;font-weight:700;color:#000;}
#loading .hint{font-size:12px;font-weight:500;color:rgba(0,0,0,0.4);margin-top:6px;}
.progress-bar{
  width:200px;height:6px;margin:12px auto 0;
  background:rgba(0,0,0,0.08);border-radius:3px;overflow:hidden;
}
.progress-bar-inner{
  height:100%;width:0%;background:linear-gradient(90deg,#ff2442,#ff7eb3);
  border-radius:3px;animation:progress 120s linear forwards;
}
@keyframes progress{to{width:85%}}

/* Result */
#result{display:none;}
.result-header{
  display:flex;justify-content:space-between;align-items:center;
  margin-bottom:14px;
}
.result-header h2{font-size:20px;font-weight:900;color:#000;display:flex;align-items:center;gap:8px;}
.result-header a{
  padding:6px 16px;border-radius:10px;
  background:#fff;border:2px solid #000;color:#000;
  text-decoration:none;font-size:12px;font-weight:800;
  box-shadow:2px 2px 0 #000;
}
#brochureFrame{
  border:2.5px solid #000;border-radius:16px;overflow:hidden;
  box-shadow:4px 4px 0 #000;
  background:#fff;
}
#brochureFrame iframe{width:100%;height:80vh;border:none;display:block;}

/* Footer */
.footer{
  text-align:center;margin-top:24px;
  display:flex;justify-content:center;gap:8px;align-items:center;
}
.footer span{
  padding:3px 10px;border-radius:6px;font-size:10px;font-weight:700;
  background:rgba(0,0,0,0.06);color:rgba(0,0,0,0.5);
  letter-spacing:0.5px;
}
.footer .brand{font-family:'Outfit',sans-serif;color:rgba(0,0,0,0.3);}

@media(max-width:480px){
  .title-main{font-size:36px;}
  .input-row{flex-direction:column;}
  .grid{grid-template-columns:1fr;}
  .badge{font-size:10px;}
}
</style>
</head>
<body>

<div class="wrapper">
  <div class="header">
    <div class="badges">
      <span class="badge">🤖 AI 自动生成</span>
      <span class="badge">🗺️ 交互地图</span>
      <span class="badge">✨ 懒人必备</span>
    </div>
    <div class="title-tag">旅行神器</div>
    <div class="title-main">AI旅行攻略</div>
    <div class="title-sub">输入目的地 · 一键生成</div>
  </div>

  <div class="input-glass">
    <div class="mockup-header">
      <div class="mockup-dots">
        <span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
      </div>
      <span class="mockup-label">COMMAND PROMPT</span>
    </div>
    <div class="input-row">
      <input id="goalInput" type="text" placeholder="输入目的地，例如「安吉周末自驾漂流」" onkeydown="if(event.key==='Enter')generate()">
      <button id="genBtn" onclick="generate()">生成 ✨</button>
    </div>
  </div>

  <div class="examples" id="exampleTags">
    <span onclick="fill(this.dataset.goal)" data-goal="安吉周末漂流自驾">🏔️ 安吉漂流</span>
    <span onclick="fill(this.dataset.goal)" data-goal="杭州两天一夜带爸妈">👨‍👩‍👧 杭州亲子</span>
    <span onclick="fill(this.dataset.goal)" data-goal="莫干山避暑自驾">🌲 莫干山避暑</span>
    <span onclick="fill(this.dataset.goal)" data-goal="千岛湖三天度假">🏖️ 千岛湖度假</span>
  </div>

  <div class="grid">
    <div class="card"><div class="card-icon">📄</div><div class="card-title">图文手册</div><div class="card-desc">含精美封面及每日行程卡</div></div>
    <div class="card"><div class="card-icon">🗺️</div><div class="card-title">交互地图</div><div class="card-desc">支持 Leaflet 路线按日切换</div></div>
    <div class="card"><div class="card-icon">🍜</div><div class="card-title">扫街美食</div><div class="card-desc">扫街榜高分推荐，绝不踩雷</div></div>
    <div class="card"><div class="card-icon">🤖</div><div class="card-title">辩论规划</div><div class="card-desc">AI对抗优化路线，不走弯路</div></div>
  </div>

  <div id="loading">
    <div class="loader"></div>
    <p>🤖 AI 正在规划行程...</p>
    <p class="hint">正在调用高德API + DeepSeek 对抗辩论，约需2-3分钟</p>
    <div class="progress-bar"><div class="progress-bar-inner"></div></div>
  </div>

  <div id="result">
    <div class="result-header">
      <h2>📖 攻略已生成</h2>
      <a id="downloadLink" href="#">下载文件 ⬇</a>
    </div>
    <div id="brochureFrame">
      <iframe id="brochureIframe"></iframe>
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
  setInterval(rotateTags,5000);
});

function fill(t){document.getElementById('goalInput').value=t;}

async function generate(){
  var goal=document.getElementById('goalInput').value.trim();
  if(!goal) return;
  var btn=document.getElementById('genBtn');
  btn.disabled=true;
  document.getElementById('loading').style.display='block';
  document.getElementById('result').style.display='none';
  document.querySelector('.progress-bar-inner').style.animation='none';
  void document.querySelector('.progress-bar-inner').offsetWidth;
  document.querySelector('.progress-bar-inner').style.animation='progress 120s linear forwards';

  try{
    var resp=await fetch('/generate',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({goal:goal})
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
        break;
      }else if(st.status==='failed'){
        document.getElementById('loading').innerHTML='<p>❌ 生成失败</p><p style="font-size:13px;color:#666">'+st.error+'</p>';
        break;
      }
      attempts++;
    }
  }catch(e){
    document.getElementById('loading').innerHTML='<p>❌ 请求失败: '+e.message+'</p>';
  }
  btn.disabled=false;
}
</script>
  </div>

</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    print("🌍 AI旅行攻略 Web App 启动中...")
    print("   访问地址: http://localhost:8080")
    print("   按 Ctrl+C 停止")
    uvicorn.run(app, host="0.0.0.0", port=8080, timeout_keep_alive=600)
