// Mensarium control UI. Vanilla ES module, no build step, no dependencies.

const $main = document.getElementById('main');
const $toasts = document.getElementById('toasts');
const $modalRoot = document.getElementById('modal-root');
const $logoutBtn = document.getElementById('logout-btn');

let isAuthed = false;
let viewCleanup = [];

function onCleanup(fn) { viewCleanup.push(fn); }
function runCleanup() { viewCleanup.forEach((fn) => { try { fn(); } catch (err) { /* noop */ } }); viewCleanup = []; }

class AuthError extends Error {}

// ===== API =====

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
    ...opts,
  });
  if (res.status === 401) {
    isAuthed = false;
    throw new AuthError('unauthorized');
  }
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch (err) { data = text; } }
  if (!res.ok) {
    const msg = (data && data.detail) ? data.detail : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}
function apiGet(path) { return api(path); }
function apiPost(path, body) { return api(path, { method: 'POST', body: JSON.stringify(body || {}) }); }

async function safe(promise, fallback) {
  try { return await promise; }
  catch (err) {
    if (err instanceof AuthError) throw err;
    return fallback;
  }
}

// ===== Toast =====

function toast(message, isError = false) {
  const el = document.createElement('div');
  el.className = `toast${isError ? ' error' : ''}`;
  el.textContent = message;
  $toasts.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ===== Escaping / safe markdown-lite =====

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function renderMarkdownLite(text) {
  // Text is untrusted (model output). Escape first, then apply a minimal safe transform.
  let escaped = esc(text);
  escaped = escaped.replace(/```([\s\S]*?)```/g, (m, code) => `<pre>${code}</pre>`);
  escaped = escaped.replace(/`([^`\n]+)`/g, (m, code) => `<code class="inline">${code}</code>`);
  const parts = escaped.split(/(<pre>[\s\S]*?<\/pre>)/g);
  return parts.map((p) => (p.startsWith('<pre>') ? p : p.replace(/\n/g, '<br>'))).join('');
}

function relativeTime(iso) {
  if (!iso) return 'never';
  const diffSec = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (diffSec < 5) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const min = Math.round(diffSec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

function formatDuration(sec) {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

async function copyText(text, btn) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    const original = btn.textContent;
    btn.textContent = 'Copied';
    setTimeout(() => { btn.textContent = original; }, 1500);
  } catch (err) {
    toast('Copy failed', true);
  }
}

// ===== Badges =====

const TARGET_STATUS_BADGE = { online: 'ok', offline: 'neutral', revoked: 'danger' };
const RISK_BADGE = { read: 'neutral', write: 'warn', execute: 'orange', network: 'purple', destructive: 'danger' };
const TASK_STATUS_BADGE = {
  NEW: 'neutral', VALIDATING: 'neutral', PLANNING: 'accent',
  WAITING_APPROVAL: 'warn', EXECUTING: 'accent', OBSERVING: 'accent',
  SUCCEEDED: 'ok', FAILED: 'danger', FAILED_RECOVERABLE: 'danger',
  CANCELED: 'neutral', PAUSED: 'purple',
};

function badge(text, kind) {
  const span = document.createElement('span');
  span.className = `badge badge-${kind || 'neutral'}`;
  const dot = document.createElement('span');
  dot.className = 'badge-dot';
  span.appendChild(dot);
  span.appendChild(document.createTextNode(text || ''));
  return span;
}

// ===== Modal =====

function openModal(contentEl) {
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.appendChild(contentEl);
  backdrop.appendChild(modal);
  backdrop.addEventListener('click', (ev) => { if (ev.target === backdrop) closeModal(); });
  $modalRoot.appendChild(backdrop);
  return backdrop;
}
function closeModal() { $modalRoot.innerHTML = ''; }

// ===== Login =====

function showLogin() {
  runCleanup();
  isAuthed = false;
  $logoutBtn.classList.add('hidden');
  document.querySelectorAll('.nav-link').forEach((a) => a.classList.add('hidden'));
  $main.innerHTML = '';

  const wrap = document.createElement('div');
  wrap.className = 'login-wrap';
  wrap.innerHTML = `
    <div class="login-box">
      <h1>Mensarium</h1>
      <div class="login-hint">Run <code>mensarium core token</code> on the Core host</div>
      <div class="field">
        <label for="login-token">Admin token</label>
        <input type="password" id="login-token" autocomplete="off">
      </div>
      <button class="primary" id="login-btn" style="width:100%">Log in</button>
    </div>`;
  $main.appendChild(wrap);

  const input = wrap.querySelector('#login-token');
  const btn = wrap.querySelector('#login-btn');
  input.focus();

  async function doLogin() {
    const token = input.value.trim();
    if (!token) return;
    btn.disabled = true;
    try {
      await apiPost('/v1/auth/login', { token });
      isAuthed = true;
      document.querySelectorAll('.nav-link').forEach((a) => a.classList.remove('hidden'));
      $logoutBtn.classList.remove('hidden');
      if (location.hash === '#/dashboard') router(); else location.hash = '#/dashboard';
    } catch (err) {
      toast(err.message || 'Login failed', true);
    } finally {
      btn.disabled = false;
    }
  }
  btn.addEventListener('click', doLogin);
  input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') doLogin(); });
}

// ===== Shared: task list & new-task form =====

function renderTaskList(container, tasks, targets) {
  container.innerHTML = '';
  const targetName = (id) => {
    const t = (targets || []).find((x) => x.id === id);
    return t ? t.name : id;
  };
  tasks.forEach((t) => {
    const item = document.createElement('div');
    item.className = 'list-item';
    item.style.cursor = 'pointer';

    const main = document.createElement('div');
    main.className = 'list-main';
    const title = document.createElement('div');
    title.className = 'list-title';
    title.textContent = (t.input || '').slice(0, 90) || '(empty input)';
    const sub = document.createElement('div');
    sub.className = 'list-sub';
    sub.textContent = t.target_name || targetName(t.target_id);
    main.append(title, sub);

    const right = document.createElement('div');
    right.style.display = 'flex';
    right.style.alignItems = 'center';
    right.style.gap = '10px';
    right.appendChild(badge(t.status, TASK_STATUS_BADGE[t.status] || 'neutral'));
    const meta = document.createElement('div');
    meta.className = 'list-meta';
    meta.textContent = relativeTime(t.updated_at);
    right.appendChild(meta);

    item.append(main, right);
    item.addEventListener('click', () => { location.hash = `#/tasks/${t.id}`; });
    container.appendChild(item);
  });
}

