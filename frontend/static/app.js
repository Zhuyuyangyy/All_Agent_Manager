/* ═══════════════════════════════════════════
   All Agent Manager — 前端交互逻辑
   ═══════════════════════════════════════════ */

// ── 安全请求封装 ──
async function safeFetch(url, options = {}) {
  try {
    const res = await fetch(url, options);
    if (!res.ok) return null;
    const text = await res.text();
    try { return JSON.parse(text); } catch { return null; }
  } catch { return null; }
}

// ── Toast 通知 ──

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ── 通用分页渲染 ──

function renderPagination(container, currentPage, totalPages, onPageChange) {
  if (!container || totalPages <= 1) {
    if (container) container.innerHTML = '';
    return;
  }

  const buttons = [];

  // 上一页
  buttons.push(
    `<button class="pagination-btn" ${currentPage <= 1 ? 'disabled' : ''} data-page="${currentPage - 1}">&laquo;</button>`
  );

  // 页码按钮（最多显示 7 个）
  const maxVisible = 7;
  let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
  let endPage = Math.min(totalPages, startPage + maxVisible - 1);
  if (endPage - startPage < maxVisible - 1) {
    startPage = Math.max(1, endPage - maxVisible + 1);
  }

  if (startPage > 1) {
    buttons.push(`<button class="pagination-btn" data-page="1">1</button>`);
    if (startPage > 2) buttons.push(`<span class="pagination-ellipsis">...</span>`);
  }

  for (let i = startPage; i <= endPage; i++) {
    buttons.push(
      `<button class="pagination-btn ${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`
    );
  }

  if (endPage < totalPages) {
    if (endPage < totalPages - 1) buttons.push(`<span class="pagination-ellipsis">...</span>`);
    buttons.push(`<button class="pagination-btn" data-page="${totalPages}">${totalPages}</button>`);
  }

  // 下一页
  buttons.push(
    `<button class="pagination-btn" ${currentPage >= totalPages ? 'disabled' : ''} data-page="${currentPage + 1}">&raquo;</button>`
  );

  container.innerHTML = buttons.join('');

  // 绑定事件
  container.querySelectorAll('.pagination-btn:not([disabled])').forEach(btn => {
    btn.addEventListener('click', () => {
      const page = parseInt(btn.dataset.page, 10);
      if (!isNaN(page) && page >= 1 && page <= totalPages) {
        onPageChange(page);
      }
    });
  });
}

// ── 侧边栏导航 ──

const navItems = document.querySelectorAll('.nav-item');
const sections = document.querySelectorAll('.content-section');
const pageTitle = document.getElementById('page-title');
const sectionTitles = {
  bridge: '微信桥接',
  discovery: '智能发现',
  agents: 'Agent 状态',
  tasks: '任务管理',
  monitor: '执行监控',
  health: '健康状态',
  skills: '技能库',
  plugins: '插件管理',
  evolution: '进化审查',
  mcp: 'MCP 工具',
  messages: '消息记录',
  chat: 'iliya 对话',
  'model-config': '模型配置',
};

navItems.forEach(item => {
  item.addEventListener('click', (e) => {
    e.preventDefault();
    const section = item.dataset.section;

    navItems.forEach(n => n.classList.remove('active'));
    item.classList.add('active');

    sections.forEach(s => s.classList.remove('active'));
    document.getElementById(`section-${section}`).classList.add('active');

    pageTitle.textContent = sectionTitles[section] || '';
  });
});

// ── 微信桥接 ──

const wechatTokenForm = document.getElementById('wechat-token-form');
const wechatConnectBtn = document.getElementById('wechat-connect-btn');
const wechatDisconnectBtn = document.getElementById('wechat-disconnect-btn');
const wechatResult = document.getElementById('wechat-token-result');
const wechatBadge = document.getElementById('wechat-badge');
const wechatLight = document.getElementById('wechat-light');
const wechatStatusLabel = document.getElementById('wechat-status-label');
const wechatStatusDetail = document.getElementById('wechat-status-detail');
const wechatQrBtn = document.getElementById('wechat-qr-btn');
const wechatQrContainer = document.getElementById('wechat-qr-container');
const wechatQrImage = document.getElementById('wechat-qr-image');
const wechatQrStatus = document.getElementById('wechat-qr-status');
const wechatSavedCard = document.getElementById('wechat-saved-card');
const wechatSavedInfo = document.getElementById('wechat-saved-info');
const wechatClearTokenBtn = document.getElementById('wechat-clear-token-btn');
const globalStatus = document.getElementById('global-status');

let currentQrcodeId = null;
let pollTimer = null;

// ── 已保存 Token 管理 ──

async function checkSavedWechatToken() {
  const data = await safeFetch('/bridge/wechat/saved-token');
  if (data && data.has_saved_token && data.info) {
    wechatSavedCard.style.display = 'block';
    const info = data.info;
    wechatSavedInfo.textContent = `Bot ID: ${info.bot_id || '未知'} | 保存时间: ${info.saved_at || '未知'}`;
  } else {
    wechatSavedCard.style.display = 'none';
  }
}

if (wechatClearTokenBtn) {
  wechatClearTokenBtn.addEventListener('click', async () => {
    if (!confirm('确定要清除保存的 Token 吗？下次需要重新扫码登录。')) return;
    const data = await safeFetch('/bridge/wechat/clear-token', { method: 'POST' });
    if (data && data.ok) {
      showToast('Token 已清除', 'success');
      wechatSavedCard.style.display = 'none';
    } else {
      showToast('清除失败', 'error');
    }
  });
}

function updateWechatUI(status, error) {
  const light = wechatLight;
  const badge = wechatBadge;
  const label = wechatStatusLabel;
  const detail = wechatStatusDetail;
  const globalIndicator = globalStatus.querySelector('.status-indicator');
  const globalText = globalStatus.querySelector('.status-text');

  light.className = 'status-light';
  badge.className = 'badge';

  switch (status) {
    case 'connected':
      light.classList.add('light-online');
      badge.classList.add('badge-online');
      badge.textContent = '已连接';
      label.textContent = '微信已连接';
      detail.textContent = '消息将自动路由到 Agent';
      wechatDisconnectBtn.style.display = 'inline-flex';
      wechatTokenForm.style.display = 'none';
      wechatQrBtn.style.display = 'none';
      globalIndicator.className = 'status-indicator status-online';
      globalText.textContent = '系统已连接';
      break;
    case 'connecting':
      light.classList.add('light-connecting');
      badge.classList.add('badge-connecting');
      badge.textContent = '连接中';
      label.textContent = '正在连接...';
      detail.textContent = '正在与微信服务器建立连接';
      wechatDisconnectBtn.style.display = 'inline-flex';
      globalIndicator.className = 'status-indicator status-connecting';
      globalText.textContent = '连接中...';
      break;
    case 'error':
      light.classList.add('light-error');
      badge.classList.add('badge-error');
      badge.textContent = '连接错误';
      label.textContent = '连接失败';
      detail.textContent = error || '未知错误';
      wechatDisconnectBtn.style.display = 'none';
      wechatTokenForm.style.display = 'block';
      wechatQrBtn.style.display = 'inline-flex';
      globalIndicator.className = 'status-indicator status-error';
      globalText.textContent = '连接错误';
      break;
    default:
      badge.classList.add('badge-offline');
      badge.textContent = '未连接';
      label.textContent = '等待连接';
      detail.textContent = '请通过下方方式连接微信';
      wechatDisconnectBtn.style.display = 'none';
      wechatTokenForm.style.display = 'block';
      wechatQrBtn.style.display = 'inline-flex';
      globalIndicator.className = 'status-indicator status-offline';
      globalText.textContent = '系统未连接';
  }
}

async function fetchBridgeStatus() {
  try {
    const response = await fetch('/bridge/status');
    const status = await response.json();
    const wechat = status.wechat;
    updateWechatUI(wechat?.status || 'disconnected', wechat?.error);
  } catch (err) {
    updateWechatUI('disconnected');
  }
}

wechatTokenForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(wechatTokenForm);

  wechatConnectBtn.classList.add('loading');
  wechatConnectBtn.disabled = true;
  wechatResult.textContent = '';
  wechatResult.className = 'form-result';

  try {
    const response = await fetch('/bridge/wechat/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bot_token: formData.get('bot_token'),
        agent_id: formData.get('agent_id') || null,
      }),
    });
    const data = await response.json();

    if (data.status === 'connected' || data.status === 'connecting') {
      wechatResult.textContent = '连接成功！';
      wechatResult.className = 'form-result success';
      wechatTokenForm.reset();
      showToast('微信连接成功', 'success');
    } else {
      wechatResult.textContent = `连接失败: ${data.error || data.status}`;
      wechatResult.className = 'form-result error';
    }
  } catch (err) {
    wechatResult.textContent = `错误: ${err.message}`;
    wechatResult.className = 'form-result error';
  }

  wechatConnectBtn.classList.remove('loading');
  wechatConnectBtn.disabled = false;
  await fetchBridgeStatus();
});

wechatDisconnectBtn.addEventListener('click', async () => {
  try {
    await fetch('/bridge/wechat/disconnect', { method: 'POST' });
    showToast('已断开微信连接', 'info');
  } catch (err) {
    showToast(`断开失败: ${err.message}`, 'error');
  }
  await fetchBridgeStatus();
});

// ── 二维码登录 ──

wechatQrBtn.addEventListener('click', async () => {
  wechatQrContainer.style.display = 'block';
  wechatQrBtn.style.display = 'none';
  wechatQrStatus.textContent = '正在获取二维码...';

  try {
    const response = await fetch('/bridge/wechat/qrcode');
    const data = await response.json();

    if (data.ok) {
      wechatQrImage.src = data.qrcode_url;
      currentQrcodeId = data.qrcode_id;
      wechatQrStatus.textContent = '请使用微信扫描二维码';
      startQrcodePolling();
    } else {
      wechatQrStatus.textContent = `获取失败: ${data.error}`;
    }
  } catch (err) {
    wechatQrStatus.textContent = `错误: ${err.message}`;
  }
});

function startQrcodePolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollQrcodeStatus, 3000);
}

async function pollQrcodeStatus() {
  if (!currentQrcodeId) return;

  try {
    const response = await fetch('/bridge/wechat/qrcode/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qrcode_id: currentQrcodeId }),
    });
    const data = await response.json();

    switch (data.status) {
      case 'scanned':
        wechatQrStatus.textContent = '已扫码，请在手机上确认...';
        break;
      case 'confirmed':
        clearInterval(pollTimer);
        pollTimer = null;
        wechatQrStatus.textContent = '登录成功，正在连接...';
        if (data.bot_token) {
          try {
            const resp = await fetch('/bridge/wechat/connect', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ bot_token: data.bot_token }),
            });
            const connectData = await resp.json();
            if (connectData.status === 'connected' || connectData.status === 'connecting') {
              showToast('微信连接成功！正在跳转到对话...', 'success');
              // 自动跳转到对话页面
              setTimeout(() => {
                const chatNav = document.querySelector('.nav-item[data-section="chat"]');
                if (chatNav) chatNav.click();
              }, 1000);
            } else {
              showToast(`连接失败: ${connectData.error || '未知错误'}`, 'error');
            }
          } catch (err) {
            showToast(`连接请求失败: ${err.message}`, 'error');
          }
        }
        currentQrcodeId = null;
        await fetchBridgeStatus();
        break;
      case 'expired':
        clearInterval(pollTimer);
        pollTimer = null;
        wechatQrStatus.textContent = '二维码已过期，请重新获取';
        currentQrcodeId = null;
        break;
      case 'error':
        clearInterval(pollTimer);
        pollTimer = null;
        wechatQrStatus.textContent = `错误: ${data.error}`;
        currentQrcodeId = null;
        break;
    }
  } catch (err) {
    console.error('QR poll error:', err);
  }
}

// ── Agent 状态 ──

