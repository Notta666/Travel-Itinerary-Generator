import { taskState } from './state.js?v=3.5.6';
import { startQuoteRotation, stopQuoteRotation } from './quotes.js?v=3.5.6';
import { connectSSE } from './sse.js?v=3.5.6';
import { showLoading, showResult, showError, updateProgress, resetButton, cancelCurrentTask } from './ui.js?v=3.5.6';

const TAG_POOL = [
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

function pickRandom(n) {
  const shuffled = TAG_POOL.slice().sort(() => Math.random() - 0.5);
  return shuffled.slice(0, n);
}

function rotateTags() {
  const container = document.getElementById('exampleTags');
  if (!container) return;
  const tags = pickRandom(4);
  container.innerHTML = tags.map(t => {
    return `<span data-goal="${t.goal}" onclick="fill(this.dataset.goal)">${t.emoji} ${t.label}</span>`;
  }).join('');
}

document.addEventListener('DOMContentLoaded', () => {
  rotateTags();
  setInterval(rotateTags, 8000);
});

// Run tag rotation immediately if DOMContentLoaded has already fired
if (document.readyState === 'interactive' || document.readyState === 'complete') {
  rotateTags();
}

export function fill(t) {
  const goalInput = document.getElementById('goalInput');
  if (goalInput) {
    goalInput.value = t;
  }
}

export function toggleCustomization() {
  const opts = document.getElementById('customOptions');
  const icon = document.getElementById('toggleIcon');
  if (!opts || !icon) return;
  if (opts.style.display === 'none') {
    opts.style.display = 'flex';
    icon.innerText = '➖';
  } else {
    opts.style.display = 'none';
    icon.innerText = '➕';
  }
}

export function toggleGuide() {
  const content = document.getElementById('guideContent');
  const icon = document.getElementById('guideToggleIcon');
  if (!content || !icon) return;
  if (content.style.display === 'none') {
    content.style.display = 'flex';
    icon.innerText = '➖';
  } else {
    content.style.display = 'none';
    icon.innerText = '➕';
  }
}

export async function generate() {
  const goal = document.getElementById('goalInput').value.trim();
  if (!goal) return;
  const btn = document.getElementById('genBtn');

  // If a task is already running, click cancels it
  if (taskState.currentTaskId) {
    cancelCurrentTask();
    return;
  }

  btn.disabled = true;
  btn.innerText = '⏳ 提交中...';

  stopQuoteRotation();
  showLoading();
  startQuoteRotation();

  // Get people and total budget
  const peopleVal = document.getElementById('peopleInput').value.trim();
  const budgetVal = document.getElementById('budgetInput').value.trim();
  const people = peopleVal ? parseInt(peopleVal, 10) : null;
  const budget = budgetVal ? parseFloat(budgetVal) : null;

  // Get hotel nightly budget range
  const hotelMinVal = document.getElementById('hotelBudgetMin').value.trim();
  const hotelMaxVal = document.getElementById('hotelBudgetMax').value.trim();
  const hotelBudgetMin = hotelMinVal ? parseInt(hotelMinVal, 10) : 300;
  const hotelBudgetMax = hotelMaxVal ? parseInt(hotelMaxVal, 10) : 500;

  // Get enabled customized steps
  const steps = [];
  if (document.getElementById('step_research').checked) steps.push('research');
  if (document.getElementById('step_enrich').checked) steps.push('enrich');
  if (document.getElementById('step_distance').checked) steps.push('distance');
  if (document.getElementById('step_flyai').checked) steps.push('flyai');
  if (document.getElementById('step_tips').checked) steps.push('tips');

  try {
    const resp = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        goal: goal,
        steps: steps,
        people: people,
        budget: budget,
        hotel_budget_min: hotelBudgetMin,
        hotel_budget_max: hotelBudgetMax
      })
    });
    const data = await resp.json();
    const taskId = data.task_id;
    taskState.currentTaskId = taskId;

    // Change button to cancel state
    btn.disabled = false;
    btn.innerText = '⏹️ 取消规划';
    btn.style.background = 'linear-gradient(135deg,#ef4444,#dc2626)';
    btn.classList.add('cancel-state');

    // Use SSE (Server-Sent Events) instead of polling
    connectSSE(
      taskId,
      msg => {
        updateProgress(msg);
      },
      msg => {
        stopQuoteRotation();
        if (msg.message.includes('完成')) {
          showResult(taskId);
        } else {
          showError(msg.message);
        }
        resetButton();
      }
    );
  } catch (e) {
    stopQuoteRotation();
    showError('请求失败: ' + e.message);
    resetButton();
  }
}

// Bind to window object for inline HTML event handlers
window.generate = generate;
window.fill = fill;
window.toggleCustomization = toggleCustomization;
window.toggleGuide = toggleGuide;