async function renderNewTaskForm(container, targets) {
  const profiles = await safe(apiGet('/v1/agent-profiles'), []);
  container.innerHTML = `
    <div class="field">
      <label>Target</label>
      <select id="nt-target"></select>
    </div>
    <div class="field">
      <label>Profile</label>
      <select id="nt-profile"></select>
    </div>
    <div class="field">
      <label>Input</label>
      <textarea id="nt-input" rows="3" placeholder="Describe the task..."></textarea>
    </div>
    <button class="primary" id="nt-submit">Create task</button>`;

  const targetSel = container.querySelector('#nt-target');
  targets.forEach((t) => {
    const opt = document.createElement('option');
    opt.value = t.id;
    opt.textContent = t.status === 'online' ? t.name : `${t.name} (${t.status})`;
    opt.disabled = t.status !== 'online';
    targetSel.appendChild(opt);
  });
  const firstOnline = targets.find((t) => t.status === 'online');
  if (firstOnline) targetSel.value = firstOnline.id;

  const profileSel = container.querySelector('#nt-profile');
  profiles.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = `${p.name} (v${p.version})`;
    profileSel.appendChild(opt);
  });

  container.querySelector('#nt-submit').addEventListener('click', async () => {
    const targetId = targetSel.value;
    const inputEl = container.querySelector('#nt-input');
    const input = inputEl.value.trim();
    if (!targetId) { toast('Select an online target', true); return; }
    if (!input) { toast('Enter task input', true); return; }
    const submitBtn = container.querySelector('#nt-submit');
    submitBtn.disabled = true;
    try {
      const body = { target_id: targetId, input };
      if (profileSel.value) body.profile_id = profileSel.value;
      const task = await apiPost('/v1/tasks', body);
      location.hash = `#/tasks/${task.id}`;
    } catch (err) {
      if (err instanceof AuthError) { showLogin(); return; }
      toast(err.message, true);
    } finally {
      submitBtn.disabled = false;
    }
  });
}

// ===== Dashboard =====