async function fetchAgentStatus() {
  const status = await safeFetch('/agents/status');
  if (!status || typeof status !== 'object') return;
  try {

    // OpenHanako
    const hana = status.openhanako || {};
    const hanaBadge = document.getElementById('openhanako-badge');
    const hanaDetail = document.getElementById('openhanako-detail');
    if (hanaBadge) {
      if (hana.status === 'configured' || hana.status === 'connected') {
        hanaBadge.className = 'badge badge-online';
        hanaBadge.textContent = '运行中';
        if (hanaDetail) hanaDetail.textContent = hana.url || '';
      } else {
        hanaBadge.className = 'badge badge-offline';
        hanaBadge.textContent = '未运行';
        if (hanaDetail) hanaDetail.textContent = `期望地址: ${hana.url || '未配置'}`;
      }
    }

    // OpenClaw
    const claw = status.openclaw || {};
    const clawBadge = document.getElementById('openclaw-badge');
    const clawDetail = document.getElementById('openclaw-detail');
    if (clawBadge) {
      if (claw.status === 'configured') {
        clawBadge.className = 'badge badge-configured';
        clawBadge.textContent = '已配置';
        if (clawDetail) clawDetail.textContent = claw.url || '';
      } else {
        clawBadge.className = 'badge badge-offline';
        clawBadge.textContent = '未配置';
        if (clawDetail) clawDetail.textContent = '设置 OPENCLAW_URL 环境变量';
      }
    }

    // Hermes
    const hermes = status.hermes || {};
    const hermesBadge = document.getElementById('hermes-badge');
    const hermesDetail = document.getElementById('hermes-detail');
    if (hermesBadge) {
      if (hermes.status === 'configured') {
        hermesBadge.className = 'badge badge-configured';
        hermesBadge.textContent = '已配置';
        if (hermesDetail) hermesDetail.textContent = hermes.url || hermes.cli || '';
      } else {
        hermesBadge.className = 'badge badge-offline';
        hermesBadge.textContent = '未配置';
        if (hermesDetail) hermesDetail.textContent = '设置 HERMES_URL 或 HERMES_CLI_COMMAND';
      }
    }
  } catch (err) {
    console.error('Failed to fetch agent status:', err);
  }
}

// ── 任务管理 ──

const taskForm = document.getElementById('task-form');
const taskList = document.getElementById('task-list');
const submitResult = document.getElementById('submit-result');
const submitTaskBtn = document.getElementById('submit-task-btn');
const refreshTasksBtn = document.getElementById('refresh-tasks');

async function fetchTasks() {
  try {
    const response = await fetch('/tasks');
    const tasks = await response.json();

    if (tasks.length === 0) {
      taskList.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          <p>暂无任务</p>
        </div>`;
      return;
    }

    const agentNames = { openclaw: 'OpenClaw', hermes: 'Hermes', openhanako: 'OpenHanako', auto: '自动' };

    taskList.innerHTML = tasks.map(task => `
      <div class="task-item">
        <div class="task-item-head">
          <span class="task-goal">${escapeHtml(task.goal)}</span>
          <div class="btn-group">
            <span class="badge badge-${task.status}">${statusLabel(task.status)}</span>
            ${task.status === 'running' || task.status === 'pending' || task.status === 'waiting' ? `
              <button class="btn btn-ghost btn-xs" onclick="cancelTask('${task.id}')" title="取消任务">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            ` : ''}
            ${task.status === 'failed' ? `
              <button class="btn btn-ghost btn-xs" onclick="retryTask('${task.id}')" title="重试任务">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
              </button>
            ` : ''}
          </div>
        </div>
        <div class="task-meta">
          <span>请求: ${agentNames[task.requested_agent] || task.requested_agent}</span>
          <span>分配: ${agentNames[task.selected_agent] || task.selected_agent}</span>
          <span>${escapeHtml(task.routing_reason)}</span>
        </div>
        ${task.result_payload || task.error_message ? `
          <div class="task-result">${escapeHtml(task.result_payload || task.error_message)}</div>
        ` : ''}
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to fetch tasks:', err);
  }
}

function statusLabel(status) {
  const labels = {
    pending: '等待中', running: '执行中', waiting: '排队中',
    success: '已完成', failed: '失败',
  };
  return labels[status] || status;
}

taskForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(taskForm);

  submitTaskBtn.classList.add('loading');
  submitTaskBtn.disabled = true;
  submitResult.textContent = '';
  submitResult.className = 'form-result';

  try {
    const response = await fetch('/submit-task', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        goal: formData.get('goal'),
        requested_agent: formData.get('requested_agent'),
      }),
    });
    const data = await response.json();

    submitResult.textContent = `任务已提交，分配到 ${data.selected_agent}`;
    submitResult.className = 'form-result success';
    taskForm.reset();
    showToast('任务提交成功', 'success');
    await fetchTasks();
  } catch (err) {
    submitResult.textContent = `提交失败: ${err.message}`;
    submitResult.className = 'form-result error';
  }

  submitTaskBtn.classList.remove('loading');
  submitTaskBtn.disabled = false;
});

refreshTasksBtn.addEventListener('click', fetchTasks);

async function cancelTask(taskId) {
  if (!confirm('确定要取消这个任务吗？')) return;
  try {
    await fetch(`/tasks/${taskId}/cancel`, { method: 'POST' });
    showToast('任务已取消', 'info');
    await fetchTasks();
  } catch (err) {
    showToast(`取消失败: ${err.message}`, 'error');
  }
}

async function retryTask(taskId) {
  try {
    await fetch(`/tasks/${taskId}/retry`, { method: 'POST' });
    showToast('任务已重新提交', 'success');
    await fetchTasks();
  } catch (err) {
    showToast(`重试失败: ${err.message}`, 'error');
  }
}

// ── 消息记录 ──

const messageList = document.getElementById('message-list');
const refreshMessagesBtn = document.getElementById('refresh-messages');
const messagePagination = document.getElementById('message-pagination');

let msgPage = 1;
const msgPageSize = 30;
let msgTotal = 0;

async function fetchMessages(page = 1) {
  msgPage = page;
  const offset = (page - 1) * msgPageSize;
  if (!messageList) return;
  const data = await safeFetch(`/bridge/messages?limit=${msgPageSize}&offset=${offset}`);
  // 支持两种返回格式：直接数组 或 {messages: [], total: N}
  const messages = Array.isArray(data) ? data : ((data && data.messages) || []);
  msgTotal = Array.isArray(data) ? messages.length : ((data && data.total) || messages.length);
  try {

    if (messages.length === 0) {
      messageList.innerHTML = `
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
          <p>暂无消息</p>
        </div>`;
      if (messagePagination) messagePagination.innerHTML = '';
      return;
    }
    messageList.innerHTML = messages.map(msg => {
      const isIn = msg.direction === 'in';
      const time = new Date(msg.ts * 1000).toLocaleTimeString('zh-CN');
      return `
        <div class="message-item">
          <div class="message-head">
            <span class="message-direction ${isIn ? 'dir-in' : 'dir-out'}">
              ${isIn ? '← 收到' : '→ 发送'} · ${msg.platform}
            </span>
            <span class="message-time">${time}</span>
          </div>
          <div class="message-text">${escapeHtml(msg.text)}</div>
        </div>`;
    }).join('');
    messageList.scrollTop = messageList.scrollHeight;
    // 分页
    if (messagePagination) {
      const totalPages = Math.ceil(msgTotal / msgPageSize) || 1;
      renderPagination(messagePagination, page, totalPages, (p) => fetchMessages(p));
    }
  } catch (err) {
    console.error('Failed to fetch messages:', err);
  }
}

refreshMessagesBtn.addEventListener('click', () => fetchMessages(msgPage));

// ── 系统提示词编辑 ──

const orchestratorPrompt = document.getElementById('orchestrator-prompt');
const savePromptBtn = document.getElementById('save-prompt-btn');
const resetPromptBtn = document.getElementById('reset-prompt-btn');
const promptSaveStatus = document.getElementById('prompt-save-status');

async function fetchOrchestratorPrompt() {
  try {
    const response = await fetch('/agents/prompt');
    const data = await response.json();
    if (data.system_prompt) {
      orchestratorPrompt.value = data.system_prompt;
    }
  } catch (err) {
    orchestratorPrompt.value = '加载失败';
  }
}

if (savePromptBtn) {
  savePromptBtn.addEventListener('click', async () => {
    const prompt = orchestratorPrompt.value.trim();
    if (!prompt) {
      showToast('提示词不能为空', 'error');
      return;
    }

    savePromptBtn.classList.add('loading');
    savePromptBtn.disabled = true;

    try {
      const response = await fetch('/agents/prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system_prompt: prompt }),
      });
      const data = await response.json();

      if (data.ok) {
        showToast('提示词已保存', 'success');
        promptSaveStatus.textContent = '已保存';
        promptSaveStatus.className = 'prompt-hint success';
        setTimeout(() => {
          promptSaveStatus.textContent = '';
          promptSaveStatus.className = 'prompt-hint';
        }, 3000);
      } else {
        showToast('保存失败', 'error');
      }
    } catch (err) {
      showToast(`保存失败: ${err.message}`, 'error');
    }

    savePromptBtn.classList.remove('loading');
    savePromptBtn.disabled = false;
  });
}

if (resetPromptBtn) {
  resetPromptBtn.addEventListener('click', async () => {
    if (!confirm('确定要恢复默认提示词吗？当前编辑的内容将丢失。')) {
      return;
    }

    try {
      const response = await fetch('/agents/prompt/reset', { method: 'POST' });
      const data = await response.json();

      if (data.ok) {
        showToast('已恢复默认提示词', 'success');
        await fetchOrchestratorPrompt();
      } else {
        showToast('恢复失败', 'error');
      }
    } catch (err) {
      showToast(`恢复失败: ${err.message}`, 'error');
    }
  });
}

// ── 智能发现 ──

const sourceList = document.getElementById('source-list');
const discoveryList = document.getElementById('discovery-list');
const scanHistory = document.getElementById('scan-history');
const scanDiscoveryBtn = document.getElementById('scan-discovery-btn');
const refreshDiscoveryBtn = document.getElementById('refresh-discovery');
const clearDiscoveryBtn = document.getElementById('clear-discovery-btn');

