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

var LOADING_TEMPLATE = [
  '<div class="loader"></div>',
  '<p class="loading-title">🤖 AI 正在规划你的专属攻略...</p>',
  '<p class="hint">正在进行多源分析与路线优化，预计需要 1-2 分钟</p>',
  '<div class="quote-container">',
  '  <span class="quote-text" id="quoteText">正在翻小红书… 你负责偷懒，我负责做攻略 ✨</span>',
  '</div>',
  '<div id="stepProgress" style="margin:12px auto 0;max-width:320px;text-align:center;font-size:12px;color:#6366f1;font-weight:600;min-height:20px;"></div>',
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
      // 更新进度提示与步骤显示
      var quoteEl = document.getElementById('quoteText');
      if(quoteEl) quoteEl.innerText = msg.message;
      var stepEl = document.getElementById('stepProgress');
      if(stepEl && !msg.done) stepEl.innerText = '⏳ ' + msg.message;
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