async function viewDashboard(root) {
  root.innerHTML = `
    <div class="page-header"><h1>Dashboard</h1></div>
    <div id="dash-grid" class="grid"></div>
    <div class="section-title">Recent tasks</div>
    <div id="dash-tasks"></div>
    <div class="section-title">New task</div>
    <div class="card" id="dash-newtask"></div>`;

  const system = await safe(apiGet('/v1/system'), null);
  const targets = await safe(apiGet('/v1/targets'), []);
  const tasks = await safe(apiGet('/v1/tasks'), []);

  const grid = root.querySelector('#dash-grid');

  const coreCard = document.createElement('div');
  coreCard.className = 'card';
  coreCard.innerHTML = `<div class="section-title" style="margin-top:0">Core</div>
    <div class="kv">
      <div class="k">Version</div><div>${esc(system && system.version)}</div>
      <div class="k">Workspace</div><div>${esc(system && system.workspace_id)}</div>
    </div>`;
  grid.appendChild(coreCard);

  const prov = system && system.provider;
  const providerCard = document.createElement('div');
  providerCard.className = 'card';
  providerCard.innerHTML = `<div class="section-title" style="margin-top:0">Provider</div>
    <div class="kv">
      <div class="k">Name</div><div>${esc(prov && prov.name)}</div>
      <div class="k">Model</div><div>${esc(prov && prov.model)}</div>
      <div class="k">Health</div><div id="prov-health"></div>
    </div>`;
  grid.appendChild(providerCard);
  const healthOk = !!(prov && prov.health && prov.health.ok);
  providerCard.querySelector('#prov-health').appendChild(
    prov ? badge(healthOk ? 'ok' : 'error', healthOk ? 'ok' : 'danger') : badge('unknown', 'neutral'),
  );

  const online = targets.filter((t) => t.status === 'online').length;
  const targetsCard = document.createElement('div');
  targetsCard.className = 'card';
  targetsCard.innerHTML = `<div class="section-title" style="margin-top:0">Targets</div>
    <div style="font-size:28px;font-weight:700">${esc(online)}</div>
    <div class="muted">online of ${esc(targets.length)}</div>`;
  grid.appendChild(targetsCard);

  const tasksWrap = root.querySelector('#dash-tasks');
  if (!tasks.length) {
    tasksWrap.innerHTML = '<div class="empty-state">No tasks yet</div>';
  } else {
    renderTaskList(tasksWrap, tasks.slice(0, 5), targets);
  }

  await renderNewTaskForm(root.querySelector('#dash-newtask'), targets);
}

// ===== Tasks =====

async function viewTasks(root) {
  root.innerHTML = `
    <div class="page-header"><h1>Tasks</h1></div>
    <div class="section-title" style="margin-top:0">New task</div>
    <div class="card" id="tasks-newtask" style="margin-bottom:20px"></div>
    <div class="section-title">All tasks</div>
    <div id="tasks-list"></div>`;

  const targets = await safe(apiGet('/v1/targets'), []);
  const tasks = await safe(apiGet('/v1/tasks'), []);

  await renderNewTaskForm(root.querySelector('#tasks-newtask'), targets);

  const list = root.querySelector('#tasks-list');
  if (!tasks.length) { list.innerHTML = '<div class="empty-state">No tasks yet</div>'; return; }
  renderTaskList(list, tasks, targets);
}

// ===== Task detail (chat-like timeline) =====

const CANCELABLE_STATUSES = ['NEW', 'VALIDATING', 'PLANNING', 'WAITING_APPROVAL', 'EXECUTING', 'OBSERVING', 'PAUSED', 'FAILED_RECOVERABLE'];
const PAUSABLE_STATUSES = ['NEW', 'VALIDATING', 'PLANNING', 'WAITING_APPROVAL', 'EXECUTING', 'OBSERVING'];
const RESUMABLE_STATUSES = ['PAUSED', 'FAILED_RECOVERABLE'];
const COMPOSABLE_STATUSES = ['SUCCEEDED', 'FAILED', 'CANCELED', 'PAUSED', 'FAILED_RECOVERABLE'];