async function fetchDiscoverySources() {
  try {
    const response = await fetch('/discovery/sources');
    const sources = await response.json();

    if (sources.length === 0) {
      sourceList.innerHTML = `
        <div class="empty-state" style="padding: 16px;">
          <p>未配置任务来源</p>
          <span class="form-help">设置 DISCOVERY_SCAN_DIRS 等环境变量启用自动发现</span>
        </div>`;
      return;
    }

    sourceList.innerHTML = sources.map(s => `
      <div class="source-item">
        <div class="source-info">
          <div class="source-icon ${s.enabled ? 'source-icon-active' : 'source-icon-inactive'}">
            ${s.name.charAt(0)}
          </div>
          <span class="source-name">${escapeHtml(s.name)}</span>
        </div>
        <span class="source-status">${s.enabled ? '已启用' : '未启用'}</span>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to fetch discovery sources:', err);
  }
}

async function fetchDiscoveryPending() {
  if (!discoveryList) return;
  const tasks = await safeFetch('/discovery/pending');
  if (!Array.isArray(tasks) || tasks.length === 0) {
    discoveryList.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        <p>暂无待处理任务</p>
      </div>`;
    return;
  }
  try {

    const priorityLabels = { low: '低', normal: '普通', high: '高', urgent: '紧急' };
    const typeLabels = {
      bug_fix: '修bug', feature: '新功能', research: '调研',
      code_review: '代码审查', documentation: '文档', maintenance: '维护', custom: '自定义'
    };

    discoveryList.innerHTML = tasks.map(t => `
      <div class="discovery-item">
        <div class="discovery-info">
          <div class="discovery-goal">${escapeHtml(t.goal)}</div>
          <div class="discovery-meta">
            <span>来源: ${escapeHtml(t.source)}</span>
            <span>类型: ${typeLabels[t.task_type] || t.task_type}</span>
            <span>优先级: ${priorityLabels[t.priority] || t.priority}</span>
            <span>建议Agent: ${t.suggested_agent}</span>
          </div>
        </div>
        <div class="discovery-actions">
          <button class="btn btn-primary btn-sm" onclick="takeDiscoveryTask('${t.id}')">执行</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to fetch discovery pending:', err);
  }
}

async function takeDiscoveryTask(taskId) {
  try {
    const response = await fetch(`/discovery/take/${taskId}`, { method: 'POST' });
    const data = await response.json();
    if (data.ok) {
      showToast('任务已取走', 'success');
      await fetchDiscoveryPending();
      await fetchTasks();
    }
  } catch (err) {
    showToast(`操作失败: ${err.message}`, 'error');
  }
}

async function fetchScanHistory() {
  if (!scanHistory) return;
  const history = await safeFetch('/discovery/history');
  if (!Array.isArray(history) || history.length === 0) {
    scanHistory.innerHTML = `
      <div class="empty-state" style="padding: 16px;">
        <p>暂无扫描记录</p>
      </div>`;
    return;
  }
  try {
    scanHistory.innerHTML = history.reverse().map(h => {
      const time = new Date(h.time).toLocaleString('zh-CN');
      const sourceStats = Object.entries(h.sources || {}).map(([k, v]) => {
        if (v.error) return `${k}: 错误`;
        return `${k}: 发现${v.found}个, 新${v.new}个`;
      }).join(', ');

      return `
        <div class="scan-item">
          <span class="scan-time">${time}</span>
          <div class="scan-result">
            <span class="scan-stat">新任务: ${h.new_tasks}</span>
            <span class="scan-stat">${sourceStats || '无来源'}</span>
          </div>
        </div>`;
    }).join('');
  } catch (err) {
    console.error('Failed to fetch scan history:', err);
  }
}

if (scanDiscoveryBtn) {
  scanDiscoveryBtn.addEventListener('click', async () => {
    scanDiscoveryBtn.classList.add('loading');
    scanDiscoveryBtn.disabled = true;

    try {
      const response = await fetch('/discovery/scan', { method: 'POST' });
      const data = await response.json();
      showToast(`扫描完成，发现 ${data.new_tasks} 个新任务`, 'success');
      await fetchDiscoveryPending();
      await fetchScanHistory();
    } catch (err) {
      showToast(`扫描失败: ${err.message}`, 'error');
    }

    scanDiscoveryBtn.classList.remove('loading');
    scanDiscoveryBtn.disabled = false;
  });
}

if (refreshDiscoveryBtn) {
  refreshDiscoveryBtn.addEventListener('click', async () => {
    await fetchDiscoverySources();
    await fetchDiscoveryPending();
    await fetchScanHistory();
  });
}

if (clearDiscoveryBtn) {
  clearDiscoveryBtn.addEventListener('click', async () => {
    if (!confirm('确定要清空所有待处理任务吗？')) return;

    try {
      const response = await fetch('/discovery/clear', { method: 'POST' });
      const data = await response.json();
      showToast(`已清空 ${data.cleared} 个任务`, 'info');
      await fetchDiscoveryPending();
    } catch (err) {
      showToast(`清空失败: ${err.message}`, 'error');
    }
  });
}

// ── 执行监控 ──

const monitorStats = document.getElementById('monitor-stats');
const agentExecStats = document.getElementById('agent-exec-stats');
const executionHistory = document.getElementById('execution-history');
const refreshMonitorBtn = document.getElementById('refresh-monitor');
const cleanupMonitorBtn = document.getElementById('cleanup-monitor-btn');

async function fetchMonitorStatus() {
  try {
    const response = await fetch('/monitor/status');
    const stats = await response.json();

    document.getElementById('stat-running').textContent = stats.running || 0;
    document.getElementById('stat-retrying').textContent = stats.retrying || 0;
    document.getElementById('stat-completed').textContent = stats.completed || 0;
    document.getElementById('stat-failed').textContent = stats.failed || 0;
  } catch (err) {
    console.error('Failed to fetch monitor status:', err);
  }
}

async function fetchAgentExecStats() {
  try {
    const response = await fetch('/monitor/agent-stats');
    const stats = await response.json();
    const agentNames = { openclaw: 'OpenClaw', hermes: 'Hermes', openhanako: 'OpenHanako' };

    if (Object.keys(stats).length === 0) {
      agentExecStats.innerHTML = `
        <div class="empty-state" style="padding: 16px;">
          <p>暂无执行数据</p>
        </div>`;
      return;
    }

    agentExecStats.innerHTML = Object.entries(stats).map(([name, s]) => `
      <div class="agent-stat-card">
        <div class="agent-stat-header">
          <span class="agent-stat-name">${agentNames[name] || name}</span>
          <span class="badge badge-${s.success_rate >= 80 ? 'online' : s.success_rate >= 50 ? 'configured' : 'error'}">${s.success_rate}%</span>
        </div>
        <div class="agent-stat-details">
          <span>总计: ${s.total_tasks}</span>
          <span>成功: ${s.completed_tasks}</span>
          <span>失败: ${s.failed_tasks}</span>
          <span>平均耗时: ${s.avg_duration}s</span>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to fetch agent exec stats:', err);
  }
}

async function fetchExecutionHistory() {
  if (!executionHistory) return;
  const history = await safeFetch('/monitor/history?limit=20');
  if (!Array.isArray(history) || history.length === 0) {
    executionHistory.innerHTML = `
      <div class="empty-state" style="padding: 16px;">
        <p>暂无执行记录</p>
      </div>`;
    return;
  }
  try {
    const eventLabels = {
      started: '开始执行', completed: '执行完成', failed: '执行失败',
      retrying: '重试中', timeout: '超时', cancelled: '已取消'
    };

    executionHistory.innerHTML = history.reverse().map(h => {
      const time = new Date(h.timestamp).toLocaleString('zh-CN');
      const duration = h.duration ? `${h.duration.toFixed(1)}s` : '-';
      const isError = h.event === 'failed' || h.event === 'timeout';

      return `
        <div class="history-item ${isError ? 'history-error' : ''}">
          <div class="history-head">
            <span class="history-event badge badge-${isError ? 'error' : h.event === 'completed' ? 'success' : 'configured'}">
              ${eventLabels[h.event] || h.event}
            </span>
            <span class="history-time">${time}</span>
          </div>
          <div class="history-details">
            <span>Agent: ${h.agent}</span>
            <span>任务: ${h.task_id.substring(0, 8)}...</span>
            <span>耗时: ${duration}</span>
            ${h.retry_count > 0 ? `<span>重试: ${h.retry_count}</span>` : ''}
          </div>
          ${h.error ? `<div class="history-error-msg">${escapeHtml(h.error)}</div>` : ''}
        </div>`;
    }).join('');
  } catch (err) {
    console.error('Failed to fetch execution history:', err);
  }
}

if (refreshMonitorBtn) {
  refreshMonitorBtn.addEventListener('click', async () => {
    await fetchMonitorStatus();
    await fetchAgentExecStats();
    await fetchExecutionHistory();
  });
}

if (cleanupMonitorBtn) {
  cleanupMonitorBtn.addEventListener('click', async () => {
    if (!confirm('确定要清理已完成的执行记录吗？')) return;

    try {
      const response = await fetch('/monitor/cleanup', { method: 'POST' });
      const data = await response.json();
      showToast(`已清理 ${data.removed} 条记录`, 'info');
      await fetchMonitorStatus();
      await fetchExecutionHistory();
    } catch (err) {
      showToast(`清理失败: ${err.message}`, 'error');
    }
  });
}

// ── 健康状态 ──

const healthDetailList = document.getElementById('health-detail-list');
const recoveryHistory = document.getElementById('recovery-history');
const healthCheckBtn = document.getElementById('health-check-btn');

async function fetchHealthSummary() {
  try {
    const response = await fetch('/health/summary');
    const stats = await response.json();

    document.getElementById('health-healthy').textContent = stats.healthy || 0;
    document.getElementById('health-degraded').textContent = stats.degraded || 0;
    document.getElementById('health-unhealthy').textContent = stats.unhealthy || 0;
    document.getElementById('health-unknown').textContent = stats.unknown || 0;
  } catch (err) {
    console.error('Failed to fetch health summary:', err);
  }
}

async function fetchHealthDetail() {
  try {
    const response = await fetch('/health/status');
    const states = await response.json();
    const agentNames = { openclaw: 'OpenClaw', hermes: 'Hermes', openhanako: 'OpenHanako' };
    const statusIcons = { healthy: '✓', degraded: '⚠', unhealthy: '✗', unknown: '?' };
    const statusColors = { healthy: 'success', degraded: 'warning', unhealthy: 'error', unknown: 'offline' };

    if (Object.keys(states).length === 0) {
      healthDetailList.innerHTML = `
        <div class="empty-state" style="padding: 16px;">
          <p>暂无健康数据</p>
        </div>`;
      return;
    }

    healthDetailList.innerHTML = Object.entries(states).map(([name, s]) => `
      <div class="health-detail-card">
        <div class="health-detail-header">
          <span class="health-agent-name">${agentNames[name] || name}</span>
          <span class="badge badge-${statusColors[s.status]}">
            ${statusIcons[s.status]} ${s.status}
          </span>
        </div>
        <div class="health-detail-body">
          <div class="health-stat-row">
            <span>连续失败: ${s.consecutive_failures}</span>
            <span>总检查: ${s.total_checks}</span>
            <span>总失败: ${s.total_failures}</span>
          </div>
          <div class="health-stat-row">
            <span>平均延迟: ${s.avg_latency_ms}ms</span>
            <span>恢复动作: ${s.recovery_action}</span>
          </div>
          ${s.last_check ? `<div class="health-stat-row"><span>上次检查: ${new Date(s.last_check).toLocaleString('zh-CN')}</span></div>` : ''}
          ${s.error_history && s.error_history.length > 0 ? `
            <div class="health-errors">
              <span class="health-errors-label">最近错误:</span>
              ${s.error_history.slice(-3).map(e => `<div class="health-error-item">${escapeHtml(e)}</div>`).join('')}
            </div>
          ` : ''}
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to fetch health detail:', err);
  }
}

async function fetchRecoveryHistory() {
  if (!recoveryHistory) return;
  const history = await safeFetch('/health/history');
  if (!Array.isArray(history) || history.length === 0) {
    recoveryHistory.innerHTML = `
      <div class="empty-state" style="padding: 16px;">
        <p>暂无恢复记录</p>
      </div>`;
    return;
  }
  try {
    recoveryHistory.innerHTML = history.reverse().map(h => {
      const time = new Date(h.timestamp).toLocaleString('zh-CN');
      return `
        <div class="recovery-item">
          <div class="recovery-head">
            <span class="badge badge-${h.success ? 'success' : 'error'}">
              ${h.success ? '成功' : '失败'}
            </span>
            <span class="recovery-time">${time}</span>
          </div>
          <div class="recovery-details">
            <span>Agent: ${h.agent}</span>
            <span>动作: ${h.action}</span>
            ${h.error ? `<span>错误: ${escapeHtml(h.error)}</span>` : ''}
          </div>
        </div>`;
    }).join('');
  } catch (err) {
    console.error('Failed to fetch recovery history:', err);
  }
}

if (healthCheckBtn) {
  healthCheckBtn.addEventListener('click', async () => {
    healthCheckBtn.classList.add('loading');
    healthCheckBtn.disabled = true;

    try {
      await fetch('/health/check', { method: 'POST' });
      showToast('健康检查完成', 'success');
      await fetchHealthSummary();
      await fetchHealthDetail();
      await fetchRecoveryHistory();
    } catch (err) {
      showToast(`检查失败: ${err.message}`, 'error');
    }

    healthCheckBtn.classList.remove('loading');
    healthCheckBtn.disabled = false;
  });
}

// ── 技能库 ──

const skillList = document.getElementById('skill-list');
const skillCount = document.getElementById('skill-count');
const skillPagination = document.getElementById('skill-pagination');
const skillSearch = document.getElementById('skill-search');
const skillStatusFilter = document.getElementById('skill-status-filter');
const skillAgentFilter = document.getElementById('skill-agent-filter');
const refreshSkillsBtn = document.getElementById('refresh-skills');
const analyzeSkillsBtn = document.getElementById('analyze-skills-btn');

let allSkills = [];
let skillPage = 1;
const skillPageSize = 10;
let selectedSkillIds = new Set();

async function fetchSkillStats() {
  try {
    const response = await fetch('/skills/stats');
    const stats = await response.json();

    document.getElementById('skill-total').textContent = stats.total_skills || 0;
    document.getElementById('skill-active').textContent = stats.active_skills || 0;
    document.getElementById('skill-draft').textContent = stats.draft_skills || 0;
    document.getElementById('skill-success-rate').textContent = `${stats.overall_success_rate || 0}%`;
  } catch (err) {
    console.error('Failed to fetch skill stats:', err);
  }
}

function filterSkills() {
  const search = (skillSearch?.value || '').toLowerCase();
  const status = skillStatusFilter?.value || '';
  const agent = skillAgentFilter?.value || '';

  return allSkills.filter(s => {
    if (search && !s.name.toLowerCase().includes(search) && !s.description.toLowerCase().includes(search)) {
      return false;
    }
    if (status && s.status !== status) return false;
    if (agent && !s.preferred_agents.includes(agent)) return false;
    return true;
  });
}

function renderSkills() {
  const filtered = filterSkills();
  const totalPages = Math.ceil(filtered.length / skillPageSize);
  const start = (skillPage - 1) * skillPageSize;
  const paged = filtered.slice(start, start + skillPageSize);

  skillCount.textContent = `${filtered.length} 项`;

  // 显示/隐藏批量操作按钮
  const batchDeleteBtn = document.getElementById('skill-batch-delete');
  const selectAllBtn = document.getElementById('skill-select-all');
  if (batchDeleteBtn) batchDeleteBtn.style.display = selectedSkillIds.size > 0 ? 'inline-flex' : 'none';
  if (selectAllBtn) selectAllBtn.textContent = selectedSkillIds.size === paged.length && paged.length > 0 ? '取消全选' : '全选';

  if (paged.length === 0) {
    skillList.innerHTML = `
      <div class="empty-state">
        <p>暂无技能</p>
        <span class="form-help">点击"分析历史"从已完成的任务中自动提取技能</span>
      </div>`;
    skillPagination.innerHTML = '';
    return;
  }

  const statusLabels = { draft: '草稿', active: '已激活', disabled: '已禁用', archived: '已归档' };
  const statusColors = { draft: 'configured', active: 'success', disabled: 'offline', archived: 'offline' };

  skillList.innerHTML = paged.map(s => `
    <div class="skill-item" data-id="${s.id}">
      <div class="skill-header">
        <div style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" class="skill-select" data-id="${s.id}" ${selectedSkillIds.has(s.id) ? 'checked' : ''}>
          <span class="skill-name">${escapeHtml(s.name)}</span>
        </div>
        <span class="badge badge-${statusColors[s.status]}">${statusLabels[s.status]}</span>
      </div>
      <div class="skill-desc">${escapeHtml(s.description)}</div>
      <div class="skill-meta">
        <span>使用: ${s.total_uses}次</span>
        <span>成功率: ${s.success_rate}%</span>
        <span>来源: ${s.source}</span>
        ${s.preferred_agents.length > 0 ? `<span>Agent: ${s.preferred_agents.join(', ')}</span>` : ''}
      </div>
      <div class="skill-actions">
        ${s.status === 'draft' ? `<button class="btn btn-success btn-sm" onclick="activateSkill('${s.id}')">启用</button>` : ''}
        ${s.status === 'active' ? `<button class="btn btn-outline btn-sm" onclick="disableSkill('${s.id}')">禁用</button>` : ''}
        ${s.status === 'disabled' ? `<button class="btn btn-success btn-sm" onclick="activateSkill('${s.id}')">启用</button>` : ''}
        <button class="btn btn-ghost btn-sm" onclick="deleteSkill('${s.id}')" title="删除">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
        </button>
      </div>
    </div>
  `).join('');

  // 绑定复选框事件
  document.querySelectorAll('.skill-select').forEach(cb => {
    cb.addEventListener('change', () => {
      if (cb.checked) {
        selectedSkillIds.add(cb.dataset.id);
      } else {
        selectedSkillIds.delete(cb.dataset.id);
      }
      renderSkills();
    });
  });

  renderPagination(skillPagination, skillPage, totalPages, (page) => {
    skillPage = page;
    renderSkills();
  });
}

async function fetchSkills() {
  try {
    const response = await fetch('/skills');
    allSkills = await response.json();
    skillPage = 1;
    renderSkills();
  } catch (err) {
    console.error('Failed to fetch skills:', err);
  }
}

async function activateSkill(skillId) {
  try {
    await fetch(`/skills/${skillId}/activate`, { method: 'POST' });
    showToast('技能已激活', 'success');
    await fetchSkills();
    await fetchSkillStats();
  } catch (err) {
    showToast(`操作失败: ${err.message}`, 'error');
  }
}

async function disableSkill(skillId) {
  try {
    await fetch(`/skills/${skillId}/disable`, { method: 'POST' });
    showToast('技能已禁用', 'info');
    await fetchSkills();
    await fetchSkillStats();
  } catch (err) {
    showToast(`操作失败: ${err.message}`, 'error');
  }
}

async function deleteSkill(skillId) {
  if (!confirm('确定要删除这个技能吗？')) return;
  try {
    await fetch(`/skills/${skillId}`, { method: 'DELETE' });
    showToast('技能已删除', 'info');
    await fetchSkills();
    await fetchSkillStats();
  } catch (err) {
    showToast(`操作失败: ${err.message}`, 'error');
  }
}

if (analyzeSkillsBtn) {
  analyzeSkillsBtn.addEventListener('click', async () => {
    analyzeSkillsBtn.classList.add('loading');
    analyzeSkillsBtn.disabled = true;

    try {
      const response = await fetch('/replay/generate', { method: 'POST' });
      const data = await response.json();
      showToast(`生成了 ${data.count} 个技能提案`, 'success');
      await fetchSkills();
      await fetchSkillStats();
      await fetchPendingReviews();
    } catch (err) {
      showToast(`分析失败: ${err.message}`, 'error');
    }

    analyzeSkillsBtn.classList.remove('loading');
    analyzeSkillsBtn.disabled = false;
  });
}

if (refreshSkillsBtn) {
  refreshSkillsBtn.addEventListener('click', async () => {
    await fetchSkills();
    await fetchSkillStats();
  });
}

// 技能搜索和过滤
if (skillSearch) skillSearch.addEventListener('input', () => { skillPage = 1; renderSkills(); });
if (skillStatusFilter) skillStatusFilter.addEventListener('change', () => { skillPage = 1; renderSkills(); });
if (skillAgentFilter) skillAgentFilter.addEventListener('change', () => { skillPage = 1; renderSkills(); });

// 技能全选/批量删除
document.getElementById('skill-select-all')?.addEventListener('click', () => {
  const paged = filterSkills().slice((skillPage - 1) * skillPageSize, skillPage * skillPageSize);
  if (selectedSkillIds.size === paged.length) {
    selectedSkillIds.clear();
  } else {
    paged.forEach(s => selectedSkillIds.add(s.id));
  }
  renderSkills();
});

document.getElementById('skill-batch-delete')?.addEventListener('click', async () => {
  if (selectedSkillIds.size === 0) return;
  if (!confirm(`确定要删除选中的 ${selectedSkillIds.size} 个技能吗？`)) return;

  for (const id of selectedSkillIds) {
    try { await fetch(`/skills/${id}`, { method: 'DELETE' }); } catch (e) {}
  }
  selectedSkillIds.clear();
  showToast('批量删除完成', 'success');
  await fetchSkills();
  await fetchSkillStats();
});

// ── 技能 ZIP 拖拽上传 ──

function setupDropzone(dropzoneId, fileInputId, uploadUrl, acceptExts, onSuccess) {
  const dropzone = document.getElementById(dropzoneId);
  const fileInput = document.getElementById(fileInputId);
  if (!dropzone || !fileInput) return;

  // 点击触发文件选择
  dropzone.addEventListener('click', () => fileInput.click());

  // 拖拽事件
  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('drag-over');
  });
  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('drag-over');
  });
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    const files = e.dataTransfer.files;
    if (files.length > 0) handleUpload(files[0]);
  });

  // 文件选择
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      handleUpload(fileInput.files[0]);
      fileInput.value = '';
    }
  });

  async function handleUpload(file) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!acceptExts.includes(ext)) {
      showToast(`不支持的文件类型 ${ext}，请上传 ${acceptExts.join(', ')}`, 'error');
      return;
    }

    dropzone.classList.add('uploading');
    dropzone.querySelector('p').textContent = `正在安装 ${file.name}...`;

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(uploadUrl, { method: 'POST', body: formData });
      const data = await response.json();

      if (response.ok && data.ok) {
        showToast(data.message || '安装成功', 'success');
        if (onSuccess) await onSuccess();
      } else {
        showToast(data.detail || data.error || '安装失败', 'error');
      }
    } catch (err) {
      showToast(`上传失败: ${err.message}`, 'error');
    } finally {
      dropzone.classList.remove('uploading');
      dropzone.querySelector('p').innerHTML = dropzoneId === 'skill-dropzone'
        ? '拖拽 <strong>.zip</strong> 或 <strong>.skill</strong> 文件到此处安装技能'
        : '拖拽 <strong>.zip</strong> 文件到此处安装插件';
    }
  }
}

setupDropzone('skill-dropzone', 'skill-file-input', '/skills/upload', ['.zip', '.skill'], async () => {
  await fetchSkills();
  await fetchSkillStats();
});

setupDropzone('plugin-dropzone', 'plugin-file-input', '/plugins/upload', ['.zip'], async () => {
  await fetchPlugins();
  await fetchPluginStats();
});

// ── 插件管理 ──

const pluginList = document.getElementById('plugin-list');
const pluginCount = document.getElementById('plugin-count');
const pluginPagination = document.getElementById('plugin-pagination');
const pluginSearch = document.getElementById('plugin-search');
const pluginStatusFilter = document.getElementById('plugin-status-filter');
const pluginSafeFilter = document.getElementById('plugin-safe-filter');
const capabilityMap = document.getElementById('capability-map');
const refreshPluginsBtn = document.getElementById('refresh-plugins');

let allPlugins = [];
let pluginPage = 1;
const pluginPageSize = 10;
let selectedPluginIds = new Set();

async function fetchPluginStats() {
  try {
    const response = await fetch('/plugins/stats');
    const stats = await response.json();

    document.getElementById('plugin-total').textContent = stats.total_plugins || 0;
    document.getElementById('plugin-active').textContent = stats.active_plugins || 0;
    document.getElementById('plugin-capabilities').textContent = Object.keys(stats.capabilities || {}).length;
    document.getElementById('plugin-success-rate').textContent = `${stats.overall_success_rate || 0}%`;
  } catch (err) {
    console.error('Failed to fetch plugin stats:', err);
  }
}

function filterPlugins() {
  const search = (pluginSearch?.value || '').toLowerCase();
  const status = pluginStatusFilter?.value || '';
  const safe = pluginSafeFilter?.value || '';

  return allPlugins.filter(p => {
    if (search && !p.display_name.toLowerCase().includes(search) && !p.description.toLowerCase().includes(search)) {
      // 也搜索能力名称
      const capMatch = p.capability_names.some(c => c.toLowerCase().includes(search));
      if (!capMatch) return false;
    }
    if (status && p.status !== status) return false;
    if (safe && p.safe_level !== safe) return false;
    return true;
  });
}

function renderPlugins() {
  const filtered = filterPlugins();
  const totalPages = Math.ceil(filtered.length / pluginPageSize);
  const start = (pluginPage - 1) * pluginPageSize;
  const paged = filtered.slice(start, start + pluginPageSize);

  pluginCount.textContent = `${filtered.length} 项`;

  // 显示/隐藏批量操作按钮
  const batchDeleteBtn = document.getElementById('plugin-batch-delete');
  const selectAllBtn = document.getElementById('plugin-select-all');
  if (batchDeleteBtn) batchDeleteBtn.style.display = selectedPluginIds.size > 0 ? 'inline-flex' : 'none';
  if (selectAllBtn) selectAllBtn.textContent = selectedPluginIds.size === paged.length && paged.length > 0 ? '取消全选' : '全选';

  if (paged.length === 0) {
    pluginList.innerHTML = `
      <div class="empty-state">
        <p>暂无插件</p>
      </div>`;
    pluginPagination.innerHTML = '';
    return;
  }

  const safeLabels = { low: '低风险', medium: '中风险', high: '高风险' };
  const safeColors = { low: 'success', medium: 'configured', high: 'error' };

  pluginList.innerHTML = paged.map(p => `
    <div class="plugin-item" data-id="${p.id}">
      <div class="plugin-header">
        <div style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" class="plugin-select" data-name="${p.name}" ${selectedPluginIds.has(p.name) ? 'checked' : ''}>
          <span class="plugin-name">${escapeHtml(p.display_name)}</span>
        </div>
        <span class="badge badge-${p.status === 'active' ? 'success' : 'offline'}">${p.status === 'active' ? '已启用' : '未启用'}</span>
      </div>
      <div class="plugin-desc">${escapeHtml(p.description)}</div>
      <div class="plugin-meta">
        <span>版本: ${p.version}</span>
        <span class="badge badge-${safeColors[p.safe_level]}">${safeLabels[p.safe_level]}</span>
        <span>能力: ${p.capability_names.join(', ') || '无'}</span>
        ${p.allowed_agents.length > 0 ? `<span>Agent: ${p.allowed_agents.join(', ')}</span>` : ''}
      </div>
      <div class="plugin-stats-row">
        <span>使用: ${p.total_uses}次</span>
        <span>成功率: ${p.success_rate}%</span>
        ${p.fallback_plugins.length > 0 ? `<span>Fallback: ${p.fallback_plugins.join(', ')}</span>` : ''}
      </div>
      <div class="plugin-actions">
        <button class="btn btn-ghost btn-sm" onclick="deletePlugin('${p.name}')" title="卸载插件">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          卸载
        </button>
      </div>
    </div>
  `).join('');

  // 绑定复选框事件
  document.querySelectorAll('.plugin-select').forEach(cb => {
    cb.addEventListener('change', () => {
      if (cb.checked) {
        selectedPluginIds.add(cb.dataset.name);
      } else {
        selectedPluginIds.delete(cb.dataset.name);
      }
      renderPlugins();
    });
  });

  renderPagination(pluginPagination, pluginPage, totalPages, (page) => {
    pluginPage = page;
    renderPlugins();
  });
}

async function fetchPlugins() {
  const data = await safeFetch('/plugins');
  allPlugins = Array.isArray(data) ? data : [];
  pluginPage = 1;
  renderPlugins();
}

async function fetchCapabilityMap() {
  try {
    const response = await fetch('/plugins/capabilities');
    const capabilities = await response.json();

    if (Object.keys(capabilities).length === 0) {
      capabilityMap.innerHTML = `
        <div class="empty-state" style="padding: 16px;">
          <p>暂无能力数据</p>
        </div>`;
      return;
    }

    capabilityMap.innerHTML = Object.entries(capabilities).map(([cap, plugins]) => `
      <div class="capability-item">
        <span class="capability-name">${escapeHtml(cap)}</span>
        <span class="capability-plugins">${plugins.join(', ')}</span>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to fetch capability map:', err);
  }
}

if (refreshPluginsBtn) {
  refreshPluginsBtn.addEventListener('click', async () => {
    await fetchPlugins();
    await fetchPluginStats();
    await fetchCapabilityMap();
  });
}

// 插件搜索和过滤
if (pluginSearch) pluginSearch.addEventListener('input', () => { pluginPage = 1; renderPlugins(); });
if (pluginStatusFilter) pluginStatusFilter.addEventListener('change', () => { pluginPage = 1; renderPlugins(); });
if (pluginSafeFilter) pluginSafeFilter.addEventListener('change', () => { pluginPage = 1; renderPlugins(); });

// 插件卸载
async function deletePlugin(pluginName) {
  if (!confirm('确定要卸载这个插件吗？')) return;
  try {
    await fetch(`/plugins/files/${pluginName}`, { method: 'DELETE' });
    showToast('插件已卸载', 'success');
    await fetchPlugins();
    await fetchPluginStats();
    await fetchCapabilityMap();
  } catch (err) {
    showToast(`卸载失败: ${err.message}`, 'error');
  }
}

// 插件全选/批量删除
document.getElementById('plugin-select-all')?.addEventListener('click', () => {
  const paged = filterPlugins().slice((pluginPage - 1) * pluginPageSize, pluginPage * pluginPageSize);
  if (selectedPluginIds.size === paged.length) {
    selectedPluginIds.clear();
  } else {
    paged.forEach(p => selectedPluginIds.add(p.name));
  }
  renderPlugins();
});

document.getElementById('plugin-batch-delete')?.addEventListener('click', async () => {
  if (selectedPluginIds.size === 0) return;
  if (!confirm(`确定要卸载选中的 ${selectedPluginIds.size} 个插件吗？`)) return;

  for (const name of selectedPluginIds) {
    try { await fetch(`/plugins/files/${name}`, { method: 'DELETE' }); } catch (e) {}
  }
  selectedPluginIds.clear();
  showToast('批量卸载完成', 'success');
  await fetchPlugins();
  await fetchPluginStats();
  await fetchCapabilityMap();
});

// 安装插件按钮触发 dropzone
document.getElementById('install-plugin-btn')?.addEventListener('click', () => {
  document.getElementById('plugin-file-input')?.click();
});

// ── 进化审查 ──

const pendingReviews = document.getElementById('pending-reviews');
const pendingCount = document.getElementById('pending-count');
const reviewHistory = document.getElementById('review-history');
const historyCount = document.getElementById('history-count');
const reviewPagination = document.getElementById('review-pagination');
const reviewSearch = document.getElementById('review-search');
const reviewStatusFilter = document.getElementById('review-status-filter');
const reviewRiskFilter = document.getElementById('review-risk-filter');
const refreshEvolutionBtn = document.getElementById('refresh-evolution');
const generateSkillsBtn = document.getElementById('generate-skills-btn');

let allReviews = [];
let reviewPage = 1;
const reviewPageSize = 10;

async function fetchEvolutionStats() {
  try {
    const response = await fetch('/evolution/stats');
    const stats = await response.json();

    document.getElementById('evo-pending').textContent = stats.pending || 0;
    document.getElementById('evo-approved').textContent = stats.approved || 0;
    document.getElementById('evo-rejected').textContent = stats.rejected || 0;
    document.getElementById('evo-rules').textContent = stats.total_rules || 0;
  } catch (err) {
    console.error('Failed to fetch evolution stats:', err);
  }
}

function filterReviews(reviews) {
  const search = (reviewSearch?.value || '').toLowerCase();
  const status = reviewStatusFilter?.value || '';
  const risk = reviewRiskFilter?.value || '';

  return reviews.filter(r => {
    if (search && !r.skill_name.toLowerCase().includes(search)) return false;
    if (status && r.status !== status) return false;
    if (risk && r.risk_level !== risk) return false;
    return true;
  });
}

function renderPendingReviews(reviews) {
  if (!Array.isArray(reviews)) reviews = [];
  const filtered = reviews.filter(r => r.status === 'pending');
  if (pendingCount) pendingCount.textContent = `${filtered.length} 项`;

  if (filtered.length === 0) {
    if (pendingReviews) pendingReviews.innerHTML = `
      <div class="empty-state" style="padding: 16px;">
        <p>暂无待审查技能</p>
      </div>`;
    return;
  }

  // 批量操作按钮
  const batchActions = `
    <div class="batch-actions">
      <button class="btn btn-outline btn-sm" onclick="selectAllReviews()">全选</button>
      <button class="btn btn-primary btn-sm" onclick="batchApproveReviews()">批量批准</button>
      <button class="btn btn-danger btn-sm" onclick="batchRejectReviews()">批量拒绝</button>
      <button class="btn btn-outline btn-sm" onclick="autoApproveSuggestions()">自动批准建议</button>
    </div>
  `;

  if (pendingReviews) pendingReviews.innerHTML = batchActions + filtered.map(r => `
    <div class="review-item">
      <div class="review-checkbox">
        <input type="checkbox" class="review-select" data-id="${r.id}">
      </div>
      <div class="review-content">
        <div class="review-header">
          <span class="review-name">${escapeHtml(r.skill_name)}</span>
          <span class="badge badge-${r.risk_level === 'high' ? 'error' : r.risk_level === 'medium' ? 'configured' : 'success'}">
            ${r.risk_level} 风险
          </span>
          ${r.auto_approve_suggestion ? '<span class="badge badge-success">建议批准</span>' : ''}
        </div>
        <div class="review-meta">
          <span>触发规则: ${(r.triggered_rules || []).length}条</span>
          <span>安全检查: ${(r.safety_checks || []).length}项</span>
          <span>提交时间: ${new Date(r.submitted_at).toLocaleString('zh-CN')}</span>
        </div>
        ${r.suggestion_reason ? `<div class="review-suggestion">建议: ${escapeHtml(r.suggestion_reason)}</div>` : ''}
        ${(r.risk_factors || []).length > 0 ? `
          <div class="review-risks">
            <span class="review-risks-label">风险因素:</span>
            ${(r.risk_factors || []).map(f => `<div class="review-risk-item">${escapeHtml(f)}</div>`).join('')}
          </div>
        ` : ''}
        <div class="review-actions">
          <button class="btn btn-primary btn-sm" onclick="approveReview('${r.id}')">批准</button>
          <button class="btn btn-danger btn-sm" onclick="rejectReview('${r.id}')">拒绝</button>
        </div>
      </div>
    </div>
  `).join('');
}

function renderReviewHistory(reviews) {
  if (!Array.isArray(reviews)) reviews = [];
  const completed = reviews.filter(r => r.status !== 'pending');
  const filtered = filterReviews(completed);
  const totalPages = Math.ceil(filtered.length / reviewPageSize);
  const start = (reviewPage - 1) * reviewPageSize;
  const paged = filtered.slice(start, start + reviewPageSize);

  if (historyCount) historyCount.textContent = `${filtered.length} 项`;

  if (paged.length === 0) {
    if (reviewHistory) reviewHistory.innerHTML = `
      <div class="empty-state" style="padding: 16px;">
        <p>暂无审查记录</p>
      </div>`;
    if (reviewPagination) reviewPagination.innerHTML = '';
    return;
  }

  const statusLabels = { approved: '已批准', rejected: '已拒绝', needs_info: '需补充' };
  const statusColors = { approved: 'success', rejected: 'error', needs_info: 'configured' };

  if (reviewHistory) reviewHistory.innerHTML = paged.map(r => `
    <div class="review-item review-completed">
      <div class="review-header">
        <span class="review-name">${escapeHtml(r.skill_name)}</span>
        <span class="badge badge-${statusColors[r.status]}">${statusLabels[r.status]}</span>
      </div>
      <div class="review-meta">
        <span>审查者: ${r.reviewer || '系统'}</span>
        <span>时间: ${r.reviewed_at ? new Date(r.reviewed_at).toLocaleString('zh-CN') : '-'}</span>
      </div>
      ${r.review_notes ? `<div class="review-notes">${escapeHtml(r.review_notes)}</div>` : ''}
    </div>
  `).join('');

  if (reviewPagination) renderPagination(reviewPagination, reviewPage, totalPages, (page) => {
    reviewPage = page;
    renderReviewHistory(allReviews);
  });
}

async function fetchPendingReviews() {
  const data = await safeFetch('/evolution/pending');
  renderPendingReviews(Array.isArray(data) ? data : []);
}

async function fetchReviewHistory() {
  const data = await safeFetch('/evolution/reviews?limit=50');
  allReviews = Array.isArray(data) ? data : [];
  reviewPage = 1;
  renderReviewHistory(allReviews);
}

async function approveReview(reviewId) {
  try {
    await fetch(`/evolution/reviews/${reviewId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: 'Approved from dashboard' }),
    });
    showToast('技能已批准并激活', 'success');
    await fetchPendingReviews();
    await fetchReviewHistory();
    await fetchEvolutionStats();
    await fetchSkills();
    await fetchSkillStats();
  } catch (err) {
    showToast(`操作失败: ${err.message}`, 'error');
  }
}

async function rejectReview(reviewId) {
  const notes = prompt('请输入拒绝原因（可选）:');
  if (notes === null) return;

  try {
    await fetch(`/evolution/reviews/${reviewId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes }),
    });
    showToast('技能已拒绝', 'info');
    await fetchPendingReviews();
    await fetchReviewHistory();
    await fetchEvolutionStats();
  } catch (err) {
    showToast(`操作失败: ${err.message}`, 'error');
  }
}

if (generateSkillsBtn) {
  generateSkillsBtn.addEventListener('click', async () => {
    generateSkillsBtn.classList.add('loading');
    generateSkillsBtn.disabled = true;

    try {
      const response = await fetch('/replay/generate', { method: 'POST' });
      const data = await response.json();
      showToast(`生成了 ${data.count} 个技能提案`, 'success');
      await fetchPendingReviews();
      await fetchReviewHistory();
      await fetchEvolutionStats();
    } catch (err) {
      showToast(`生成失败: ${err.message}`, 'error');
    }

    generateSkillsBtn.classList.remove('loading');
    generateSkillsBtn.disabled = false;
  });
}

if (refreshEvolutionBtn) {
  refreshEvolutionBtn.addEventListener('click', async () => {
    await fetchPendingReviews();
    await fetchReviewHistory();
    await fetchEvolutionStats();
  });
}

// ── 批量操作 ──

function selectAllReviews() {
  const checkboxes = document.querySelectorAll('.review-select');
  const allChecked = Array.from(checkboxes).every(cb => cb.checked);
  checkboxes.forEach(cb => { cb.checked = !allChecked; });
}

function getSelectedReviewIds() {
  return Array.from(document.querySelectorAll('.review-select:checked'))
    .map(cb => cb.dataset.id);
}

async function batchApproveReviews() {
  const ids = getSelectedReviewIds();
  if (ids.length === 0) {
    showToast('请先选择要批准的技能', 'info');
    return;
  }

  try {
    const response = await fetch('/evolution/batch/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ review_ids: ids, notes: 'Batch approved from dashboard' }),
    });
    const data = await response.json();
    showToast(`已批准 ${data.count} 个技能`, 'success');
    await fetchPendingReviews();
    await fetchReviewHistory();
    await fetchEvolutionStats();
    await fetchSkills();
    await fetchSkillStats();
  } catch (err) {
    showToast(`批量批准失败: ${err.message}`, 'error');
  }
}

