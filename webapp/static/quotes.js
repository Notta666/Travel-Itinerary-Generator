import { taskState } from './state.js';

export const QUOTES = [
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

export function startQuoteRotation() {
  if (taskState.quoteTimer) clearInterval(taskState.quoteTimer);
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

  taskState.quoteTimer = setInterval(nextQuote, 6000);
}

export function stopQuoteRotation() {
  if (taskState.quoteTimer) {
    clearInterval(taskState.quoteTimer);
    taskState.quoteTimer = null;
  }
}