async function viewTaskDetail(root, taskId) {
  root.innerHTML = `
    <div class="task-layout">
      <div class="task-header">
        <button class="ghost" id="back-btn">&larr; Tasks</button>
        <span id="task-status-badge"></span>
        <span id="task-target-name" class="muted"></span>
        <div class="spacer"></div>
        <button id="btn-pause">Pause</button>
        <button id="btn-resume">Resume</button>
        <button class="danger" id="btn-cancel">Cancel</button>
      </div>
      <div class="timeline" id="timeline"></div>
      <div class="composer">
        <textarea id="composer-input" placeholder="Send a follow-up message..."></textarea>
        <button class="primary" id="composer-send">Send</button>
      </div>
      <div class="composer-hint" id="composer-hint"></div>
    </div>`;

  root.querySelector('#back-btn').addEventListener('click', () => { location.hash = '#/tasks'; });

  let task;
  try {
    task = await apiGet(`/v1/tasks/${taskId}`);
  } catch (err) {
    if (err instanceof AuthError) { showLogin(); return; }
    toast(err.message, true);
    location.hash = '#/tasks';
    return;
  }

  const timeline = root.querySelector('#timeline');
  const statusBadgeEl = root.querySelector('#task-status-badge');
  const targetNameEl = root.querySelector('#task-target-name');
  const btnPause = root.querySelector('#btn-pause');
  const btnResume = root.querySelector('#btn-resume');
  const btnCancel = root.querySelector('#btn-cancel');
  const composerInput = root.querySelector('#composer-input');
  const composerSend = root.querySelector('#composer-send');
  const composerHint = root.querySelector('#composer-hint');

  targetNameEl.textContent = task.target_name || task.target_id;
  let currentStatus = task.status;

  function setStatus(status) {
    currentStatus = status;
    statusBadgeEl.innerHTML = '';
    statusBadgeEl.appendChild(badge(status, TASK_STATUS_BADGE[status] || 'neutral'));
    btnCancel.disabled = !CANCELABLE_STATUSES.includes(status);
    btnPause.disabled = !PAUSABLE_STATUSES.includes(status);
    btnResume.disabled = !RESUMABLE_STATUSES.includes(status);
    const composable = COMPOSABLE_STATUSES.includes(status);
    composerInput.disabled = !composable;
    composerSend.disabled = !composable;
    composerHint.textContent = composable ? '' : 'Task is running; wait for it to pause or finish before sending a message. Ctrl/Cmd+Enter to send.';
  }
  setStatus(task.status);

  async function doAction(action) {
    try {
      const updated = await apiPost(`/v1/tasks/${taskId}/${action}`);
      setStatus(updated.status);
    } catch (err) {
      if (err instanceof AuthError) { showLogin(); return; }
      toast(err.message, true);
    }
  }
  btnCancel.addEventListener('click', () => { if (confirm('Cancel this task?')) doAction('cancel'); });
  btnPause.addEventListener('click', () => doAction('pause'));
  btnResume.addEventListener('click', () => doAction('resume'));

  async function sendMessage() {
    const text = composerInput.value.trim();
    if (!text || composerSend.disabled) return;
    composerSend.disabled = true;
    try {
      await apiPost(`/v1/tasks/${taskId}/messages`, { input: text });
      composerInput.value = '';
    } catch (err) {
      if (err instanceof AuthError) { showLogin(); return; }
      toast(err.message, true);
    } finally {
      composerSend.disabled = !COMPOSABLE_STATUSES.includes(currentStatus);
    }
  }
  composerSend.addEventListener('click', sendMessage);
  composerInput.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') { ev.preventDefault(); sendMessage(); }
  });

  // --- timeline helpers ---
  function isNearBottom() { return timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 80; }
  function scrollToBottom() { timeline.scrollTop = timeline.scrollHeight; }

  function appendBubble(cls, text) {
    const wasNear = isNearBottom();
    const div = document.createElement('div');
    div.className = `bubble ${cls}`;
    div.innerHTML = renderMarkdownLite(text || '');
    timeline.appendChild(div);
    if (wasNear) scrollToBottom();
    return div;
  }
  function appendRow(cls, text) {
    const wasNear = isNearBottom();
    const div = document.createElement('div');
    div.className = cls;
    div.textContent = text;
    timeline.appendChild(div);
    if (wasNear) scrollToBottom();
    return div;
  }

  const thinkingRows = new Map();
  const toolCards = new Map();
  const approvalCards = new Map();

  function upsertToolCard(id, tool, display, status) {
    let entry = toolCards.get(id);
    if (!entry) {
      const wasNear = isNearBottom();
      const card = document.createElement('div');
      card.className = 'tc-card';
      const head = document.createElement('div');
      head.className = 'tc-head';
      const nameEl = document.createElement('span');
      nameEl.className = 'tc-name';
      nameEl.textContent = tool || '';
      const displayEl = document.createElement('span');
      displayEl.className = 'tc-display';
      displayEl.textContent = display || '';
      const statusEl = document.createElement('span');
      head.append(nameEl, displayEl, statusEl);
      const body = document.createElement('div');
      body.className = 'tc-body';
      const out = document.createElement('pre');
      out.className = 'tc-out';
      body.appendChild(out);
      head.addEventListener('click', () => body.classList.toggle('open'));
      card.append(head, body);
      timeline.appendChild(card);
      if (wasNear) scrollToBottom();
      entry = { card, statusEl, out, body };
      toolCards.set(id, entry);
    }
    entry.statusEl.innerHTML = '';
    entry.statusEl.appendChild(badge(status, status === 'executing' ? 'accent' : 'neutral'));
    return entry;
  }

  function updateToolCardResult(payload) {
    const entry = upsertToolCard(payload.tool_call_id, payload.tool, null, payload.status);
    const kind = payload.status === 'succeeded' ? 'ok' : (payload.status === 'failed' ? 'danger' : 'warn');
    entry.statusEl.innerHTML = '';
    entry.statusEl.appendChild(badge(payload.status, kind));
    let outText = payload.output || '';
    if (payload.exit_code !== null && payload.exit_code !== undefined) outText = `exit ${payload.exit_code}\n${outText}`;
    entry.out.textContent = outText;
    if (payload.truncated) {
      const note = document.createElement('div');
      note.className = 'muted';
      note.style.fontSize = '11px';
      note.style.marginTop = '4px';
      note.textContent = 'Output truncated.';
      if (payload.artifact_id) {
        const link = document.createElement('a');
        link.href = `/v1/artifacts/${payload.artifact_id}`;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = ' full output';
        note.appendChild(link);
      }
      entry.body.appendChild(note);
    }
    entry.body.classList.add('open');
  }

  function renderApprovalCard(payload) {
    const wasNear = isNearBottom();
    const tc = payload.tool_call || {};
    const risk = tc.risk || 'read';
    const card = document.createElement('div');
    card.className = `approval-card${risk === 'destructive' ? ' risk-destructive' : ''}`;

    const head = document.createElement('div');
    head.className = 'approval-head';
    const left = document.createElement('div');
    left.style.display = 'flex';
    left.style.gap = '8px';
    left.style.alignItems = 'center';
    left.appendChild(badge(risk, RISK_BADGE[risk] || 'neutral'));
    const targetSpan = document.createElement('span');
    targetSpan.className = 'muted';
    targetSpan.textContent = tc.target_name || '';
    left.appendChild(targetSpan);
    head.appendChild(left);
    const countdown = document.createElement('span');
    countdown.className = 'countdown';
    head.appendChild(countdown);
    card.appendChild(head);

    function addRow(label, value) {
      if (value === undefined || value === null || value === '') return;
      const row = document.createElement('div');
      row.className = 'approval-row';
      const kEl = document.createElement('span');
      kEl.className = 'k';
      kEl.textContent = label;
      const vEl = document.createElement('span');
      vEl.className = 'mono';
      vEl.style.wordBreak = 'break-word';
      vEl.textContent = value;
      row.append(kEl, vEl);
      card.appendChild(row);
    }
    addRow('Tool', tc.tool);
    addRow('Command', tc.display);
    const args = tc.arguments || {};
    addRow('Args', Object.keys(args).length ? JSON.stringify(args) : '');
    addRow('Cwd', args.cwd);

    if (args.stdin) {
      const label = document.createElement('div');
      label.className = 'approval-row';
      const kEl = document.createElement('span');
      kEl.className = 'k';
      kEl.textContent = 'Stdin';
      label.appendChild(kEl);
      card.appendChild(label);
      const pre = document.createElement('pre');
      pre.className = 'tc-out';
      pre.textContent = args.stdin;
      card.appendChild(pre);
    }

    let confirmCheck = null;
    if (risk === 'destructive') {
      const confirmWrap = document.createElement('label');
      confirmWrap.className = 'confirm-check';
      confirmCheck = document.createElement('input');
      confirmCheck.type = 'checkbox';
      confirmWrap.append(confirmCheck, document.createTextNode('I understand this is destructive'));
      card.appendChild(confirmWrap);
    }

    const actions = document.createElement('div');
    actions.className = 'approval-actions';
    const approveBtn = document.createElement('button');
    approveBtn.className = 'primary';
    approveBtn.textContent = 'Approve once';
    approveBtn.disabled = risk === 'destructive';
    const rejectBtn = document.createElement('button');
    rejectBtn.className = 'danger';
    rejectBtn.textContent = 'Reject';
    actions.append(approveBtn, rejectBtn);
    card.appendChild(actions);

    if (confirmCheck) {
      confirmCheck.addEventListener('change', () => { approveBtn.disabled = !confirmCheck.checked; });
    }

    async function decide(decision) {
      approveBtn.disabled = true;
      rejectBtn.disabled = true;
      if (confirmCheck) confirmCheck.disabled = true;
      try {
        const body = { decision };
        if (risk === 'destructive') body.confirm = true;
        await apiPost(`/v1/approvals/${payload.approval_id}/decision`, body);
      } catch (err) {
        if (err instanceof AuthError) { showLogin(); return; }
        toast(err.message, true);
        rejectBtn.disabled = false;
        if (confirmCheck) { confirmCheck.disabled = false; approveBtn.disabled = !confirmCheck.checked; }
        else approveBtn.disabled = false;
      }
    }
    approveBtn.addEventListener('click', () => decide('approve'));
    rejectBtn.addEventListener('click', () => decide('reject'));

    timeline.appendChild(card);
    if (wasNear) scrollToBottom();

    let timer = null;
    const expiresAt = payload.expires_at ? new Date(payload.expires_at).getTime() : null;
    if (expiresAt) {
      const tick = () => {
        const remaining = Math.round((expiresAt - Date.now()) / 1000);
        if (remaining <= 0) { countdown.textContent = 'expired'; clearInterval(timer); }
        else countdown.textContent = `expires in ${formatDuration(remaining)}`;
      };
      tick();
      timer = setInterval(tick, 1000);
      onCleanup(() => clearInterval(timer));
    }

    approvalCards.set(payload.approval_id, { card, approveBtn, rejectBtn, confirmCheck, countdown, timer });
  }

  function decideApprovalCard(payload) {
    const entry = approvalCards.get(payload.approval_id);
    if (!entry) return;
    if (entry.timer) clearInterval(entry.timer);
    entry.card.classList.add('decided');
    entry.approveBtn.disabled = true;
    entry.rejectBtn.disabled = true;
    if (entry.confirmCheck) entry.confirmCheck.disabled = true;
    entry.countdown.textContent = `decision: ${payload.decision}${payload.note ? ` - ${payload.note}` : ''}`;
  }

  function handleEvent(evt) {
    const { event, payload } = evt;
    switch (event) {
      case 'user.message':
        appendBubble('bubble-user', payload.text);
        break;
      case 'task.status':
        setStatus(payload.status);
        break;
      case 'llm.request':
        thinkingRows.set(payload.step, appendRow('row-thinking', 'thinking...'));
        break;
      case 'llm.response': {
        const row = thinkingRows.get(payload.step);
        if (row) { row.remove(); thinkingRows.delete(payload.step); }
        if (payload.text) appendBubble('bubble-assistant', payload.text);
        break;
      }
      case 'tool_call.denied':
        appendRow('row-error', `Tool call denied: ${payload.tool} - ${payload.reason || ''}`);
        break;
      case 'tool_call.pending_approval':
        renderApprovalCard(payload);
        break;
      case 'approval.decided':
        decideApprovalCard(payload);
        break;
      case 'tool_call.executing':
        upsertToolCard(payload.tool_call_id, payload.tool, payload.display, 'executing');
        break;
      case 'tool_call.result':
        updateToolCardResult(payload);
        break;
      case 'task.final':
        appendBubble('bubble-assistant bubble-final', payload.text);
        break;
      case 'task.error':
        appendRow('row-error', `Error: ${payload.message}`);
        break;
      default:
        break;
    }
  }

  // --- SSE with reconnect + backoff, dedupe by seq ---
  let lastSeq = 0;
  let es = null;
  let reconnectDelay = 1000;
  let closed = false;

  function connectSSE() {
    if (closed) return;
    es = new EventSource(`/v1/tasks/${taskId}/events?after=${lastSeq}`, { withCredentials: true });
    es.onopen = () => { reconnectDelay = 1000; };
    es.onmessage = (msg) => {
      let evt;
      try { evt = JSON.parse(msg.data); } catch (err) { return; }
      if (typeof evt.seq === 'number') {
        if (evt.seq <= lastSeq) return;
        lastSeq = evt.seq;
      }
      handleEvent(evt);
    };
    es.onerror = () => {
      es.close();
      if (closed) return;
      setTimeout(connectSSE, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    };
  }
  connectSSE();
  onCleanup(() => { closed = true; if (es) es.close(); });
}