async function batchRejectReviews() {
  const ids = getSelectedReviewIds();
  if (ids.length === 0) {
    showToast('请先选择要拒绝的技能', 'info');
    return;
  }

  const notes = prompt('请输入拒绝原因（可选）:');
  if (notes === null) return;

  try {
    const response = await fetch('/evolution/batch/reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ review_ids: ids, notes }),
    });
    const data = await response.json();
    showToast(`已拒绝 ${data.count} 个技能`, 'info');
    await fetchPendingReviews();
    await fetchReviewHistory();
    await fetchEvolutionStats();
  } catch (err) {
    showToast(`批量拒绝失败: ${err.message}`, 'error');
  }
}

async function autoApproveSuggestions() {
  try {
    const response = await fetch('/evolution/auto-approve', { method: 'POST' });
    const data = await response.json();
    showToast(`自动批准了 ${data.count} 个低风险技能`, 'success');
    await fetchPendingReviews();
    await fetchReviewHistory();
    await fetchEvolutionStats();
    await fetchSkills();
    await fetchSkillStats();
  } catch (err) {
    showToast(`自动批准失败: ${err.message}`, 'error');
  }
}

// 审查搜索和过滤
if (reviewSearch) reviewSearch.addEventListener('input', () => { reviewPage = 1; renderReviewHistory(allReviews); });
if (reviewStatusFilter) reviewStatusFilter.addEventListener('change', () => { reviewPage = 1; renderReviewHistory(allReviews); });
if (reviewRiskFilter) reviewRiskFilter.addEventListener('change', () => { reviewPage = 1; renderReviewHistory(allReviews); });

