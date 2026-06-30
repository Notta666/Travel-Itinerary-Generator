/* =====================================================
   AI 智能随心游 · 一键规划行程 - JavaScript
   ===================================================== */

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
  setInterval(rotateTags,8000);
});

function fill(t){document.getElementById('goalInput').value=t;}

var quoteTimer = null;
var currentTaskId = null;        // 当前运行的任务 ID
var evtSource = null;            // SSE 连接
var QUOTES = [
  "📕 正在翻阅小红书的宝藏笔记...",
  "🏛️ 整理景点数据和真实用户反馈中...",
  "🍜 搜索本地人私藏的美食路线...",
  "🗺️ 计算各景点之间的最优路线...",
  "💰 查询飞猪实时机票/高铁/酒店价格...",
  "⏳ 综合预算和人数做最优行程规划...",
  "🎫 查询景点门票价格和开放信息...",
  "☀️ 查看目的地天气预报...",
  "🏨 搜索顺路又实惠的住宿...",
  "🤝 避雷过滤中——全网黑的餐厅已剔除...",
  "📊 多方案路线辩论中，选最好走的那条...",
  "🎨 正在生成精美图文手册和交互地图...",
  "📦 您专属的旅行攻略打包中，马上就好..."
];

var LOADING_TEMPLATE = [
  '<div class="loader"></div>',
  '<p class="loading-title">🤖 正在规划你的专属攻略...</p>',
  '<p class="hint" id="loadingHint">读取小红书网友路线中...</p>',
  '<div class="quote-container">',
  '  <span class="quote-text" id="quoteText">📕 正在翻阅小红书的宝藏笔记...</span>',
  '</div>',
  '<div id="stepProgress" style="margin:12px auto 0;max-width:340px;text-align:center;font-size:12px;color:#6366f1;font-weight:600;min-height:20px;"></div>',
  '<div class="progress-bar"><div class="progress-bar-inner"></div></div>'
].join('\n');

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
      void quoteEl.offsetWidth;
      quoteEl.classList.remove('fade-in');
    }, 400);
  }

  quoteTimer = setInterval(nextQuote, 6000);
}

function resetButton() {
  var btn=document.getElementById('genBtn');
  btn.disabled=false;
  btn.innerText='🚀 规划行程';
  btn.style.background='';
  btn.style.boxShadow='';
  btn.classList.remove('cancel-state');
  currentTaskId = null;
  if (evtSource) { evtSource.close(); evtSource = null; }
}

function cancelCurrentTask() {
  if (!currentTaskId) return;
  var btn=document.getElementById('genBtn');
  btn.disabled=true;
  btn.innerText='⏳ 正在取消...';
  if (evtSource) { evtSource.close(); evtSource = null; }
  fetch('/cancel/'+currentTaskId, {method:'POST'})
    .then(function(r){return r.json()})
    .then(function(){
      resetButton();
      document.getElementById('loading').innerHTML='<p>⏹️ 已取消规划</p>';
    })
    .catch(function(){
      resetButton();
    });
}

async function generate(){
  var goal=document.getElementById('goalInput').value.trim();
  if(!goal) return;
  var btn=document.getElementById('genBtn');

  // 如果已有任务在运行，点击则取消
  if (currentTaskId) {
    cancelCurrentTask();
    return;
  }

  btn.disabled=true;
  btn.innerText='⏳ 提交中...';

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
  void bar.offsetWidth;
  bar.style.animation='progress 120s linear forwards';

  // 获取人数和总预算
  var peopleVal = document.getElementById('peopleInput').value.trim();
  var budgetVal = document.getElementById('budgetInput').value.trim();
  var people = peopleVal ? parseInt(peopleVal, 10) : null;
  var budget = budgetVal ? parseFloat(budgetVal) : null;

  // 获取酒店每晚预算区间
  var hotelMinVal = document.getElementById('hotelBudgetMin').value.trim();
  var hotelMaxVal = document.getElementById('hotelBudgetMax').value.trim();
  var hotelBudgetMin = hotelMinVal ? parseInt(hotelMinVal, 10) : 300;
  var hotelBudgetMax = hotelMaxVal ? parseInt(hotelMaxVal, 10) : 500;

  // 获取定制启用的步骤
  var steps = [];
  if(document.getElementById('step_research').checked) steps.push('research');
  if(document.getElementById('step_enrich').checked) steps.push('enrich');
  if(document.getElementById('step_distance').checked) steps.push('distance');
  if(document.getElementById('step_flyai').checked) steps.push('flyai');
  if(document.getElementById('step_tips').checked) steps.push('tips');

  try{
    var resp=await fetch('/generate',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({goal:goal, steps:steps, people:people, budget:budget, hotel_budget_min:hotelBudgetMin, hotel_budget_max:hotelBudgetMax})
    });
    var data=await resp.json();
    var taskId=data.task_id;
    currentTaskId = taskId;

    // 按钮改为「取消规划」
    btn.disabled=false;
    btn.innerText='⏹️ 取消规划';
    btn.style.background='linear-gradient(135deg,#ef4444,#dc2626)';
    btn.classList.add('cancel-state');

    // 使用 SSE（Server-Sent Events）替代轮询
    evtSource = new EventSource('/stream/'+taskId);
    evtSource.onmessage = function(event) {
      var msg = JSON.parse(event.data);
      // 更新进度提示与步骤显示 - 去掉后端传来的 "Step X/Y:" 前缀，避免与进度条重复
      var displayMsg = msg.message;
      // 简单截掉 "Step X/Y: " 或 "Step X/Y " 前缀
      displayMsg = displayMsg.replace(/^Step\s+\d+\/\d+[：:\s]+/, '');
      var quoteEl = document.getElementById('quoteText');
      if(quoteEl) quoteEl.innerText = '⏳ ' + displayMsg;
      var stepEl = document.getElementById('stepProgress');
      if(stepEl && !msg.done) stepEl.innerText = '⏳ ' + displayMsg;
      if(msg.done) {
        evtSource.close();
        evtSource = null;
        if (quoteTimer) {
          clearInterval(quoteTimer);
          quoteTimer = null;
        }
        if(msg.message.includes('完成')) {
          document.getElementById('brochureIframe').src='/result/'+taskId;
          document.getElementById('downloadLink').href='/download/'+taskId;
          document.getElementById('result').style.display='block';
          document.getElementById('loading').style.display='none';
          document.getElementById('goalInput').value='';
        } else {
          document.getElementById('loading').innerHTML='<p>❌ 生成失败</p><p style="font-size:13px;color:#666;margin-top:8px;">'+msg.message+'</p>';
        }
        resetButton();
      }
    };
    evtSource.onerror = function() {
      evtSource.close();
      evtSource = null;
    };
  }catch(e){
    if (quoteTimer) {
      clearInterval(quoteTimer);
      quoteTimer = null;
    }
    document.getElementById('loading').innerHTML='<p>❌ 请求失败: '+e.message+'</p>';
    resetButton();
  }
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