// ===== Targets =====

async function viewTargets(root) {
  root.innerHTML = `
    <div class="page-header">
      <h1>Targets</h1>
      <div class="page-actions"><button class="primary" id="pair-btn">Pair new target</button></div>
    </div>
    <div id="targets-grid" class="grid"><div class="empty-state">Loading...</div></div>`;

  async function refresh() {
    let targets;
    try { targets = await apiGet('/v1/targets'); }
    catch (err) { if (err instanceof AuthError) showLogin(); return; }
    renderTargetsGrid(root.querySelector('#targets-grid'), targets, refresh);
  }
  await refresh();
  const interval = setInterval(refresh, 5000);
  onCleanup(() => clearInterval(interval));

  root.querySelector('#pair-btn').addEventListener('click', openPairingModal);
}

function renderTargetsGrid(grid, targets, refresh) {
  grid.innerHTML = '';
  if (!targets.length) { grid.innerHTML = '<div class="empty-state">No targets paired yet</div>'; return; }
  targets.forEach((t) => {
    const card = document.createElement('div');
    card.className = 'card target-card';

    const head = document.createElement('div');
    head.className = 'target-card-head';
    const name = document.createElement('div');
    name.className = 'target-name';
    name.textContent = t.name;
    head.append(name, badge(t.status, TARGET_STATUS_BADGE[t.status] || 'neutral'));
    card.appendChild(head);

    const facts = document.createElement('div');
    facts.className = 'target-fact';
    facts.textContent = `${t.platform || '-'} - ${t.hostname || '-'} - agent ${t.agent_version || '-'}`;
    card.appendChild(facts);

    const lastSeen = document.createElement('div');
    lastSeen.className = 'target-fact';
    lastSeen.textContent = `Last seen: ${relativeTime(t.last_seen_at)}`;
    card.appendChild(lastSeen);

    const caps = t.capabilities || {};
    if (caps.roots && caps.roots.length) {
      const row = document.createElement('div');
      row.className = 'tag-row';
      caps.roots.forEach((r) => { const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = r; row.appendChild(tag); });
      card.appendChild(row);
    }
    if (caps.tools && caps.tools.length) {
      const row = document.createElement('div');
      row.className = 'tag-row';
      caps.tools.forEach((tl) => { const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = tl; row.appendChild(tag); });
      card.appendChild(row);
    }

    if (t.status !== 'revoked') {
      const revokeBtn = document.createElement('button');
      revokeBtn.className = 'danger';
      revokeBtn.textContent = 'Revoke';
      revokeBtn.addEventListener('click', async () => {
        if (!confirm(`Revoke target "${t.name}"? This cannot be undone.`)) return;
        revokeBtn.disabled = true;
        try {
          await apiPost(`/v1/targets/${t.id}/revoke`);
          toast('Target revoked');
          if (refresh) refresh();
        } catch (err) {
          if (err instanceof AuthError) { showLogin(); return; }
          toast(err.message, true);
          revokeBtn.disabled = false;
        }
      });
      card.appendChild(revokeBtn);
    }

    grid.appendChild(card);
  });
}