// ── 工具函数 ──

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ── AI 对话 ──

const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSendBtn = document.getElementById('chat-send-btn');
const chatModelName = document.getElementById('chat-model-name');
const clearChatBtn = document.getElementById('clear-chat-btn');

let chatHistory = [];
let isSending = false;
let selectedAgent = '';  // '' = iliya (default)

// ── Agent 选择器 ──

const chatAgentBtns = document.querySelectorAll('.chat-agent-btn');
const agentPlaceholders = {
  '': '和 iliya 说点什么吧...',
  'openhanako': '跟 OpenHanako 说点什么吧...',
  'openclaw': '跟 OpenClaw 说点什么吧...',
  'hermes': '跟 Hermes 说点什么吧...',
};

chatAgentBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    chatAgentBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedAgent = btn.dataset.agent;
    chatInput.placeholder = agentPlaceholders[selectedAgent] || agentPlaceholders[''];
  });
});

// 自动调整输入框高度
chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  chatSendBtn.disabled = !chatInput.value.trim();
});

// 发送消息
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
});

chatSendBtn.addEventListener('click', sendChatMessage);

clearChatBtn.addEventListener('click', async () => {
  if (!confirm('确定要清空所有对话记录吗？')) return;
  try {
    await fetch('/chat/clear', { method: 'POST' });
    chatHistory = [];
    renderChatMessages();
    showToast('对话已清空', 'success');
  } catch (err) {
    showToast('清空失败: ' + err.message, 'error');
  }
});

