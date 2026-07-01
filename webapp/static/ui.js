import { taskState } from './state.js';

export function showLoading() {
  const template = document.getElementById('loadingTemplate');
  const loadingEl = document.getElementById('loading');
  if (template && loadingEl) {
    loadingEl.innerHTML = '';
    const clone = template.content.cloneNode(true);
    loadingEl.appendChild(clone);
  }
  if (loadingEl) {
    loadingEl.style.display = 'block';
  }
  const resultEl = document.getElementById('result');
  if (resultEl) {
    resultEl.style.display = 'none';
  }

  // Initialize progress bar (CSS animation removed — driven by SSE pct)
  const bar = document.querySelector('.progress-bar-inner');
  if (bar) {
    bar.style.animation = 'none';
    bar.style.width = '0%';
  }
}

export function showResult(taskId) {
  const iframe = document.getElementById('brochureIframe');
  if (iframe) {
    iframe.src = '/result/' + taskId;
  }
  const dlLink = document.getElementById('downloadLink');
  if (dlLink) {
    dlLink.href = '/download/' + taskId;
  }
  const resultEl = document.getElementById('result');
  if (resultEl) {
    resultEl.style.display = 'block';
  }
  const loadingEl = document.getElementById('loading');
  if (loadingEl) {
    loadingEl.style.display = 'none';
  }
  const goalInput = document.getElementById('goalInput');
  if (goalInput) {
    goalInput.value = '';
  }
}

export function showError(msg) {
  const loadingEl = document.getElementById('loading');
  if (loadingEl) {
    loadingEl.innerHTML = `<p>❌ 失败</p><p style="font-size:13px;color:#666;margin-top:8px;">${msg}</p>`;
  }
}

export function updateProgress(msg) {
  let displayMsg = msg.message;
  // Strip "Step X/Y: " or "Step X/Y " prefix
  displayMsg = displayMsg.replace(/^Step\s+\d+\/\d+[：:\s]+/, '');

  const stepEl = document.getElementById('stepProgress');
  if (stepEl && !msg.done) {
    stepEl.innerText = '⚙️ 当前后台进度: ' + displayMsg;
  }

  // Bind real SSE progress percentage to bar width
  const bar = document.querySelector('.progress-bar-inner');
  if (bar && msg.pct !== undefined) {
    bar.style.width = `${msg.pct}%`;
  }
}

export function resetButton() {
  const btn = document.getElementById('genBtn');
  if (btn) {
    btn.disabled = false;
    btn.innerText = '✨ 极速规划';
    btn.style.background = '';
    btn.style.boxShadow = '';
    btn.classList.remove('cancel-state');
  }
  taskState.reset();
}

export function cancelCurrentTask() {
  if (!taskState.currentTaskId) return;
  const btn = document.getElementById('genBtn');
  if (btn) {
    btn.disabled = true;
    btn.innerText = '⏳ 正在取消...';
  }

  const taskId = taskState.currentTaskId;
  taskState.reset();

  fetch('/cancel/' + taskId, { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      resetButton();
      const loadingEl = document.getElementById('loading');
      if (loadingEl) {
        loadingEl.innerHTML = '<p>⏹️ 已取消规划</p>';
      }
    })
    .catch(() => {
      resetButton();
    });
}