async function openPairingModal() {
  const content = document.createElement('div');
  content.innerHTML = `
    <div class="modal-head"><h2>Pair new target</h2><button class="ghost" id="modal-close">Close</button></div>
    <div id="modal-body">Requesting pairing code...</div>`;
  openModal(content);
  content.querySelector('#modal-close').addEventListener('click', closeModal);

  let data;
  try {
    data = await apiPost('/v1/targets/pairing-codes');
  } catch (err) {
    if (err instanceof AuthError) { closeModal(); showLogin(); return; }
    content.querySelector('#modal-body').textContent = err.message || 'Failed to create pairing code';
    return;
  }

  const body = content.querySelector('#modal-body');
  body.innerHTML = `
    <div class="pairing-code">${esc(data.code)}</div>
    <div class="muted" style="text-align:center;margin-bottom:14px">Expires in <span id="pair-countdown" class="countdown"></span></div>
    <label>Install command</label>
    <div class="copy-row"><pre>${esc(data.install_command)}</pre><button data-copy="install">Copy</button></div>
    <label>Pair command</label>
    <div class="copy-row"><pre>${esc(data.pair_command)}</pre><button data-copy="pair">Copy</button></div>`;
  body.querySelector('[data-copy="install"]').addEventListener('click', (ev) => copyText(data.install_command, ev.currentTarget));
  body.querySelector('[data-copy="pair"]').addEventListener('click', (ev) => copyText(data.pair_command, ev.currentTarget));

  const countdownEl = body.querySelector('#pair-countdown');
  const expiresAt = new Date(data.expires_at).getTime();
  const iv = setInterval(() => {
    const remaining = Math.max(0, Math.round((expiresAt - Date.now()) / 1000));
    countdownEl.textContent = formatDuration(remaining);
    if (remaining <= 0) clearInterval(iv);
  }, 1000);
  countdownEl.textContent = formatDuration(Math.max(0, Math.round((expiresAt - Date.now()) / 1000)));

  const obs = new MutationObserver(() => {
    if (!document.body.contains(content)) { clearInterval(iv); obs.disconnect(); }
  });
  obs.observe($modalRoot, { childList: true });
}