async function sendChatMessage() {
  const content = chatInput.value.trim();
  if (!content || isSending) return;

  isSending = true;
  chatSendBtn.disabled = true;
  chatInput.value = '';
  chatInput.style.height = 'auto';

  // 添加用户消息到界面
  const userMsg = { id: 'temp_' + Date.now(), role: 'user', content, timestamp: new Date().toISOString() };
  chatHistory.push(userMsg);
  renderChatMessages();

  // 显示输入中状态
  showTypingIndicator();

  try {
    const resp = await fetch('/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: content, agent_name: selectedAgent || undefined }),
    });
    const data = await resp.json();

    // 移除输入中状态
    hideTypingIndicator();

    if (data.error) {
      showToast(data.error, 'error');
    }

    // 添加助手回复
    if (data.assistant_message) {
      chatHistory.push(data.assistant_message);
    }

    renderChatMessages();
    updateChatModelStatus();
  } catch (err) {
    hideTypingIndicator();
    showToast('发送失败: ' + err.message, 'error');
  } finally {
    isSending = false;
    chatSendBtn.disabled = !chatInput.value.trim();
  }
}

function renderChatMessages() {
  if (chatHistory.length === 0) {
    chatMessages.innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-avatar">
          <span>iliya</span>
        </div>
        <h3>主人好呀～</h3>
        <p>我是 iliya，你的专属小甜妹！请先在「模型配置」中添加模型供应商，然后就可以和我聊天啦～</p>
      </div>`;
    return;
  }

  chatMessages.innerHTML = chatHistory.map(msg => {
    const isUser = msg.role === 'user';
    const time = new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    // 检测是否包含子 Agent 标识
    const agentMatch = !isUser && msg.content.match(/^\[(\w+)\]/);
    const agentTag = agentMatch ? agentMatch[1] : '';
    const avatarText = isUser ? '你' : (agentTag || 'I');
    const agentColors = { OpenClaw: '#3B82F6', OpenHanako: '#10B981', Hermes: '#8B5CF6' };
    const avatarStyle = agentTag && agentColors[agentTag]
      ? `style="background: linear-gradient(135deg, ${agentColors[agentTag]}, ${agentColors[agentTag]}dd);"`
      : '';
    const displayContent = agentMatch ? msg.content.replace(/^\[\w+\]\s*/, '') : msg.content;
    return `
      <div class="chat-message ${msg.role}">
        <div class="chat-avatar" ${avatarStyle}>${avatarText}</div>
        <div>
          ${agentTag ? `<div class="chat-agent-tag" style="color: ${agentColors[agentTag] || '#E8608C'}">${agentTag} 回复</div>` : ''}
          <div class="chat-bubble">${escapeHtml(displayContent)}</div>
          <div class="chat-message-time">${time}</div>
        </div>
      </div>`;
  }).join('');

  // 平滑滚动到底部
  requestAnimationFrame(() => {
    chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: 'smooth' });
  });
}

function showTypingIndicator() {
  const indicator = document.createElement('div');
  indicator.className = 'chat-message assistant';
  indicator.id = 'typing-indicator';
  indicator.innerHTML = `
    <div class="chat-avatar">I</div>
    <div class="chat-bubble">
      <div class="chat-typing">
        <div class="chat-typing-dot"></div>
        <div class="chat-typing-dot"></div>
        <div class="chat-typing-dot"></div>
      </div>
    </div>`;
  chatMessages.appendChild(indicator);
  requestAnimationFrame(() => {
    chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: 'smooth' });
  });
}

function hideTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  if (indicator) indicator.remove();
}

async function updateChatModelStatus() {
  if (!chatModelName) return;
  const data = await safeFetch('/model/active');
  if (data && data.model) {
    chatModelName.textContent = `${data.provider_id || ''} (${data.model || '未选模型'})`;
  } else {
    chatModelName.textContent = '未配置模型';
  }
}

async function loadChatHistory() {
  const data = await safeFetch('/chat/history');
  chatHistory = Array.isArray(data) ? data : [];
  renderChatMessages();
  updateChatModelStatus();
}

// ── 模型配置（OpenHanako 风格）──

const mcProviderList = document.getElementById('mc-provider-list');
const mcDetail = document.getElementById('mc-detail');
const mcDetailContent = document.getElementById('mc-detail-content');
const mcDetailEmpty = mcDetail?.querySelector('.mc-detail-empty');
const mcDetailName = document.getElementById('mc-detail-name');
const mcApiKey = document.getElementById('mc-api-key');
const mcApiBase = document.getElementById('mc-api-base');
const mcApiFormat = document.getElementById('mc-api-format');
const mcActiveModel = document.getElementById('mc-active-model');
const mcTemperature = document.getElementById('mc-temperature');
const mcMaxTokens = document.getElementById('mc-max-tokens');
const mcModelList = document.getElementById('mc-model-list');
const mcCustomModelInput = document.getElementById('mc-custom-model-input');

let mcCurrentProviderId = null;
let mcCurrentProvider = null;

// 预设供应商点击
document.querySelectorAll('.mc-preset-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const preset = btn.dataset.preset;
    const data = await safeFetch('/model/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: preset, preset }),
    });
    if (data && data.id) {
      showToast('供应商已添加', 'success');
      await mcRefreshProviders();
      mcSelectProvider(data.id);
    } else {
      showToast('添加失败', 'error');
    }
  });
});

// 添加自定义供应商
document.getElementById('mc-add-custom-btn')?.addEventListener('click', async () => {
  const data = await safeFetch('/model/providers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: '自定义供应商', api_format: 'openai-completions' }),
  });
  if (data && data.id) {
    showToast('已添加自定义供应商', 'success');
    await mcRefreshProviders();
    mcSelectProvider(data.id);
  } else {
    showToast('添加失败', 'error');
  }
});

// 验证连接（先保存当前表单再验证）
document.getElementById('mc-verify-btn')?.addEventListener('click', async () => {
  if (!mcCurrentProviderId) return;
  const btn = document.getElementById('mc-verify-btn');
  btn.innerHTML = '<span class="btn-loading">验证中...</span>';
  btn.disabled = true;
  try {
    // 先保存当前表单数据
    const savePayload = {
      api_base: mcApiBase.value,
      api_format: mcApiFormat.value,
      active_model: mcActiveModel.value,
      temperature: parseFloat(mcTemperature.value),
      max_tokens: parseInt(mcMaxTokens.value),
    };
    if (mcApiKey.value) {
      savePayload.api_key = mcApiKey.value;
    }
    await safeFetch(`/model/providers/${mcCurrentProviderId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(savePayload),
    });
    // 再验证
    const data = await safeFetch(`/model/providers/${mcCurrentProviderId}/verify`, { method: 'POST' });
    if (data) {
      showToast(data.ok ? '连接验证成功' : '连接验证失败: ' + (data.error || ''), data.ok ? 'success' : 'error');
    } else {
      showToast('连接验证失败: 无响应', 'error');
    }
  } catch (err) {
    showToast('验证失败: ' + err.message, 'error');
  } finally {
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> 验证';
    btn.disabled = false;
  }
});

// 删除供应商
document.getElementById('mc-delete-btn')?.addEventListener('click', async () => {
  if (!mcCurrentProviderId) return;
  if (!confirm('确定要删除这个供应商吗？')) return;
  const data = await safeFetch(`/model/providers/${mcCurrentProviderId}`, { method: 'DELETE' });
  if (data && data.ok) {
    showToast('供应商已删除', 'success');
    mcCurrentProviderId = null;
    mcCurrentProvider = null;
    mcDetailContent.style.display = 'none';
    mcDetailEmpty.style.display = 'flex';
    mcRefreshProviders();
    updateChatModelStatus();
  } else {
    showToast('删除失败', 'error');
  }
});

// 获取模型列表
document.getElementById('mc-fetch-models-btn')?.addEventListener('click', async () => {
  if (!mcCurrentProviderId) return;
  showToast('正在获取模型列表...', 'info');
  const data = await safeFetch(`/model/providers/${mcCurrentProviderId}/fetch-models`, { method: 'POST' });
  if (data && data.models && data.models.length > 0) {
    // 合并到当前 provider 的 models
    const existingModels = mcCurrentProvider.models || [];
    const newModels = data.models.map(m => m.id).filter(id => !existingModels.includes(id));
    if (newModels.length > 0) {
      await safeFetch(`/model/providers/${mcCurrentProviderId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ models: [...existingModels, ...newModels] }),
      });
      showToast(`获取到 ${data.models.length} 个模型，新增 ${newModels.length} 个`, 'success');
      mcSelectProvider(mcCurrentProviderId);
    } else {
      showToast(`获取到 ${data.models.length} 个模型，无新增`, 'success');
    }
  } else {
    showToast((data && data.error) || '未获取到模型', 'error');
  }
});

// 添加自定义模型
document.getElementById('mc-add-model-btn')?.addEventListener('click', async () => {
  if (!mcCurrentProviderId || !mcCustomModelInput.value.trim()) return;
  const modelId = mcCustomModelInput.value.trim();
  const models = [...(mcCurrentProvider.models || []), modelId];
  const result = await safeFetch(`/model/providers/${mcCurrentProviderId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ models }),
  });
  if (result) {
    mcCustomModelInput.value = '';
    mcSelectProvider(mcCurrentProviderId);
    showToast('模型已添加', 'success');
  } else {
    showToast('添加失败', 'error');
  }
});