// ===== Audit =====

async function viewAudit(root) {
  root.innerHTML = `
    <div class="page-header">
      <h1>Audit log</h1>
      <div class="page-actions"><button id="audit-refresh">Refresh</button></div>
    </div>
    <div id="audit-table"></div>`;

  async function load() {
    let events;
    try { events = await apiGet('/v1/audit?limit=200'); }
    catch (err) {
      if (err instanceof AuthError) { showLogin(); return; }
      toast(err.message, true);
      return;
    }
    renderAuditTable(root.querySelector('#audit-table'), events);
  }
  root.querySelector('#audit-refresh').addEventListener('click', load);
  await load();
}

function renderAuditTable(container, events) {
  if (!events.length) { container.innerHTML = '<div class="empty-state">No audit events</div>'; return; }
  const table = document.createElement('table');
  table.innerHTML = '<thead><tr><th>Time</th><th>Actor</th><th>Event</th><th>Payload</th><th>Hash</th></tr></thead>';
  const tbody = document.createElement('tbody');
  events.forEach((ev) => {
    const tr = document.createElement('tr');
    const tdTime = document.createElement('td');
    tdTime.textContent = new Date(ev.created_at).toLocaleString();
    const tdActor = document.createElement('td');
    tdActor.textContent = ev.actor;
    const tdType = document.createElement('td');
    tdType.textContent = ev.event_type;
    const tdPayload = document.createElement('td');
    const pre = document.createElement('pre');
    pre.style.cssText = 'margin:0;max-width:420px;overflow-x:auto;font-size:11px';
    pre.textContent = JSON.stringify(ev.payload);
    tdPayload.appendChild(pre);
    const tdHash = document.createElement('td');
    tdHash.className = 'mono';
    tdHash.textContent = (ev.hash || '').slice(0, 10);
    tr.append(tdTime, tdActor, tdType, tdPayload, tdHash);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.innerHTML = '';
  container.appendChild(table);
}

// ===== Settings =====

async function viewSettings(root) {
  root.innerHTML = `
    <div class="page-header"><h1>Settings</h1></div>
    <div class="grid">
      <div class="card" id="settings-system"><div class="section-title" style="margin-top:0">System</div>Loading...</div>
      <div class="card" id="settings-models"><div class="section-title" style="margin-top:0">Available models</div>Loading...</div>
    </div>
    <div class="section-title">CLI cheatsheet</div>
    <div class="card"><pre class="mono" style="white-space:pre-wrap;margin:0">mensarium core backup -o file.pab
mensarium core restore file.pab
mensarium core token
mensarium status</pre></div>`;

  const system = await safe(apiGet('/v1/system'), null);
  const sysCard = root.querySelector('#settings-system');
  if (system) {
    const prov = system.provider || {};
    sysCard.innerHTML = `<div class="section-title" style="margin-top:0">System</div>
      <div class="kv">
        <div class="k">Version</div><div>${esc(system.version)}</div>
        <div class="k">Workspace</div><div>${esc(system.workspace_id)}</div>
        <div class="k">Public URL</div><div>${esc(system.public_url)}</div>
        <div class="k">Key fingerprint</div><div class="mono">${esc(system.core_key_fingerprint)}</div>
        <div class="k">Provider</div><div>${esc(prov.name)}</div>
        <div class="k">Base URL</div><div>${esc(prov.base_url)}</div>
        <div class="k">Model</div><div>${esc(prov.model)}</div>
      </div>`;
  } else {
    sysCard.innerHTML = '<div class="section-title" style="margin-top:0">System</div><div class="empty-state">Failed to load system info</div>';
  }

  const modelsCard = root.querySelector('#settings-models');
  try {
    const models = await apiGet('/v1/models');
    modelsCard.innerHTML = '<div class="section-title" style="margin-top:0">Available models</div>';
    if (!models.length) {
      modelsCard.innerHTML += '<div class="empty-state">No models available</div>';
    } else {
      const wrap = document.createElement('div');
      models.forEach((m) => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.style.cssText = 'display:inline-block;margin:3px';
        tag.textContent = m.id;
        wrap.appendChild(tag);
      });
      modelsCard.appendChild(wrap);
    }
  } catch (err) {
    if (err instanceof AuthError) { showLogin(); return; }
    modelsCard.innerHTML = `<div class="section-title" style="margin-top:0">Available models</div><div class="empty-state">${esc(err.message || 'Failed to load models')}</div>`;
  }
}

// ===== Router =====

const ROUTES = [
  { pattern: /^#\/dashboard$/, view: viewDashboard },
  { pattern: /^#\/tasks$/, view: viewTasks },
  { pattern: /^#\/tasks\/([^/]+)$/, view: viewTaskDetail },
  { pattern: /^#\/targets$/, view: viewTargets },
  { pattern: /^#\/audit$/, view: viewAudit },
  { pattern: /^#\/settings$/, view: viewSettings },
];

function updateNavActive(hash) {
  document.querySelectorAll('.nav-link').forEach((a) => {
    const r = a.getAttribute('data-route');
    const active = hash === r || (r === '#/tasks' && hash.startsWith('#/tasks/'));
    a.classList.toggle('active', active);
  });
}

async function router() {
  runCleanup();
  if (!location.hash) { location.hash = '#/dashboard'; return; }
  const hash = location.hash;
  updateNavActive(hash);
  for (const r of ROUTES) {
    const m = hash.match(r.pattern);
    if (m) {
      $main.innerHTML = '';
      try {
        await r.view($main, ...m.slice(1));
      } catch (err) {
        if (err instanceof AuthError) { showLogin(); return; }
        toast(err.message || 'Error', true);
      }
      return;
    }
  }
  location.hash = '#/dashboard';
}

// ===== Boot =====

async function boot() {
  window.addEventListener('hashchange', router);
  $logoutBtn.addEventListener('click', async () => {
    try { await apiPost('/v1/auth/logout'); } catch (err) { /* noop */ }
    showLogin();
  });

  try {
    await apiGet('/v1/system');
    isAuthed = true;
    $logoutBtn.classList.remove('hidden');
    document.querySelectorAll('.nav-link').forEach((a) => a.classList.remove('hidden'));
    router();
  } catch (err) {
    showLogin();
  }
}

boot();