// 保存配置
document.getElementById('mc-save-btn')?.addEventListener('click', async () => {
  if (!mcCurrentProviderId) return;
  const btn = document.getElementById('mc-save-btn');
  btn.querySelector('.btn-text').style.display = 'none';
  btn.querySelector('.btn-loading').style.display = 'inline';
  btn.disabled = true;

  const payload = {
    api_base: mcApiBase.value,
    api_format: mcApiFormat.value,
    active_model: mcActiveModel.value,
    temperature: parseFloat(mcTemperature.value),
    max_tokens: parseInt(mcMaxTokens.value),
  };
  // 只有用户输入了新 key 才更新，避免空值覆盖
  if (mcApiKey.value) {
    payload.api_key = mcApiKey.value;
  }

  const data = await safeFetch(`/model/providers/${mcCurrentProviderId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (data) {
    showToast('配置已保存', 'success');
    mcSelectProvider(mcCurrentProviderId);
    updateChatModelStatus();
  } else {
    showToast('保存失败', 'error');
  }
  btn.querySelector('.btn-text').style.display = 'inline';
  btn.querySelector('.btn-loading').style.display = 'none';
  btn.disabled = false;
});

// API Key 显示/隐藏
document.getElementById('mc-key-toggle')?.addEventListener('click', () => {
  mcApiKey.type = mcApiKey.type === 'password' ? 'text' : 'password';
});

async function mcRefreshProviders() {
  const providers = await safeFetch('/model/providers');
  if (!providers || !Array.isArray(providers)) return;
  renderMcProviderList(providers);
}

function renderMcProviderList(providers) {
  if (providers.length === 0) {
    mcProviderList.innerHTML = '<div class="mc-empty-hint">暂无供应商</div>';
    return;
  }

  const presetIcons = {
    ollama: { letter: 'O', color: '#333' },
    openai: { letter: 'G', color: '#10a37f' },
    anthropic: { letter: 'A', color: '#d97757' },
    deepseek: { letter: 'D', color: '#4d6bfe' },
    dashscope: { letter: 'Q', color: '#615ea8' },
    moonshot: { letter: 'K', color: '#1a1a2e' },
    zhipu: { letter: 'Z', color: '#e53935' },
    siliconflow: { letter: 'S', color: '#6366f1' },
    groq: { letter: 'Gr', color: '#f55036' },
    minimax: { letter: 'Mi', color: '#0099ff' },
    volcengine: { letter: 'V', color: '#3f87f5' },
  };

  mcProviderList.innerHTML = providers.map(p => {
    const icon = presetIcons[p.preset] || { letter: p.name.charAt(0).toUpperCase(), color: '#6366f1' };
    const isActive = p.id === mcCurrentProviderId;
    return `
      <div class="mc-provider-item ${isActive ? 'active' : ''}" onclick="mcSelectProvider('${p.id}')">
        <div class="mc-provider-item-icon" style="background: ${icon.color};">${icon.letter}</div>
        <div class="mc-provider-item-info">
          <div class="mc-provider-item-name">${escapeHtml(p.name)}</div>
          <div class="mc-provider-item-model">${escapeHtml(p.active_model || '未选模型')}</div>
        </div>
      </div>`;
  }).join('');
}

async function mcSelectProvider(providerId) {
  mcCurrentProviderId = providerId;
  const data = await safeFetch(`/model/providers/${providerId}`);
  if (!data) {
    showToast('加载失败: 无法获取供应商信息', 'error');
    return;
  }
  mcCurrentProvider = data;

  // 显示详情
  mcDetailEmpty.style.display = 'none';
  mcDetailContent.style.display = 'block';

  // 填充表单
  mcDetailName.textContent = mcCurrentProvider.name;
  // api_key 在 to_dict() 中被脱敏，只有 api_key_masked
  // 如果有 masked 值说明已保存了 key，显示 placeholder 提示
  if (mcCurrentProvider.api_key_masked) {
    mcApiKey.value = '';
    mcApiKey.placeholder = `已保存 (${mcCurrentProvider.api_key_masked})，留空则不修改`;
  } else {
    mcApiKey.value = '';
    mcApiKey.placeholder = 'sk-...';
  }
  mcApiBase.value = mcCurrentProvider.api_base || '';
  mcApiFormat.value = mcCurrentProvider.api_format || 'openai-completions';
  mcTemperature.value = mcCurrentProvider.temperature ?? 0.7;
  mcMaxTokens.value = mcCurrentProvider.max_tokens ?? 4096;

  // 渲染模型列表
  const models = mcCurrentProvider.models || [];
  if (models.length === 0) {
    mcModelList.innerHTML = '<div class="mc-empty-hint">暂无模型</div>';
  } else {
    mcModelList.innerHTML = models.map(m => `
      <div class="mc-model-item">
        <span class="mc-model-item-name">${escapeHtml(m)}</span>
        <button class="mc-model-item-remove" onclick="mcRemoveModel('${escapeHtml(m)}')" title="移除">×</button>
      </div>`).join('');
  }

  // 更新活跃模型下拉
  mcActiveModel.innerHTML = '<option value="">请选择</option>' +
    models.map(m => `<option value="${escapeHtml(m)}" ${m === mcCurrentProvider.active_model ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('');

  // 更新高亮
  const allProviders = await safeFetch('/model/providers');
  if (allProviders && Array.isArray(allProviders)) {
    renderMcProviderList(allProviders);
  }
}

async function mcRemoveModel(modelId) {
  if (!mcCurrentProviderId || !mcCurrentProvider) return;
  const models = (mcCurrentProvider.models || []).filter(m => m !== modelId);
  const result = await safeFetch(`/model/providers/${mcCurrentProviderId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ models }),
  });
  if (result) {
    mcSelectProvider(mcCurrentProviderId);
    showToast('模型已移除', 'success');
  } else {
    showToast('移除失败', 'error');
  }
}

// ── MCP 工具 ──

let mcpServers = [];
let mcpSelectedServerId = '';
let mcpToolSchemas = {};

async function fetchMcpServers() {
  const data = await safeFetch('/mcp/servers');
  mcpServers = (data && data.servers) ? data.servers : [];
  renderMcpServers();
  updateMcpStats();
}

function updateMcpStats() {
  const total = mcpServers.length;
  const running = mcpServers.filter(s => s.status === 'running').length;
  const tools = mcpServers.reduce((sum, s) => sum + (s.tool_count || 0), 0);
  document.getElementById('mcp-stat-total').textContent = total;
  document.getElementById('mcp-stat-running').textContent = running;
  document.getElementById('mcp-stat-tools').textContent = tools;
}

function filterMcpServers() {
  const query = document.getElementById('mcp-search').value.toLowerCase();
  const filtered = mcpServers.filter(s =>
    s.name.toLowerCase().includes(query) ||
    s.command.toLowerCase().includes(query)
  );
  renderMcpServersList(filtered);
}

function renderMcpServers() {
  renderMcpServersList(mcpServers);
}

function renderMcpServersList(servers) {
  const container = document.getElementById('mcp-servers-list');
  if (!servers || servers.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
        <p>暂无 MCP Server，点击右上角添加</p>
      </div>`;
    return;
  }

  container.innerHTML = servers.map(s => {
    const statusClass = s.status === 'running' ? 'status-success' :
                        s.status === 'error' ? 'status-error' : 'status-idle';
    const statusText = s.status === 'running' ? '运行中' :
                       s.status === 'starting' ? '启动中' :
                       s.status === 'error' ? '错误' : '已停止';
    const toolCount = s.tool_count || 0;

    return `
      <div class="row" data-id="${s.id}">
        <div class="row-main">
          <div class="checkbox-col">
            <input type="checkbox" class="mcp-checkbox" data-id="${s.id}">
          </div>
          <div class="info-col">
            <div class="item-title">${escapeHtml(s.name)}</div>
            <div class="item-subtitle">
              <span class="status-tag ${statusClass}">${statusText}</span>
              <span style="margin-left: 8px; color: var(--text-muted); font-size: 12px;">
                ${escapeHtml(s.command)} ${escapeHtml((s.args || []).join(' '))}
              </span>
              ${toolCount > 0 ? `<span style="margin-left: 8px; color: var(--text-muted); font-size: 12px;">${toolCount} 个工具</span>` : ''}
            </div>
            ${s.error ? `<div style="color: var(--text-error); font-size: 12px; margin-top: 4px;">${escapeHtml(s.error)}</div>` : ''}
          </div>
          <div class="action-col">
            <div class="btn-group">
              ${s.status === 'running' ? `
                <button class="btn btn-ghost btn-xs" onclick="stopMcpServer('${s.id}')" title="停止">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12"/></svg>
                </button>
                <button class="btn btn-ghost btn-xs" onclick="showMcpToolPanel('${s.id}')" title="工具列表">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
                </button>
              ` : `
                <button class="btn btn-ghost btn-xs" onclick="startMcpServer('${s.id}')" title="启动" ${s.status === 'starting' ? 'disabled' : ''}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                </button>
              `}
              <button class="btn btn-ghost btn-xs btn-danger" onclick="deleteMcpServer('${s.id}')" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>`;
  }).join('');
}

async function showAddMcpDialog() {
  const name = prompt('Server 名称:', 'My MCP Server');
  if (!name) return;
  const command = prompt('启动命令:', 'node');
  if (!command) return;
  const argsStr = prompt('命令参数 (空格分隔):', '');
  const args = argsStr ? argsStr.split(/\s+/) : [];
  const cwd = prompt('工作目录 (可选):', '');

  const data = await safeFetch('/mcp/servers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, command, args, cwd })
  });
  if (data && data.server) {
    showToast('Server 已添加', 'success');
    fetchMcpServers();
  } else {
    showToast((data && data.error) || '添加失败', 'error');
  }
}

async function startMcpServer(serverId) {
  const data = await safeFetch(`/mcp/servers/${serverId}/start`, { method: 'POST' });
  if (data && data.ok) {
    showToast('Server 已启动', 'success');
    fetchMcpServers();
  } else {
    showToast((data && data.error) || '启动失败', 'error');
  }
}

async function stopMcpServer(serverId) {
  const data = await safeFetch(`/mcp/servers/${serverId}/stop`, { method: 'POST' });
  if (data && data.ok) {
    showToast('Server 已停止', 'success');
    fetchMcpServers();
  } else {
    showToast((data && data.error) || '停止失败', 'error');
  }
}

async function deleteMcpServer(serverId) {
  if (!confirm('确定要删除此 MCP Server？')) return;
  const data = await safeFetch(`/mcp/servers/${serverId}`, { method: 'DELETE' });
  if (data && data.ok) {
    showToast('Server 已删除', 'success');
    fetchMcpServers();
  } else {
    showToast((data && data.error) || '删除失败', 'error');
  }
}

async function showMcpToolPanel(serverId) {
  mcpSelectedServerId = serverId;
  const panel = document.getElementById('mcp-tool-panel');
  panel.style.display = 'block';

  // 填充 server 下拉
  const select = document.getElementById('mcp-tool-server');
  select.innerHTML = mcpServers
    .filter(s => s.status === 'running')
    .map(s => `<option value="${s.id}" ${s.id === serverId ? 'selected' : ''}>${escapeHtml(s.name)}</option>`)
    .join('');

  loadMcpToolList();
}

async function loadMcpToolList() {
  const serverId = document.getElementById('mcp-tool-server').value;
  if (!serverId) return;

  const select = document.getElementById('mcp-tool-name');
  select.innerHTML = '<option value="">加载中...</option>';

  const data = await safeFetch(`/mcp/servers/${serverId}/tools`);
  if (data && data.tools) {
    mcpToolSchemas[serverId] = data.tools;
    select.innerHTML = '<option value="">-- 选择工具 --</option>' +
      data.tools.map(t => `<option value="${t.name}">${escapeHtml(t.name)} — ${escapeHtml(t.description || '')}</option>`).join('');
  } else {
    select.innerHTML = '<option value="">无工具</option>';
    if (data && data.error) showToast(data.error, 'error');
  }
}

function showMcpToolSchema() {
  const serverId = document.getElementById('mcp-tool-server').value;
  const toolName = document.getElementById('mcp-tool-name').value;
  const infoDiv = document.getElementById('mcp-tool-schema-info');

  if (!serverId || !toolName) {
    infoDiv.style.display = 'none';
    return;
  }

  const tools = mcpToolSchemas[serverId] || [];
  const tool = tools.find(t => t.name === toolName);
  if (!tool) {
    infoDiv.style.display = 'none';
    return;
  }

  const schema = tool.inputSchema;
  if (schema && schema.properties) {
    const props = Object.entries(schema.properties).map(([k, v]) =>
      `<b>${k}</b>: ${v.type || 'any'}${v.description ? ' — ' + v.description : ''}`
    ).join('<br>');
    infoDiv.innerHTML = `<div style="margin-bottom: 4px; font-weight: 600;">参数说明:</div>${props}`;
    infoDiv.style.display = 'block';

    // 自动生成默认参数示例
    const defaults = {};
    Object.entries(schema.properties).forEach(([k, v]) => {
      if (v.type === 'string') defaults[k] = '';
      else if (v.type === 'number' || v.type === 'integer') defaults[k] = 0;
      else if (v.type === 'boolean') defaults[k] = false;
      else if (v.type === 'array') defaults[k] = [];
      else if (v.type === 'object') defaults[k] = {};
    });
    document.getElementById('mcp-tool-args').value = JSON.stringify(defaults, null, 2);
  } else {
    infoDiv.style.display = 'none';
    document.getElementById('mcp-tool-args').value = '{}';
  }
}

async function callMcpTool() {
  const serverId = document.getElementById('mcp-tool-server').value;
  const toolName = document.getElementById('mcp-tool-name').value;
  const argsStr = document.getElementById('mcp-tool-args').value;
  const resultDiv = document.getElementById('mcp-tool-result');

  if (!serverId || !toolName) {
    showToast('请选择 Server 和工具', 'error');
    return;
  }

  let args = {};
  try {
    args = JSON.parse(argsStr || '{}');
  } catch (e) {
    showToast('参数 JSON 格式错误', 'error');
    return;
  }

  resultDiv.style.display = 'block';
  resultDiv.textContent = '调用中...';

  const data = await safeFetch('/mcp/tools/call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server_id: serverId, tool_name: toolName, arguments: args })
  });
  if (data && data.ok) {
    resultDiv.textContent = data.content || JSON.stringify(data.raw, null, 2);
    resultDiv.style.borderLeft = '3px solid var(--color-success)';
  } else {
    resultDiv.textContent = '错误: ' + ((data && data.error) || '未知错误');
    resultDiv.style.borderLeft = '3px solid var(--color-error)';
  }
}

// ── MCP 聊天内测试 ──

let chatMcpPanelOpen = false;

function toggleChatMcpPanel() {
  chatMcpPanelOpen = !chatMcpPanelOpen;
  const panel = document.getElementById('chat-mcp-panel');
  const btn = document.getElementById('chat-mcp-toggle');
  panel.style.display = chatMcpPanelOpen ? 'block' : 'none';
  btn.classList.toggle('active', chatMcpPanelOpen);

  if (chatMcpPanelOpen) {
    // 填充 running 的 server 列表
    const select = document.getElementById('chat-mcp-server');
    const running = mcpServers.filter(s => s.status === 'running');
    select.innerHTML = '<option value="">-- 选择 Server --</option>' +
      running.map(s => `<option value="${s.id}">${escapeHtml(s.name)} (${s.tool_count || 0} 工具)</option>`).join('');

    if (running.length === 0) {
      document.getElementById('chat-mcp-hint').textContent = '⚠ 暂无运行中的 MCP Server，请先去「MCP 工具」页启动';
    } else {
      document.getElementById('chat-mcp-hint').textContent = `${running.length} 个 Server 可用`;
    }
  }
}

async function chatMcpLoadTools() {
  const serverId = document.getElementById('chat-mcp-server').value;
  const toolSelect = document.getElementById('chat-mcp-tool');
  if (!serverId) {
    toolSelect.innerHTML = '<option value="">-- 选择工具 --</option>';
    return;
  }

  toolSelect.innerHTML = '<option value="">加载中...</option>';

  const data = await safeFetch(`/mcp/servers/${serverId}/tools`);
  if (data && data.tools && data.tools.length > 0) {
    mcpToolSchemas[serverId] = data.tools;
    toolSelect.innerHTML = '<option value="">-- 选择工具 --</option>' +
      data.tools.map(t => `<option value="${t.name}">${escapeHtml(t.name)}</option>`).join('');
  } else {
    toolSelect.innerHTML = '<option value="">无可用工具</option>';
  }
}

function chatMcpShowSchema() {
  const serverId = document.getElementById('chat-mcp-server').value;
  const toolName = document.getElementById('chat-mcp-tool').value;
  const schemaDiv = document.getElementById('chat-mcp-schema');

  if (!serverId || !toolName) {
    schemaDiv.style.display = 'none';
    return;
  }

  const tools = mcpToolSchemas[serverId] || [];
  const tool = tools.find(t => t.name === toolName);
  if (!tool) { schemaDiv.style.display = 'none'; return; }

  const schema = tool.inputSchema;
  if (schema && schema.properties) {
    const props = Object.entries(schema.properties).map(([k, v]) =>
      `<b>${k}</b> (${v.type || 'any'})${v.description ? ' — ' + v.description : ''}`
    ).join('<br>');
    schemaDiv.innerHTML = props;
    schemaDiv.style.display = 'block';

    // 自动生成默认参数
    const defaults = {};
    Object.entries(schema.properties).forEach(([k, v]) => {
      if (v.type === 'string') defaults[k] = '';
      else if (v.type === 'number' || v.type === 'integer') defaults[k] = 0;
      else if (v.type === 'boolean') defaults[k] = false;
      else if (v.type === 'array') defaults[k] = [];
      else if (v.type === 'object') defaults[k] = {};
    });
    document.getElementById('chat-mcp-args').value = JSON.stringify(defaults, null, 2);
  } else {
    schemaDiv.style.display = 'none';
    document.getElementById('chat-mcp-args').value = '{}';
  }
}

async function chatMcpCallTool() {
  const serverId = document.getElementById('chat-mcp-server').value;
  const toolName = document.getElementById('chat-mcp-tool').value;
  const argsStr = document.getElementById('chat-mcp-args').value;
  const statusEl = document.getElementById('chat-mcp-status');
  const callBtn = document.getElementById('chat-mcp-call-btn');

  if (!serverId || !toolName) {
    showToast('请选择 Server 和工具', 'error');
    return;
  }

  let args = {};
  try {
    args = JSON.parse(argsStr || '{}');
  } catch (e) {
    showToast('参数 JSON 格式错误', 'error');
    return;
  }

  // 禁用按钮，显示状态
  callBtn.disabled = true;
  statusEl.textContent = '调用中...';

  // 在聊天中显示用户发起的工具调用
  const userMsg = { id: 'mcp_' + Date.now(), role: 'user', content: `[MCP] 调用 ${toolName}`, timestamp: new Date().toISOString() };
  chatHistory.push(userMsg);
  renderChatMessages();
  showTypingIndicator();

  const data = await safeFetch('/mcp/tools/call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server_id: serverId, tool_name: toolName, arguments: args })
  });

  hideTypingIndicator();

  if (data) {
    const resultContent = data.ok
      ? `[MCP ${toolName}]\n\n${data.content || JSON.stringify(data.raw, null, 2)}`
      : `[MCP 错误] ${data.error || '未知错误'}`;

    const botMsg = { id: 'mcp_resp_' + Date.now(), role: 'assistant', content: resultContent, timestamp: new Date().toISOString() };
    chatHistory.push(botMsg);
    renderChatMessages();

    statusEl.textContent = data.ok ? '调用成功' : '调用失败';
    setTimeout(() => { statusEl.textContent = ''; }, 3000);
  } else {
    const errMsg = { id: 'mcp_err_' + Date.now(), role: 'assistant', content: `[MCP 请求失败] 无响应`, timestamp: new Date().toISOString() };
    chatHistory.push(errMsg);
    renderChatMessages();
    statusEl.textContent = '请求失败';
  }
  callBtn.disabled = false;
}

// ── 初始化 ──

fetchBridgeStatus();
checkSavedWechatToken();
fetchAgentStatus();
fetchTasks();
fetchMessages();
fetchOrchestratorPrompt();
fetchDiscoverySources();
fetchDiscoveryPending();
fetchScanHistory();
fetchMonitorStatus();
fetchAgentExecStats();
fetchExecutionHistory();
fetchHealthSummary();
fetchHealthDetail();
fetchRecoveryHistory();
fetchSkills();
fetchSkillStats();
fetchPlugins();
fetchPluginStats();
fetchCapabilityMap();
fetchMcpServers();
fetchPendingReviews();
fetchReviewHistory();
fetchEvolutionStats();
mcRefreshProviders();
loadChatHistory();

setInterval(fetchBridgeStatus, 5000);
setInterval(fetchAgentStatus, 10000);
setInterval(fetchTasks, 3000);
setInterval(fetchMessages, 5000);
setInterval(fetchDiscoveryPending, 30000);
setInterval(fetchMonitorStatus, 10000);
setInterval(fetchHealthSummary, 30000);
setInterval(fetchSkillStats, 30000);
setInterval(fetchPendingReviews, 30000);
setInterval(updateChatModelStatus, 30000);
