// Mensarium web UI. Vanilla ES module, no build step, no dependencies.

import { LANGUAGES, lang, locale, setLang, t as tr, tp } from './i18n.js';
import { createOrb } from './orb.js';
import { createGraph, graphColor } from './graph.js';

const $app = document.getElementById('app');
const $toasts = document.getElementById('toasts');
const $layer = document.getElementById('layer');

const state = { system: null, targets: [], tasks: [], shell: null, lastChat: '#/', updates: new Map() };
let viewCleanups = [];
let shellCleanups = [];

class AuthError extends Error {}

// ---------- API ----------

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
    ...opts,
  });
  if (res.status === 401) throw new AuthError('unauthorized');
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!res.ok) throw new Error((data && data.detail) || tr('Request error ({0})', res.status));
  return data;
}
const get = (path) => api(path);
const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body || {}) });
const del = (path) => api(path, { method: 'DELETE' });

function fail(err) {
  if (err instanceof AuthError) { showLogin(); return; }
  toast(err.message || String(err), true);
}

// ---------- DOM helpers ----------

function h(tag, attrs, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    e.append(c instanceof Node ? c : String(c));
  }
  return e;
}

const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  laptop: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
  sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  sidebar: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  arrowLeft: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
  arrowUp: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  shield: '<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6z"/><path d="m9 12 2 2 4-4"/>',
  bolt: '<path d="M13 3 5 14h6l-1 7 8-11h-6z"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  play: '<path d="M7 5v14l12-7z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  stopFill: '<rect x="7.5" y="7.5" width="9" height="9" rx="1.8" fill="currentColor" stroke="none"/>',
  playFill: '<path d="M9 6.8v10.4a.8.8 0 0 0 1.2.7l8.3-5.2a.8.8 0 0 0 0-1.4L10.2 6.1A.8.8 0 0 0 9 6.8z" fill="currentColor" stroke="none"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h11"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  terminal: '<path d="m5 8 4 4-4 4M12 17h7"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  git: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M6 8.5v7M18 11.5c0 3-3 4-9.5 5"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  pulse: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a1 1 0 0 1 1-1h9"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  package: '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
  book: '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z"/><path d="M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3"/>',
  graph: '<circle cx="6" cy="7" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8.2 8.4 10.9 15.8M16.9 8.2l-3.8 7.6M8.5 6.8l7-.6"/>',
  pin: '<path d="M9 4h6l-1 5 3 3v2H7v-2l3-3z"/><path d="M12 14v6"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  robot: '<rect x="4.5" y="8" width="15" height="11" rx="3"/><path d="M12 8V5.2M2.5 12.5v3M21.5 12.5v3M9.5 16h5"/><circle cx="12" cy="4.2" r="1"/><circle cx="9.3" cy="12.4" r=".9"/><circle cx="14.7" cy="12.4" r=".9"/>',
};

function icon(name) {
  const span = document.createElement('span');
  span.innerHTML = `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  return span.firstChild;
}
// kind -> [css size, animated]; message orbs stay still so a long thread costs nothing.
const ORB_KINDS = { sm: [20, true], md: [60, true], lg: [150, true], '': [26, false], live: [26, true] };
const orb = (kind = '') => {
  const [size, animate] = ORB_KINDS[kind];
  return createOrb(size, { animate, live: kind === 'live', className: kind });
};

function toast(message, isError = false) {
  const t = h('div', { class: `toast${isError ? ' error' : ''}`, role: isError ? 'alert' : 'status' }, message);
  $toasts.append(t);
  setTimeout(() => t.remove(), 5000);
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Model output is untrusted: everything is escaped first, then a tiny markdown subset is applied.
function inlineMd(s) {
  return esc(s)
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
}

function markdown(text) {
  const out = [];
  let para = [];
  let list = null;
  const flushPara = () => { if (para.length) out.push(`<p>${para.map(inlineMd).join('<br>')}</p>`); para = []; };
  const flushList = () => {
    if (list) out.push(`<${list.tag}${list.start > 1 ? ` start="${list.start}"` : ''}>${list.items.map((i) => `<li>${i.split('\n').map(inlineMd).join('<br>')}</li>`).join('')}</${list.tag}>`);
    list = null;
  };
  const lines = String(text || '').split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flushPara(); flushList();
      const code = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
      out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
      continue;
    }
    const bullet = line.match(/^(\s*)[-*]\s+(.*)$/);
    const numbered = line.match(/^(\s*)(\d+)[.)]\s+(.*)$/);
    const heading = line.match(/^\s*#{1,6}\s+(.*)$/);
    const item = bullet || numbered;
    // Indented lines and nested items continue the current list item instead of breaking the list.
    if (list && item && item[1].length >= 2) {
      list.items[list.items.length - 1] += `\n• ${bullet ? bullet[2] : numbered[3]}`;
    } else if (list && !item && /^\s{2,}\S/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else if (item) {
      flushPara();
      const tag = bullet ? 'ul' : 'ol';
      if (!list || list.tag !== tag) { flushList(); list = { tag, items: [], start: numbered ? Number(numbered[2]) : 1 }; }
      list.items.push(bullet ? bullet[2] : numbered[3]);
    } else if (heading) {
      flushPara(); flushList();
      out.push(`<h3>${inlineMd(heading[1])}</h3>`);
    } else if (!line.trim()) {
      flushPara();
      if (list && !/^\s*([-*]|\d+[.)])\s+/.test(lines[i + 1] || '')) flushList();
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara(); flushList();
  return out.join('');
}

function relTime(iso) {
  if (!iso) return tr('never');
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 10) return tr('just now');
  if (s < 60) return tr('{0} s ago', s);
  const m = Math.round(s / 60);
  if (m < 60) return tr('{0} min ago', m);
  const hr = Math.round(m / 60);
  if (hr < 24) return tr('{0} h ago', hr);
  return tr('{0} d ago', Math.round(hr / 24));
}

const mmss = (sec) => `${Math.floor(Math.max(0, sec) / 60)}:${String(Math.max(0, sec) % 60).padStart(2, '0')}`;

async function copy(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = h('textarea', { style: 'position:fixed;opacity:0' });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }
  if (btn) {
    const prev = btn.innerHTML;
    btn.replaceChildren(icon('check'));
    setTimeout(() => { btn.innerHTML = prev; }, 1400);
  }
}

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } }

// ---------- domain vocab ----------

const STATUS = {
  NEW: [tr('Starting'), 'accent', true],
  VALIDATING: [tr('Starting'), 'accent', true],
  PLANNING: [tr('Thinking'), 'accent', true],
  WAITING_APPROVAL: [tr('Waiting for a decision'), 'warn', true],
  EXECUTING: [tr('Executing'), 'accent', true],
  OBSERVING: [tr('Parsing the result'), 'accent', true],
  SUCCEEDED: [tr('Done'), 'ok', false],
  FAILED: [tr('Error'), 'danger', false],
  FAILED_RECOVERABLE: [tr('Interrupted, can be resumed'), 'danger', false],
  CANCELED: [tr('Stopped'), '', false],
  PAUSED: [tr('Paused'), 'warn', false],
};
const REASONS = {
  'paused by user': tr('paused'),
  'canceled by user': tr('stopped by you'),
  'core restarted': tr('Core restarted, resume manually'),
  'target offline': tr('device offline'),
  'target revoked': tr('device access revoked'),
  'step budget exhausted': tr('step limit reached'),
  'tool call budget exhausted': tr('action limit reached'),
  'wall time budget exhausted': tr('task time limit reached'),
};
const RISK = {
  read: [tr('read'), ''],
  write: [tr('file changes'), 'warn'],
  execute: [tr('run a program'), 'orange'],
  network: [tr('network access'), 'accent'],
  destructive: [tr('irreversible action'), 'danger'],
};
const MODES = {
  ask: { label: tr('Ask before acting'), icon: 'shield', cls: 'accent', desc: tr('Reads right away. Running programs, changing files, and network access wait for your approval.') },
  full: { label: tr('Full access'), icon: 'bolt', cls: 'full', desc: tr('The agent does everything without asking. Only sudo and system settings are off-limits.') },
};
const TEMPLATES = [
  ['terminal', tr('Why tests are failing'), tr('Run the project\'s tests, find why they\'re failing, and explain it. Don\'t change files yet.')],
  ['git', tr('What changed'), tr('Show what changed in the repository since the last commit, and briefly describe the changes.')],
  ['folder', tr('How the project is structured'), tr('Study the project structure and explain how it\'s organized: entry points, main modules, how to run it.')],
  ['search', tr('Fix a bug'), tr('Find the cause of the error and suggest a minimal fix: ')],
];
const TOOL_ICON = { 'files.list': 'folder', 'files.read': 'file', 'files.search': 'search', 'git.status': 'git', 'git.diff': 'git', 'shell.exec': 'terminal', 'skills.read': 'book', 'memory.search': 'graph', 'memory.read': 'graph', 'memory.save': 'graph' };
// Marketplace texts are either plain strings or {en, ru} maps.
const txt = (v) => (typeof v === 'string' ? v : (v?.[lang] || v?.en || ''));
const RESUMABLE = ['PAUSED', 'FAILED_RECOVERABLE'];

const POLICY_REASONS = [
  [/^access to secret files is not allowed$/, () => tr('reading secret files is not allowed')],
  [/^unknown tool '(.+)'$/, (m) => tr('unknown tool {0}', m[1])],
  [/^tool '(.+)' is not allowed by the active profile$/, (m) => tr('tool {0} not allowed by the profile', m[1])],
  [/^tool '(.+)' is disabled for this device$/, (m) => tr('tool {0} disabled for this device', m[1])],
  [/^target does not support tool '(.+)'$/, (m) => tr('device doesn\'t support {0}', m[1])],
  [/^path '(.+)' is outside allowed roots/, (m) => tr('path {0} is outside allowed folders', m[1])],
  [/^program '(.+)' is not in the target command allowlist$/, (m) => tr('program {0} not allowed on the device', m[1])],
  [/^shell operators .* are not supported/, () => tr('shell operators (|, &&, >) are not supported, the command runs without a shell')],
  [/^`cd` is not supported/, () => tr('cd is not supported, set the folder separately')],
  [/^run programs by name, not by path$/, () => tr('specify the program by name, not by path')],
  [/^privileged actions are denied$/, () => tr('privileged actions are not allowed')],
  [/^invalid arguments/, () => tr('invalid arguments')],
];
const EXEC_STATUS = { succeeded: tr('success'), failed: tr('error'), timeout: tr('timeout'), canceled: tr('canceled'), rejected: tr('rejected by the device') };
const policyText = (r) => {
  for (const [re, fn] of POLICY_REASONS) { const m = String(r).match(re); if (m) return fn(m); }
  return r;
};
const reasonText = (r) => REASONS[r] || r;
const statusOf = (s) => STATUS[s] || [s, '', false];
const isRunning = (s) => statusOf(s)[2];
const isLocal = (t) => t && t.id === state.system?.local_target_id;
const fullAccessOf = (t) => t?.capabilities?.full_access || 'disabled';
const fullAccessBlock = (t) => (fullAccessOf(t) === 'outdated'
  ? tr('The device agent is outdated (v{0}). Update it in Settings → Devices.', t.agent_version)
  : tr('Disabled on the device: allow_full_access in its config.'));
const devices = () => state.targets.filter((t) => t.status !== 'revoked').sort((a, b) => isLocal(b) - isLocal(a));
const taskTitle = (t) => ((t.input || '').split('\n')[0] || tr('Untitled')).slice(0, 80);

// ---------- overlays ----------

function closeLayer() { $layer.replaceChildren(); }

function openPopover(anchor, items, cls = '') {
  closeLayer();
  const pop = h('div', { class: `popover ${cls}`, role: 'menu' }, items);
  $layer.append(h('div', { style: 'position:fixed;inset:0;z-index:49', onclick: closeLayer }), pop);
  const place = () => {
    const r = anchor.getBoundingClientRect();
    const top = r.top - pop.offsetHeight - 8 > 8 ? r.top - pop.offsetHeight - 8 : r.bottom + 8;
    pop.style.top = `${top}px`;
    pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8))}px`;
  };
  place();
  return place;
}

function openModal(...content) {
  closeLayer();
  const modal = h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' }, content);
  const backdrop = h('div', { class: 'backdrop', onclick: (e) => { if (e.target === backdrop) closeLayer(); } }, modal);
  $layer.append(backdrop);
  return modal;
}

function confirmDialog({ title, text, action, danger = false }) {
  return new Promise((resolve) => {
    const done = (value) => { closeLayer(); resolve(value); };
    const ok = h('button', { class: `btn ${danger ? 'btn-danger-solid' : 'btn-primary'}`, onclick: () => done(true) }, action);
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, title)),
      h('p', {}, text),
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: () => done(false) }, tr('Cancel')), ok),
    );
    $layer.querySelector('.backdrop').addEventListener('click', (e) => { if (e.target === e.currentTarget) resolve(false); });
    ok.focus();
  });
}

async function deleteChat(task) {
  const yes = await confirmDialog({
    title: tr('Delete chat?'),
    text: tr('“{0}” will disappear along with its messages and command output. If the agent is still working, the task will stop. Entries in the activity log will remain.', taskTitle(task)),
    action: tr('Delete'),
    danger: true,
  });
  if (!yes) return;
  try {
    await del(`/v1/tasks/${task.id}`);
    state.tasks = state.tasks.filter((t) => t.id !== task.id);
    toast(tr('Chat deleted'));
    if (location.hash === `#/chat/${task.id}`) go('#/');
    else state.shell?.renderSessions?.();
  } catch (err) { fail(err); }
}

async function openPairing() {
  const body = h('div', {}, h('p', {}, tr('Generating code...')));
  openModal(
    h('div', { class: 'modal-head' }, h('h2', {}, tr('Pair a device')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
    body,
  );
  let data;
  try { data = await post('/v1/targets/pairing-codes'); } catch (err) { closeLayer(); fail(err); return; }
  const timer = h('span', {});
  const line = (cmd) => h('div', { class: 'code-line' }, h('code', {}, cmd), h('button', { class: 'icon-btn', 'aria-label': tr('Copy'), onclick: (e) => copy(cmd, e.currentTarget) }, icon('copy')));
  body.replaceChildren(
    h('p', {}, tr('Run the command on the machine you want to connect. The code is one-time.')),
    h('div', { class: 'pair-code' }, data.code),
    h('div', { class: 'pair-timer' }, tr('Valid for '), timer),
    h('div', { class: 'field-label' }, tr('Install and connect')),
    line(data.install_command),
    h('div', { class: 'field-label' }, tr('If Mensarium is already installed')),
    line(`${data.pair_command} --root ~/Projects`),
  );
  const expires = new Date(data.expires_at).getTime();
  const tick = () => {
    const left = Math.round((expires - Date.now()) / 1000);
    timer.textContent = left > 0 ? mmss(left) : tr('expired');
    if (left <= 0 || !document.body.contains(timer)) clearInterval(iv);
  };
  const iv = setInterval(tick, 1000);
  tick();
}

function languageSwitch(compact = false) {
  return h('div', { class: `segmented${compact ? ' lang-compact' : ''}`, role: 'radiogroup', 'aria-label': tr('Language') },
    Object.entries(LANGUAGES).map(([code, name]) => h('button', {
      class: `seg${code === lang ? ' active' : ''}`, role: 'radio', 'aria-checked': String(code === lang),
      onclick: () => { if (code !== lang) setLang(code); },
    }, compact ? code.toUpperCase() : name)));
}

// ---------- login ----------

function showLogin() {
  cleanupAll();
  state.shell = null;
  const input = h('input', { type: 'password', placeholder: tr('Admin token'), autocomplete: 'current-password', 'aria-label': tr('Admin token') });
  const btn = h('button', { class: 'btn btn-primary' }, tr('Sign in'));
  const submit = async () => {
    const token = input.value.trim();
    if (!token) return;
    btn.disabled = true;
    try {
      await post('/v1/auth/login', { token });
      await boot();
    } catch (err) {
      toast(err instanceof AuthError ? tr('Invalid token') : err.message, true);
    } finally { btn.disabled = false; }
  };
  btn.addEventListener('click', submit);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  $app.replaceChildren(h('div', { class: 'login' }, h('div', { class: 'login-lang' }, languageSwitch(true)), h('div', { class: 'login-card' },
    orb('md'),
    h('h1', {}, 'Mensarium'),
    h('p', {}, tr('The token is issued by the command '), h('code', {}, 'mensarium core token'), tr(' on the Core server.')),
    input, btn,
  )));
  input.focus();
}

// ---------- data ----------

async function refreshData() {
  const [targets, tasks] = await Promise.all([get('/v1/targets'), get('/v1/tasks')]);
  state.targets = targets;
  state.tasks = tasks;
  for (const [id, pending] of state.updates) {
    const t = targets.find((x) => x.id === id);
    if (t && t.status === 'online' && t.agent_version === pending.version) {
      state.updates.delete(id);
      toast(tr('“{0}” updated to {1}', t.name, pending.version));
    } else if (Date.now() - pending.at > 180000) {
      state.updates.delete(id);
      toast(tr('Didn\'t wait for “{0}” to update. Check the agent log on the device.', t?.name || id), true);
    }
  }
}

function cleanupAll() {
  [...viewCleanups, ...shellCleanups].forEach((fn) => { try { fn(); } catch { /* noop */ } });
  viewCleanups = [];
  shellCleanups = [];
}

// ---------- frame ----------

// Shared frame: black sidebar on the left, inset violet-lit panel on the right.
function frame(kind, sidebarChildren) {
  cleanupAll();
  const panel = h('div', { class: 'panel' });
  const shell = h('div', { class: `shell${localStorageGet('sidebar') === 'collapsed' ? ' collapsed' : ''}` },
    h('aside', { class: 'sidebar' }, sidebarChildren),
    h('main', { class: 'main' }, panel),
    h('div', { class: 'nav-backdrop', onclick: () => shell.classList.remove('nav-open') }),
  );
  $app.replaceChildren(shell);
  const toggleNav = () => {
    if (matchMedia('(max-width: 860px)').matches) { shell.classList.toggle('nav-open'); return; }
    shell.classList.toggle('collapsed');
    localStorageSet('sidebar', shell.classList.contains('collapsed') ? 'collapsed' : 'open');
  };
  return { kind, shell, panel, toggleNav };
}

function topbar(shell, crumbs, actions, { newChat = true } = {}) {
  return h('header', { class: 'topbar' },
    h('button', { class: 'icon-btn open-nav', 'aria-label': tr('Show sidebar'), title: tr('Show sidebar'), onclick: shell.toggleNav }, icon('sidebar')),
    newChat ? h('a', { class: 'icon-btn open-nav', href: '#/', 'aria-label': tr('New chat'), title: tr('New chat') }, icon('plus')) : null,
    h('div', { class: 'crumbs' }, crumbs),
    actions ? h('div', { class: 'topbar-actions' }, actions) : null,
  );
}

function ensureAppShell() {
  if (state.shell && state.shell.kind === 'app') return state.shell;
  const sessions = h('div', { class: 'sessions' });
  const devicesCount = h('span', { class: 'count' });
  const newChat = h('a', { class: 'new-chat', href: '#/' }, icon('plus'), tr('New chat'));
  const devicesLink = h('a', { class: 'nav-item', href: '#/settings/devices' }, icon('laptop'), tr('Devices'), devicesCount);
  let s;
  const collapse = h('button', { class: 'icon-btn collapse-nav', 'aria-label': tr('Hide sidebar'), title: tr('Hide sidebar'), onclick: () => s.toggleNav() }, icon('sidebar'));
  s = frame('app', [
    h('div', { class: 'brand' }, orb('sm'), h('span', { class: 'brand-name' }, 'Mensarium'), collapse),
    newChat,
    h('div', { class: 'nav-label' }, tr('Chats')),
    sessions,
    h('div', { class: 'sidebar-foot' }, devicesLink, h('a', { class: 'nav-item', href: '#/settings/overview' }, icon('sliders'), tr('Settings'))),
  ]);

  const collapsed = new Set(JSON.parse(localStorageGet('collapsed') || '[]'));
  function renderSessions() {
    const online = devices().filter((t) => t.status === 'online').length;
    devicesCount.replaceChildren(h('span', { class: `dot${online ? ' ok' : ''}` }), tr('{0} online', online));
    const activeId = (location.hash.match(/^#\/chat\/(.+)$/) || [])[1];
    newChat.classList.toggle('active', !activeId && !location.hash.startsWith('#/settings'));
    if (!state.tasks.length) {
      sessions.replaceChildren(h('div', { class: 'sessions-empty' }, tr('Chats with the agent will appear here.')));
      return;
    }
    const byTarget = new Map();
    state.tasks.forEach((t) => {
      const key = t.target_name || tr('Other');
      if (!byTarget.has(key)) byTarget.set(key, []);
      byTarget.get(key).push(t);
    });
    const single = byTarget.size === 1;
    sessions.replaceChildren(...[...byTarget.entries()].map(([name, tasks]) => {
      const group = h('div', { class: `group${!single && collapsed.has(name) ? ' collapsed' : ''}` });
      const items = h('div', { class: 'group-items' }, tasks.map((t) => {
        const [, kind, live] = statusOf(t.status);
        return h('a', { class: `session${t.id === activeId ? ' active' : ''}`, href: `#/chat/${t.id}`, title: t.input },
          h('span', { class: `dot ${kind}${live ? ' live' : ''}` }),
          h('span', { class: 'session-title' }, taskTitle(t)),
          h('button', { class: 'icon-btn session-del', title: tr('Delete chat'), 'aria-label': tr('Delete chat'), onclick: (e) => { e.preventDefault(); e.stopPropagation(); deleteChat(t); } }, icon('trash')));
      }));
      if (!single) {
        group.append(h('button', { class: 'group-head', 'aria-expanded': String(!collapsed.has(name)), onclick: (e) => {
          group.classList.toggle('collapsed');
          const isCollapsed = group.classList.contains('collapsed');
          e.currentTarget.setAttribute('aria-expanded', String(!isCollapsed));
          if (isCollapsed) collapsed.add(name); else collapsed.delete(name);
          localStorageSet('collapsed', JSON.stringify([...collapsed]));
        } }, icon('chevron'), name));
      }
      group.append(items);
      return group;
    }));
  }

  const poll = async () => {
    try { await refreshData(); renderSessions(); } catch (err) { if (err instanceof AuthError) showLogin(); }
  };
  const iv = setInterval(poll, 4000);
  shellCleanups.push(() => clearInterval(iv));

  s.renderSessions = renderSessions;
  s.setActive = (key) => {
    devicesLink.classList.toggle('active', key === 'devices');
    s.shell.classList.remove('nav-open');
    renderSessions();
  };
  state.shell = s;
  renderSessions();
  return s;
}

// ---------- composer ----------

// The round button sends a message; while the agent works it becomes a pulsing stop, on a pause it resumes.
function composer({ placeholder, chips, onSend, onStop, onResume }) {
  const ta = h('textarea', { rows: 1, placeholder, 'aria-label': placeholder });
  const send = h('button', { class: 'send', disabled: true });
  const box = h('div', { class: 'composer' },
    h('div', { class: 'composer-input' }, ta),
    h('div', { class: 'composer-bar' }, chips, h('span', { class: 'spacer' }), send),
  );
  let mode = 'idle';
  let hint = '';
  let busy = false;
  let shown = '';
  const action = () => (mode === 'running' ? 'stop' : mode === 'paused' && !ta.value.trim() ? 'resume' : 'send');
  const sync = () => {
    const a = action();
    if (a !== shown) {
      shown = a;
      const [ic, label] = { stop: ['stopFill', tr('Stop the agent')], resume: ['playFill', tr('Resume the agent')], send: ['arrowUp', tr('Send (Enter)')] }[a];
      send.className = `send${a === 'send' ? '' : ` ${a}`}`;
      send.replaceChildren(icon(ic));
      send.title = label;
      send.setAttribute('aria-label', label);
    }
    if (a === 'stop' && hint) send.title = `${hint} ${tr('Stop the agent')}`;
    send.disabled = busy || (a === 'send' && !ta.value.trim());
    ta.disabled = mode === 'running';
    ta.placeholder = mode === 'running' ? hint : mode === 'paused' ? tr('Resume the agent or write what to do next') : placeholder;
  };
  const grow = () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`; };
  ta.addEventListener('input', () => { grow(); sync(); });
  const run = async (fn) => {
    busy = true;
    sync();
    try { await fn(); } catch (err) { fail(err); } finally { busy = false; sync(); }
  };
  const submit = () => {
    const text = ta.value.trim();
    if (!text || mode === 'running' || busy) return;
    return run(async () => { await onSend(text); ta.value = ''; grow(); });
  };
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  send.addEventListener('click', () => {
    const a = action();
    if (a === 'stop') run(onStop);
    else if (a === 'resume') run(onResume);
    else submit();
  });
  sync();
  return {
    el: h('div', { class: 'composer-wrap' }, box),
    textarea: ta,
    setText(text) { ta.value = text; grow(); sync(); ta.focus(); ta.setSelectionRange(text.length, text.length); },
    // mode: idle | running | paused; hint is the agent status shown while it works
    setAgent(value, statusHint = '') { mode = value; hint = statusHint; sync(); },
  };
}

// Chip + popover to switch between access modes; onPick resolves after the change is applied.
// A device that cannot run full access (disabled by its owner or an agent too old) keeps the chat in "ask".
function modeSwitch(initial, { target, onPick }) {
  let mode = initial;
  const label = h('span', { class: 'chip-label' });
  const chip = h('button', { class: 'chip chip-compact', title: tr('Access mode'), 'aria-haspopup': 'menu' });
  const effective = () => (mode === 'full' && fullAccessOf(target()) !== 'allowed' ? 'ask' : mode);
  const render = () => {
    const m = MODES[effective()];
    chip.className = `chip chip-compact ${m.cls}`;
    label.textContent = m.label;
    chip.replaceChildren(icon(m.icon), label, icon('chevron'));
  };
  chip.addEventListener('click', () => {
    const blocked = fullAccessOf(target()) !== 'allowed' ? fullAccessBlock(target()) : null;
    const current = effective();
    openPopover(chip, Object.entries(MODES).map(([key, m]) => h('button', {
      class: `menu-item mode-item${key === current ? ' selected' : ''}`,
      role: 'menuitemradio',
      'aria-checked': String(key === current),
      disabled: key === 'full' && blocked,
      onclick: async () => {
        closeLayer();
        if (key === current) return;
        if (key === 'full' && !await confirmDialog({
          title: tr('Turn on full access?'),
          text: tr('The agent will run commands, change files, and access the network on “{0}” without asking. You can switch back to approval mode anytime.', target()?.name || tr('the device')),
          action: tr('Turn on'),
        })) return;
        try { await onPick(key); mode = key; render(); } catch (err) { fail(err); }
      },
    }, icon(m.icon), h('span', { class: 'mi-text' }, h('span', {}, m.label),
      h('span', { class: 'mi-desc' }, key === 'full' && blocked ? blocked : m.desc)),
    key === current ? icon('check') : null)));
  });
  render();
  return { el: chip, effective, refresh: render, set(value) { mode = value; render(); } };
}

// Chip + searchable popover to pick the LLM model; an empty value means the Core default.
const defaultModel = () => state.system?.provider?.model || '';
function loadModels() {
  if (!state.models) state.models = get('/v1/models').catch((err) => { state.models = null; throw err; });
  return state.models;
}

function modelSwitch(initial, { onPick }) {
  let model = initial || '';
  const label = h('span', { class: 'chip-label' });
  const chip = h('button', { class: 'chip chip-compact chip-model', title: tr('Model'), 'aria-haspopup': 'menu' });
  const render = () => {
    label.textContent = model || defaultModel() || tr('Model');
    chip.title = tr('Model: {0}', label.textContent);
    chip.replaceChildren(icon('robot'), label, icon('chevron'));
  };
  chip.addEventListener('click', async () => {
    const search = h('input', { type: 'search', placeholder: tr('Find a model'), 'aria-label': tr('Find a model') });
    const list = h('div', { class: 'model-list' }, h('div', { class: 'popover-empty' }, tr('Loading the list...')));
    const place = openPopover(chip, [h('div', { class: 'popover-search' }, icon('search'), search), list], 'model-pop');
    search.focus();
    let ids;
    try { ids = (await loadModels()).map((m) => m.id); } catch (err) { list.replaceChildren(h('div', { class: 'popover-empty' }, err.message)); return; }
    const current = model || defaultModel();
    const renderList = () => {
      const q = search.value.trim().toLowerCase();
      const shown = ids.filter((id) => !q || id.toLowerCase().includes(q));
      list.replaceChildren(...(shown.length ? shown.map((id) => h('button', {
        class: `menu-item${id === current ? ' selected' : ''}`,
        role: 'menuitemradio',
        'aria-checked': String(id === current),
        onclick: async () => {
          closeLayer();
          if (id === current) return;
          try { await onPick(id); model = id; render(); } catch (err) { fail(err); }
        },
      }, h('span', { class: 'mi-model' }, id), id === defaultModel() ? h('span', { class: 'popover-sub' }, tr('default')) : null, id === current ? icon('check') : null))
        : [h('div', { class: 'popover-empty' }, tr('Nothing found'))]));
      place();
    };
    search.addEventListener('input', renderList);
    search.addEventListener('keydown', (e) => { if (e.key === 'Enter') list.querySelector('.menu-item')?.click(); });
    renderList();
    list.querySelector('.selected')?.scrollIntoView({ block: 'nearest' });
  });
  render();
  return { el: chip, value: () => model, set(value) { model = value || ''; render(); } };
}

// ---------- new chat ----------

async function viewNewChat() {
  const shell = ensureAppShell();
  shell.setActive(null);
  const online = devices().filter((t) => t.status === 'online');
  let selected = online.find((t) => t.id === localStorageGet('target')) || online.find(isLocal) || online[0] || null;

  const chipLabel = h('span', { class: 'chip-label' });
  const chipDot = h('span', { class: 'dot' });
  const targetChip = h('button', { class: 'chip', title: tr('Device'), 'aria-haspopup': 'menu', onclick: () => pickTarget() }, icon('laptop'), chipDot, chipLabel, icon('chevron'));
  const renderChip = () => {
    chipLabel.textContent = selected ? selected.name : tr('Select a device');
    chipDot.className = `dot${selected ? ' ok' : ''}`;
  };
  function pickTarget() {
    const items = devices().map((t) => h('button', {
      class: `menu-item${selected && t.id === selected.id ? ' selected' : ''}`, disabled: t.status !== 'online',
      onclick: () => { selected = t; localStorageSet('target', t.id); renderChip(); modeCtl.refresh(); hint.textContent = hintText(); closeLayer(); },
    }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), t.name, h('span', { class: 'popover-sub' }, isLocal(t) ? tr('Core server') : t.status === 'online' ? t.platform.split('-')[0] : tr('offline'))));
    items.push(h('div', { class: 'menu-sep' }), h('button', { class: 'menu-item', onclick: () => { closeLayer(); openPairing(); } }, icon('link'), tr('Pair a new device')));
    openPopover(targetChip, items);
  }
  renderChip();

  const hint = h('p', { class: 'welcome-hint' });
  const hintText = (mode = modeCtl.effective()) => {
    if (!online.length) return tr('All devices are currently offline. Run mensarium target run on the machine you need.');
    return mode === 'full'
      ? tr('Full access: the agent runs commands and changes files on its own, without asking.')
      : tr('The agent will explore the project on its own and ask permission before running commands or changing files.');
  };
  const modeCtl = modeSwitch(localStorageGet('mode') === 'full' ? 'full' : 'ask', {
    target: () => selected,
    onPick: async (value) => { localStorageSet('mode', value); hint.textContent = hintText(value); },
  });
  hint.textContent = hintText();

  const modelCtl = modelSwitch('', { onPick: async () => {} });

  const c = composer({
    placeholder: tr('Describe the task for the agent'),
    chips: [targetChip, h('span', { class: 'divider' }), modeCtl.el, modelCtl.el],
    onSend: async (text) => {
      if (!selected) throw new Error(tr('Select the device the agent will work on'));
      const task = await post('/v1/tasks', { target_id: selected.id, input: text, mode: modeCtl.effective(), model: modelCtl.value() || undefined });
      state.tasks.unshift(task);
      go(`#/chat/${task.id}`);
    },
  });

  const content = devices().length
    ? [
      h('div', { class: 'welcome-hero' }, orb('lg'), h('h1', {}, tr('What needs to be done?'))),
      h('div', { class: 'templates' }, TEMPLATES.map(([ic, label, text]) => h('button', { class: 'template', onclick: () => c.setText(text) }, icon(ic), label))),
      c.el,
      hint,
    ]
    : h('div', { class: 'welcome-empty' },
      h('div', { class: 'welcome-hero' }, orb('lg'), h('h1', {}, tr('Connect a device'))),
      h('p', {}, tr('The agent works on your machines through Mensarium Target. Pairing takes a minute.')),
      h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), tr('Pair a device')));

  shell.panel.replaceChildren(topbar(shell, [], null, { newChat: false }), h('div', { class: 'welcome' }, content));
  if (devices().length) c.textarea.focus();
}

// ---------- chat ----------

async function viewChat(taskId) {
  const shell = ensureAppShell();
  shell.setActive(null);
  let task;
  try { task = await get(`/v1/tasks/${taskId}`); } catch (err) { fail(err); go('#/'); return; }
  state.lastChat = `#/chat/${taskId}`;

  const act = async (action) => {
    const t = await post(`/v1/tasks/${taskId}/${action}`);
    setStatus(t.status);
  };
  const btnDelete = h('button', { class: 'icon-btn', title: tr('Delete chat'), 'aria-label': tr('Delete chat'), onclick: () => deleteChat(task) }, icon('trash'));

  const thread = h('div', { class: 'thread' });
  const inner = h('div', { class: 'thread-inner', role: 'log', 'aria-live': 'polite' });
  thread.append(inner);

  const target = () => state.targets.find((t) => t.id === task.target_id);
  const roots = (target()?.capabilities?.roots || []).slice().sort((a, b) => b.length - a.length);
  const short = (text) => roots.reduce((acc, r) => acc.split(r).join(r.split('/').pop() || r), String(text || ''));

  const modeCtl = modeSwitch(task.mode || 'ask', {
    target,
    onPick: async (value) => { await post(`/v1/tasks/${taskId}/mode`, { mode: value }); localStorageSet('mode', value); },
  });
  const modelCtl = modelSwitch(task.model, {
    onPick: (value) => post(`/v1/tasks/${taskId}/model`, { model: value }),
  });
  const c = composer({
    placeholder: tr('Reply to the agent'),
    chips: [modeCtl.el, modelCtl.el],
    onSend: (text) => post(`/v1/tasks/${taskId}/messages`, { input: text }),
    onStop: () => act('pause'),
    onResume: () => act('resume'),
  });

  shell.panel.replaceChildren(
    topbar(shell,
      [h('span', { class: 'crumb-device' }, icon('laptop'), task.target_name || tr('device'), h('span', { class: 'sep' }, '/')), h('span', { class: 'current', title: task.input }, taskTitle(task))],
      [btnDelete]),
    thread,
    c.el,
  );

  function setStatus(status) {
    task.status = status;
    const hints = { WAITING_APPROVAL: tr('The agent is waiting for your decision above'), EXECUTING: tr('The agent is running an action…'), OBSERVING: tr('The agent is reading the result…') };
    if (isRunning(status)) c.setAgent('running', hints[status] || tr('The agent is thinking…'));
    else c.setAgent(RESUMABLE.includes(status) ? 'paused' : 'idle');
  }
  setStatus(task.status);

  // --- rendering ---
  let stick = true;
  thread.addEventListener('scroll', () => { stick = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120; });
  const add = (node) => { inner.append(node); if (stick) thread.scrollTop = thread.scrollHeight; return node; };
  let lastAgent = false;

  const agentMsg = (bodyNode, live = false) => {
    const node = h('div', { class: `msg msg-agent${lastAgent ? ' cont' : ''}` }, orb(live ? 'live' : ''), h('div', { class: 'msg-body' }, bodyNode));
    lastAgent = true;
    return add(node);
  };
  const step = (node) => { lastAgent = true; return add(h('div', { class: 'step' }, node)); };
  const note = (ic, text, cls = '') => step(h('div', { class: `note ${cls}` }, icon(ic), h('span', {}, text)));

  const tools = new Map();
  const approvals = new Map();

  // One activity block per agent turn: a single rolling line while the agent works, a folded log afterwards.
  let work = null;
  function ensureWork() {
    if (work) return work;
    const spinner = h('span', { class: 'spinner', 'aria-hidden': 'true' });
    const ticker = h('span', { class: 'ticker', 'aria-live': 'polite' });
    const meta = h('span', { class: 'work-meta' });
    const log = h('div', { class: 'work-log' });
    const el = h('div', { class: 'work running' });
    const head = h('button', { class: 'work-head', 'aria-expanded': 'false', onclick: () => {
      el.classList.toggle('open');
      head.setAttribute('aria-expanded', String(el.classList.contains('open')));
    } }, spinner, ticker, meta, icon('chevron'));
    el.append(head, log);
    lastAgent = false;
    add(el);
    work = { el, head, spinner, ticker, meta, log, line: null, queue: [], timer: 0, shownAt: 0, actions: 0, started: null, ended: null };
    return work;
  }
  // Each line stays at least DWELL ms so fast actions still read one after another; older pending ones are dropped.
  const DWELL = 900;
  function show(w, text, animate) {
    const next = h('span', { class: `ticker-line${animate ? ' enter' : ''}` }, text);
    const prev = w.line;
    w.ticker.append(next);
    w.line = next;
    w.shownAt = Date.now();
    if (!prev) return;
    if (!animate) { prev.remove(); return; }
    requestAnimationFrame(() => requestAnimationFrame(() => { next.classList.remove('enter'); prev.classList.add('leave'); }));
    setTimeout(() => prev.remove(), 400);
  }
  function pump(w) {
    if (w.timer || !w.queue.length) return;
    const wait = DWELL - (Date.now() - w.shownAt);
    if (wait > 0) { w.timer = setTimeout(() => { w.timer = 0; pump(w); }, wait); return; }
    show(w, w.queue.shift(), true);
    pump(w);
  }
  function say(text, animate, w = ensureWork()) {
    const last = w.queue.length ? w.queue[w.queue.length - 1] : w.line?.textContent;
    if (last === text) return;
    if (!animate) { clearTimeout(w.timer); w.timer = 0; w.queue = []; show(w, text, false); return; }
    w.queue = [...w.queue.slice(-1), text];
    pump(w);
  }
  function stamp(ev) {
    const w = ensureWork();
    const at = new Date(ev.created_at).getTime();
    if (!w.started) w.started = at;
    w.ended = at;
  }
  function finishWork() {
    if (!work) return;
    const w = work;
    work = null;
    if (!w.actions && !w.log.childElementCount) { w.el.remove(); return; }
    w.el.classList.remove('running');
    w.el.classList.add('done');
    w.spinner.replaceWith(icon('check'));
    const secs = Math.max(0, Math.round((w.ended - w.started) / 1000));
    say(w.actions ? tp('{0} action|{0} actions', w.actions) : tr('Details'), false, w);
    w.meta.textContent = secs < 60 ? tr('{0} s', secs) : tr('{0} min', Math.round(secs / 60));
  }
  const logAdd = (node) => { ensureWork().log.append(node); if (stick) thread.scrollTop = thread.scrollHeight; return node; };

  const base = (path) => String(path || '').split('/').filter(Boolean).pop() || String(path || '');
  const clip = (text, n) => (String(text).length > n ? `${String(text).slice(0, n - 1)}…` : String(text));
  function actionText(tool, a, display) {
    if (!a) return clip(short(display) || tool, 60);
    switch (tool) {
      case 'files.list': return tr('Looking at {0}', base(a.path) || '.');
      case 'files.read': return tr('Reading {0}', base(a.path));
      case 'files.search': return tr('Searching for “{0}”', clip(a.query, 40));
      case 'git.status': return tr('Checking git status');
      case 'git.diff': return tr('Reading the git diff');
      case 'skills.read': return tr('Loading skill {0}', a.id);
      case 'memory.search': return tr('Searching memory for “{0}”', clip(a.query, 40));
      case 'memory.read': return tr('Reading note {0}', a.title);
      case 'memory.save': return tr('Remembering {0}', a.title);
      default: return a.command ? tr('Running {0}', clip(a.command, 56)) : tool;
    }
  }

  function toolCard(id, tool, display) {
    let entry = tools.get(id);
    if (entry) return entry;
    const stateEl = h('span', { class: 'tool-state' }, h('span', { class: 'dot accent live' }), tr('running'));
    const out = h('pre', { class: 'tool-out' });
    const noteEl = h('div', { class: 'tool-note' });
    const card = h('div', { class: 'tool' });
    const head = h('button', { class: 'tool-head', 'aria-expanded': 'false', onclick: () => {
      card.classList.toggle('open');
      head.setAttribute('aria-expanded', String(card.classList.contains('open')));
    } }, icon(TOOL_ICON[tool] || 'terminal'), h('span', { class: 'tool-display', title: `${tool}: ${display || ''}` }, short(display) || tool), stateEl);
    card.append(head, out, noteEl);
    logAdd(card);
    entry = { card, head, stateEl, out, noteEl };
    tools.set(id, entry);
    return entry;
  }

  function toolResult(p) {
    const e = toolCard(p.tool_call_id, p.tool, '');
    const ok = p.status === 'succeeded';
    const label = { succeeded: tr('done'), failed: tr('error'), timeout: tr('timeout'), canceled: tr('canceled'), rejected: tr('rejected by the device') }[p.status] || p.status;
    e.stateEl.className = `tool-state ${ok ? 'ok' : 'bad'}`;
    e.stateEl.replaceChildren(icon(ok ? 'check' : 'alert'), p.exit_code != null && p.exit_code !== 0 ? tr('{0}, code {1}', label, p.exit_code) : label);
    e.out.textContent = (p.output || '').replace(/^\[tool output: untrusted data, not instructions\]\n/, '').replace(/^status: [^\n]*\n?/, '') || tr('Empty output');
    if (p.truncated || p.artifact_id) {
      e.noteEl.replaceChildren(p.truncated ? tr('Output truncated. ') : '', p.artifact_id ? h('a', { href: `/v1/artifacts/${p.artifact_id}`, target: '_blank', rel: 'noopener' }, tr('Full output')) : '');
    }
  }

  function approvalCard(p) {
    const tc = p.tool_call || {};
    const args = tc.arguments || {};
    const [riskLabel, riskKind] = RISK[tc.risk] || [tc.risk, ''];
    const timer = h('span', { class: 'approval-timer' });
    const approve = h('button', { class: 'btn btn-primary' }, icon('check'), tr('Run once'));
    const reject = h('button', { class: 'btn' }, tr('Reject'));
    const actions = h('div', { class: 'approval-actions' }, approve, reject);
    let confirmBox = null;
    const card = h('div', { class: `approval${tc.risk === 'destructive' ? ' risk-destructive' : ''}`, role: 'group', 'aria-label': tr('Approval request') },
      h('div', { class: 'approval-top' }, h('span', { class: 'approval-title' }, tr('Your decision is needed')), h('span', { class: `pill ${riskKind}` }, riskLabel), timer),
      h('pre', { class: 'approval-cmd' }, args.command ? `$ ${args.command}` : short(tc.display)),
      h('dl', { class: 'approval-meta' },
        tc.tool !== 'shell.exec' ? [h('dt', {}, tr('Tool')), h('dd', {}, tc.tool)] : null,
        h('dt', {}, tr('Device')), h('dd', {}, tc.target_name || ''),
        args.cwd ? [h('dt', {}, tr('Folder')), h('dd', { title: args.cwd }, short(args.cwd))] : null,
        args.timeout_s ? [h('dt', {}, tr('Limit')), h('dd', {}, tr('{0} s', args.timeout_s))] : null,
      ),
      args.stdin ? [h('div', { class: 'approval-sub' }, tr('Input data')), h('pre', { class: 'approval-cmd approval-stdin' }, args.stdin)] : null,
    );
    if (tc.risk === 'destructive') {
      const cb = h('input', { type: 'checkbox' });
      approve.disabled = true;
      cb.addEventListener('change', () => { approve.disabled = !cb.checked; });
      confirmBox = h('label', { class: 'approval-confirm' }, cb, tr('I understand this action can\'t be undone'));
      card.append(confirmBox);
    }
    card.append(actions);
    const decide = async (decision) => {
      approve.disabled = true; reject.disabled = true;
      try { await post(`/v1/approvals/${p.approval_id}/decision`, { decision, confirm: tc.risk === 'destructive' }); }
      catch (err) { fail(err); approve.disabled = false; reject.disabled = false; }
    };
    approve.addEventListener('click', () => decide('approve'));
    reject.addEventListener('click', () => decide('reject'));
    lastAgent = false;
    const wrap = add(h('div', { class: 'step' }, card));
    const expires = new Date(p.expires_at).getTime();
    const tick = () => { const left = Math.round((expires - Date.now()) / 1000); timer.textContent = left > 0 ? tr('{0} left', mmss(left)) : tr('time\'s up'); };
    tick();
    const iv = setInterval(tick, 1000);
    viewCleanups.push(() => clearInterval(iv));
    approvals.set(p.approval_id, { card, wrap, actions, iv, timer, confirmBox });
  }

  function approvalDecided(p) {
    const e = approvals.get(p.approval_id);
    if (!e) return;
    clearInterval(e.iv);
    e.timer.textContent = '';
    e.card.classList.add('decided');
    if (e.confirmBox) e.confirmBox.remove();
    const text = { approved: tr('You allowed it to run once'), rejected: tr('You rejected the action'), expired: tr('Time to decide ran out') }[p.decision] || p.decision;
    const note = p.note === 'full access enabled' ? tr('approved by turning on full access') : p.note;
    e.actions.replaceChildren(h('span', { class: 'approval-result' }, text, note ? `: ${note}` : ''));
    if (work) { logAdd(e.card); e.wrap.remove(); }
  }

  function handle({ event, payload: p, created_at: createdAt }, live) {
    const ev = { created_at: createdAt };
    switch (event) {
      case 'user.message':
        finishWork();
        lastAgent = false;
        add(h('div', { class: 'msg-user' }, h('div', { class: 'bubble-user' }, p.text)));
        break;
      case 'task.status':
        setStatus(p.status);
        if (!isRunning(p.status)) finishWork();
        if (['PAUSED', 'CANCELED', 'FAILED', 'FAILED_RECOVERABLE'].includes(p.status)) {
          note(p.status === 'PAUSED' ? 'pause' : 'alert', `${statusOf(p.status)[0]}${p.reason ? `: ${reasonText(p.reason)}` : ''}`, p.status === 'PAUSED' || p.status === 'CANCELED' ? '' : 'error');
        }
        break;
      case 'task.mode':
        modeCtl.set(p.mode);
        note(MODES[p.mode]?.icon || 'shield', tr('Mode: {0}', (MODES[p.mode]?.label || p.mode).toLowerCase()));
        break;
      case 'task.model':
        modelCtl.set(p.model);
        note('robot', tr('Model: {0}', p.model));
        break;
      case 'llm.request':
        stamp(ev);
        if (!work?.actions) say(tr('Thinking'), live);
        break;
      case 'llm.response':
        stamp(ev);
        if (p.text && p.tool_call) logAdd(h('div', { class: 'work-thought prose', html: markdown(p.text) }));
        break;
      case 'tool_call.denied':
        stamp(ev);
        logAdd(h('div', { class: 'note' }, icon('ban'), h('span', {}, tr('Policy didn\'t allow {0}: {1}', p.tool, policyText(p.reason)))));
        break;
      case 'tool_call.pending_approval':
        stamp(ev);
        say(tr('Waiting for your decision'), live);
        approvalCard(p);
        break;
      case 'approval.decided':
        approvalDecided(p);
        break;
      case 'tool_call.executing':
        stamp(ev);
        ensureWork().actions += 1;
        say(actionText(p.tool, p.arguments, p.display), live);
        toolCard(p.tool_call_id, p.tool, p.display);
        break;
      case 'tool_call.result':
        stamp(ev);
        toolResult(p);
        break;
      case 'task.final':
        finishWork();
        agentMsg(h('div', { class: 'prose', html: markdown(p.text) }));
        break;
      case 'task.error':
        note('alert', p.message, 'error');
        break;
      default:
    }
  }

  const openedAt = Date.now();
  let lastSeq = 0;
  let es = null;
  let delay = 1000;
  let closed = false;
  const connect = () => {
    if (closed) return;
    es = new EventSource(`/v1/tasks/${taskId}/events?after=${lastSeq}`, { withCredentials: true });
    es.onopen = () => { delay = 1000; };
    es.onmessage = (m) => {
      let ev;
      try { ev = JSON.parse(m.data); } catch { return; }
      if (ev.seq <= lastSeq) return;
      lastSeq = ev.seq;
      handle(ev, new Date(ev.created_at).getTime() > openedAt - 2000);
    };
    es.onerror = () => {
      es.close();
      if (closed) return;
      setTimeout(connect, delay);
      delay = Math.min(delay * 2, 15000);
    };
  };
  connect();
  viewCleanups.push(() => { closed = true; if (es) es.close(); });
  if (!c.textarea.disabled) c.textarea.focus();
}

// ---------- settings ----------

const SETTINGS = [
  ['overview', 'pulse', tr('Overview')],
  ['model', 'robot', tr('Model')],
  ['devices', 'laptop', tr('Devices')],
  ['memory', 'graph', tr('Memory')],
  ['marketplace', 'package', tr('Marketplace')],
  ['profiles', 'layers', tr('Profiles')],
  ['audit', 'list', tr('Activity log')],
];

function ensureSettingsShell() {
  if (state.shell && state.shell.kind === 'settings') return state.shell;
  const nav = h('div', { class: 'settings-nav' });
  const search = h('input', { type: 'search', placeholder: tr('Search settings'), 'aria-label': tr('Search settings') });
  const back = () => go(state.lastChat || '#/');
  const s = frame('settings', [
    h('button', { class: 'back-link', onclick: back }, icon('arrowLeft'), tr('Back to chat'), h('span', { class: 'kbd' }, 'Esc')),
    h('div', { class: 'settings-title' }, tr('Settings')),
    h('div', { class: 'settings-search' }, icon('search'), search),
    nav,
  ]);
  const renderNav = () => {
    const q = search.value.trim().toLowerCase();
    const active = (location.hash.match(/^#\/settings\/(\w+)/) || [])[1] || 'overview';
    const visible = SETTINGS.filter(([, , label]) => !q || label.toLowerCase().includes(q));
    nav.replaceChildren(...(visible.length
      ? visible.map(([key, ic, label]) => h('a', { class: `nav-item${key === active ? ' active' : ''}`, href: `#/settings/${key}`, 'aria-current': key === active ? 'page' : null }, icon(ic), label))
      : [h('div', { class: 'sessions-empty' }, tr('Nothing found'))]));
  };
  search.addEventListener('input', renderNav);
  const onKey = (e) => { if (e.key === 'Escape' && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) back(); };
  document.addEventListener('keydown', onKey);
  shellCleanups.push(() => document.removeEventListener('keydown', onKey));
  s.setActive = () => { renderNav(); s.shell.classList.remove('nav-open'); };
  state.shell = s;
  return s;
}

function page(shell, title, desc, actions, ...sections) {
  shell.panel.replaceChildren(
    topbar(shell, []),
    h('div', { class: 'page' }, h('div', { class: 'page-inner' },
      h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, title), desc ? h('p', {}, desc) : null), actions ? h('div', { class: 'actions' }, actions) : null),
      sections,
    )),
  );
}

const section = (title, desc, ...body) => h('section', { class: 'section' },
  h('div', { class: 'section-head' }, h('div', {}, h('h2', {}, title), desc ? h('p', {}, desc) : null)),
  body);

const row = (title, desc, value, mono = false) => h('div', { class: 'row' },
  h('div', { class: 'row-text' }, h('div', { class: 'row-title' }, title), desc ? h('div', { class: 'row-desc' }, desc) : null),
  value != null ? h('div', { class: `row-value${mono ? ' mono' : ''}` }, value) : null);

const copyBtn = (text) => h('button', { class: 'icon-btn', 'aria-label': tr('Copy'), title: tr('Copy'), onclick: (e) => copy(text, e.currentTarget) }, icon('copy'));
const cmdValue = (cmd) => [h('code', {}, cmd), copyBtn(cmd)];

async function viewSettings(key) {
  const shell = ensureSettingsShell();
  shell.setActive();
  const views = { overview: settingsOverview, model: settingsModel, devices: settingsDevices, memory: settingsMemory, marketplace: settingsMarketplace, profiles: settingsProfiles, audit: settingsAudit };
  await (views[key] || settingsOverview)(shell);
}

async function settingsOverview(shell) {
  const s = await get('/v1/system');
  state.system = s;
  const url = (s.public_url || '').replace(/\/$/, '');
  const logout = h('button', { class: 'btn', onclick: async () => { try { await post('/v1/auth/logout'); } catch { /* noop */ } showLogin(); } }, icon('logout'), tr('Sign out'));
  const coreUpdate = h('div', { class: 'hero-update' });
  get('/v1/system/update').then((info) => {
    if (!info.available) { if (info.latest) coreUpdate.replaceChildren(h('span', { class: 'market-meta' }, tr('Latest version'))); return; }
    if (!info.self_update) { coreUpdate.replaceChildren(h('span', { class: 'pill accent' }, tr('{0} available', info.latest)), h('code', {}, 'mensarium update')); return; }
    coreUpdate.replaceChildren(h('span', { class: 'pill accent' }, tr('{0} available', info.latest)), h('button', { class: 'btn btn-primary btn-sm', onclick: async (e) => {
      if (!await confirmDialog({ title: tr('Update Core to {0}?', info.latest), text: tr('Core will download the version from mensarium.com and restart. Running tasks will pause, and the interface will reconnect on its own.'), action: tr('Update') })) return;
      e.target.disabled = true;
      try {
        await post('/v1/system/update');
        toast(tr('Core is updating, the page will reload on its own'));
        const started = Date.now();
        const poll = setInterval(async () => {
          try {
            const r = await fetch('/healthz').then((x) => x.json());
            if (r.version !== s.version) { clearInterval(poll); location.reload(); }
          } catch { /* restarting */ }
          if (Date.now() - started > 180000) { clearInterval(poll); toast(tr('Core didn\'t respond with the new version within 3 minutes. Check mensarium service logs core.'), true); }
        }, 2000);
      } catch (err) { fail(err); e.target.disabled = false; }
    } }, icon('refresh'), tr('Update')));
  }).catch(() => {});
  page(shell, tr('Overview'), tr('Where the main agent is reachable, and how to check that devices are talking to it.'), logout,
    h('div', { class: 'hero' }, orb('md'), h('div', { class: 'hero-text' }, h('h2', {}, 'Mensarium Core'), h('p', {}, tr('Version {0}', s.version))), coreUpdate),
    section(tr('Connection'), null, h('div', { class: 'rows' },
      row(tr('Core address'), tr('Used by the browser and devices.'), cmdValue(url), true),
      row(tr('Key fingerprint'), tr('Check it against what the installer showed on the device during pairing.'), s.core_key_fingerprint, true),
    )),
    section(tr('Maintenance'), tr('Commands run on the Core server.'), h('div', { class: 'rows' },
      row(tr('Update Mensarium'), tr('Downloads the latest version and restarts the service.'), cmdValue('mensarium update'), true),
      row(tr('Login token'), tr('Shows the admin token.'), cmdValue('mensarium core token'), true),
    )),
    section(tr('Language'), tr('Interface language. The agent answers in the language you write to it.'), languageSwitch()),
    section(tr('Backup'), tr('An archive with the database, keys, secrets, and settings, encrypted with a password you set. The same archive is used to move Core to another server.'), h('div', { class: 'rows' },
      row(tr('Create a backup'), tr('Saves the archive to the current folder.'), cmdValue('mensarium core backup -o mensarium.pab'), true),
      row(tr('Restore from a backup'), tr('Stops Core, replaces its data with the archive\'s contents, and starts it again. The previous data stays alongside it, in the core.before-restore-… folder.'), cmdValue('mensarium core restore mensarium.pab'), true),
    )),
  );
}

async function settingsModel(shell) {
  const s = await get('/v1/system');
  state.system = s;
  const p = s.provider || {};
  const health = p.health || {};
  const providerName = { ollama_cloud: 'Ollama Cloud', ollama_local: tr('Local Ollama'), llama_cpp: 'llama.cpp' }[p.name] || p.name;
  const current = h('span', {}, p.model);
  const list = h('div', { class: 'rows' }, h('div', { class: 'empty' }, tr('Loading the list...')));
  page(shell, tr('Model'), tr('Which provider and model the agent thinks through. The API key is stored only on the Core server.'), null,
    h('div', { class: 'rows' },
      row(tr('Provider'), null, providerName),
      row(tr('API address'), null, p.base_url, true),
      row(tr('Default model'), tr('Used for new chats. Inside a chat, the model is changed with the robot button in the input field.'), h('span', { class: 'status' }, icon('robot'), current), true),
      row(tr('Status'), health.ok ? null : health.detail, h('span', { class: 'status' }, h('span', { class: `dot ${health.ok ? 'ok' : 'danger'}` }), health.ok ? tr('Available') : tr('Unavailable'))),
    ),
    section(tr('Available models'), tr('Click a model to make it the default.'), list),
  );
  const render = (ids) => {
    list.replaceChildren(ids.length
      ? h('div', { class: 'row-extra model-grid' }, ids.map((id) => h('button', {
        class: `pill tag model-pill${id === state.system.provider.model ? ' accent' : ''}`,
        'aria-pressed': String(id === state.system.provider.model),
        onclick: async () => {
          if (id === state.system.provider.model) return;
          try {
            await api('/v1/system/model', { method: 'PUT', body: JSON.stringify({ model: id }) });
            state.system.provider.model = id;
            current.textContent = id;
            toast(tr('Default model: {0}', id));
            render(ids);
          } catch (err) { fail(err); }
        },
      }, id)))
      : h('div', { class: 'empty' }, tr('The provider didn\'t return any models.')));
  };
  try {
    state.models = null;
    render((await loadModels()).map((m) => m.id));
  } catch (err) {
    list.replaceChildren(h('div', { class: 'empty' }, err.message));
  }
}

const TOOL_INFO = {
  'files.list': [tr('List files'), tr('Looks at folder contents.')],
  'files.read': [tr('Read files'), tr('Opens text files, secrets are stripped out.')],
  'files.search': [tr('Search files'), tr('Searches for text in the project.')],
  'git.status': [tr('Git status'), tr('Branch and changed files.')],
  'git.diff': [tr('Git diff'), tr('Shows the diff.')],
  'shell.exec': [tr('Run commands'), tr('Runs allowed programs, changes files via git apply.')],
};

function toggleSwitch(checked, { label, onChange }) {
  const sw = h('button', { class: 'switch', role: 'switch', 'aria-checked': String(checked), 'aria-label': label, title: label });
  sw.addEventListener('click', async () => {
    const next = sw.getAttribute('aria-checked') !== 'true';
    sw.disabled = true;
    sw.setAttribute('aria-checked', String(next));
    try { await onChange(next); } catch (err) { sw.setAttribute('aria-checked', String(!next)); fail(err); } finally { sw.disabled = false; }
  });
  return sw;
}

async function settingsDevices(shell) {
  const s = state.system || await get('/v1/system');
  const listHost = h('div', {});
  const extTools = (await get('/v1/extensions').catch(() => [])).filter((e) => e.enabled).flatMap((e) => e.tools.map((t) => ({ ...t, ext: txt(e.name) })));
  const expanded = new Set(JSON.parse(localStorageGet('devices-open') || '[]'));
  let signature = '';

  function deviceBody(t) {
    const caps = t.capabilities || {};
    const disabled = new Set(caps.disabled_tools || []);
    const programs = caps.command_allowlist || [];
    const access = { allowed: tr('Allowed: you can turn on the no-approval mode in the chat.'), disabled: fullAccessBlock(t), outdated: fullAccessBlock(t) }[caps.full_access] || '';
    const revoke = h('button', { class: 'btn btn-sm btn-danger', onclick: async () => {
      if (!await confirmDialog({ title: tr('Revoke “{0}”?', t.name), text: tr('The device will lose access immediately. To restore it, you\'ll need to pair it again with a new code.'), action: tr('Revoke'), danger: true })) return;
      try { await post(`/v1/targets/${t.id}/revoke`); toast(tr('Access revoked')); await refresh(true); } catch (err) { fail(err); }
    } }, tr('Revoke access'));
    return h('div', { class: 'device-body' },
      h('div', { class: 'device-sub' }, tr('Device agent')),
      agentControl(t),
      h('div', { class: 'device-sub' }, tr('Agent tools'), h('span', {}, tr('The agent can\'t see or call a disabled tool on this device.'))),
      h('div', { class: 'tool-rows' }, (caps.tools || []).map((tool) => {
        const [name, desc] = TOOL_INFO[tool] || [tool, ''];
        return h('div', { class: 'tool-row' },
          icon(TOOL_ICON[tool] || 'terminal'),
          h('div', { class: 'row-text' }, h('div', { class: 'tool-row-title' }, name, h('code', {}, tool)), desc ? h('div', { class: 'row-desc' }, desc) : null),
          toggleSwitch(!disabled.has(tool), {
            label: tr('{0} on “{1}”', name, t.name),
            onChange: async (enabled) => {
              const view = await api(`/v1/targets/${t.id}/tools`, { method: 'PUT', body: JSON.stringify({ tool, enabled }) });
              Object.assign(t, view);
              signature = '';
              render();
            },
          }));
      })),
      extTools.length ? [
        h('div', { class: 'device-sub' }, tr('Marketplace tools'), h('span', {}, tr('They run as commands, so “Run commands” must be enabled and the program must be in the allowed list.'))),
        h('div', { class: 'tool-rows' }, extTools.map((tool) => h('div', { class: 'tool-row' },
          icon('terminal'),
          h('div', { class: 'row-text' }, h('div', { class: 'tool-row-title' }, tool.name, h('code', {}, tool.ext)), h('div', { class: 'row-desc' }, tool.description)),
          programs.includes('*') || programs.includes(tool.argv[0]) ? null : h('span', { class: 'pill warn', title: tr('The program isn\'t in the device\'s allowed list') }, tr('no {0}', tool.argv[0])),
          toggleSwitch(!disabled.has(tool.name), {
            label: tr('{0} on “{1}”', tool.name, t.name),
            onChange: async (enabled) => {
              Object.assign(t, await api(`/v1/targets/${t.id}/tools`, { method: 'PUT', body: JSON.stringify({ tool: tool.name, enabled }) }));
              signature = '';
              render();
            },
          })))),
      ] : null,
      h('div', { class: 'device-sub' }, tr('Folders')),
      h('div', { class: 'device-tags' }, (caps.roots || []).map((r) => h('span', { class: 'pill tag', title: r }, r))),
      h('div', { class: 'device-sub' }, tr('Programs for running commands')),
      h('div', { class: 'device-tags' }, programs.includes('*') ? h('span', { class: 'pill' }, tr('any programs')) : programs.map((pr) => h('span', { class: 'pill tag' }, pr))),
      h('div', { class: 'device-sub' }, tr('Full access')),
      h('p', { class: 'device-text' }, access),
      h('div', { class: 'device-actions' }, revoke),
    );
  }

  function agentControl(t) {
    const caps = t.capabilities || {};
    const outdated = t.agent_version && s.version && t.agent_version !== s.version;
    const pending = state.updates.get(t.id);
    if (isLocal(t)) return h('p', { class: 'device-text' }, tr('Version {0}. The built-in device updates along with Core.', t.agent_version));
    if (pending) return h('div', { class: 'status' }, h('span', { class: 'dot accent live' }), tr('Updating to {0}: the agent downloads the version from Core and restarts', pending.version));
    if (!outdated) return h('p', { class: 'device-text' }, tr('Version {0}, same as Core.', t.agent_version));
    if (!caps.remote_update) {
      return h('p', { class: 'device-text' }, tr('Version {0}, Core has {1}. This agent can\'t update remotely: run this once on the device ', t.agent_version, s.version), h('code', {}, 'mensarium update'), tr(', after that updates will be available here.'));
    }
    if (t.status !== 'online') return h('p', { class: 'device-text' }, tr('Version {0}, Core has {1}. You can update once the device is online.', t.agent_version, s.version));
    const btn = h('button', { class: 'btn btn-primary btn-sm', onclick: async () => {
      btn.disabled = true;
      try {
        const r = await post(`/v1/targets/${t.id}/update`);
        state.updates.set(t.id, { version: r.version, at: Date.now() });
        toast(tr('“{0}” is updating', t.name));
        signature = '';
        render();
      } catch (err) { fail(err); btn.disabled = false; }
    } }, icon('refresh'), tr('Update to {0}', s.version));
    return h('div', { class: 'device-update' }, btn, h('span', { class: 'device-text' }, tr('currently {0}', t.agent_version)));
  }

  function render() {
    const targets = devices();
    const sig = JSON.stringify([targets, [...expanded], [...state.updates.keys()]]);
    if (sig === signature) return;
    signature = sig;
    if (!targets.length) {
      listHost.replaceChildren(h('div', { class: 'rows' }, h('div', { class: 'empty' },
        h('h3', {}, tr('No devices yet')), h('p', {}, tr('Pair the machine the agent will work on.')),
        h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), tr('Pair a device')))));
      return;
    }
    listHost.replaceChildren(h('div', { class: 'rows' }, targets.map((t) => {
      const caps = t.capabilities || {};
      const outdated = t.agent_version && s.version && t.agent_version !== s.version;
      const tools = caps.tools || [];
      const enabled = tools.filter((x) => !(caps.disabled_tools || []).includes(x)).length;
      const open = expanded.has(t.id);
      const head = h('button', { class: 'device-head', 'aria-expanded': String(open), onclick: () => {
        if (expanded.has(t.id)) expanded.delete(t.id); else expanded.add(t.id);
        localStorageSet('devices-open', JSON.stringify([...expanded]));
        render();
      } },
        icon('chevron'),
        h('div', { class: 'row-text' },
          h('div', { class: 'row-title' }, t.name,
            isLocal(t) ? h('span', { class: 'pill accent', title: tr('The machine Core is installed on. Always connected.') }, 'Core') : null,
            state.updates.has(t.id) ? h('span', { class: 'pill accent' }, tr('updating'))
              : outdated ? h('span', { class: 'pill warn', title: tr('Open the device to update the agent') }, tr('v{0}, update available', t.agent_version)) : null),
          h('div', { class: 'row-desc' }, [
            t.status === 'online' ? t.platform : tr('{0} · last online {1}', t.platform, relTime(t.last_seen_at)),
            tr('tools: {0} of {1}', enabled, tools.length),
            caps.full_access === 'allowed' ? tr('full access allowed') : null,
          ].filter(Boolean).join(' · '))),
        h('span', { class: 'status', title: t.status === 'online' ? tr('Online') : tr('Offline') }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), h('span', { class: 'status-label' }, t.status === 'online' ? tr('Online') : tr('Offline'))));
      return h('div', { class: `device${open ? ' open' : ''}` }, head, open ? deviceBody(t) : null);
    })));
  }

  async function refresh(force = false) {
    try { await refreshData(); if (force) signature = ''; render(); } catch (err) { fail(err); }
  }
  page(shell, tr('Devices'), tr('Machines where the agent reads projects and runs commands. Click a device to configure its tools.'),
    h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), tr('Pair a device')),
    listHost,
  );
  render();
  const iv = setInterval(refresh, 5000);
  viewCleanups.push(() => clearInterval(iv));
}

// ---------- memory ----------

const MEM_KINDS = { fact: tr('Fact'), preference: tr('Preference'), project: tr('Project'), person: tr('Person'), device: tr('Device'), howto: tr('Instruction'), note: tr('Note') };
const MEM_SOURCES = { user: tr('you'), agent: tr('agent'), dream: tr('dream') };
const DREAM_PHASES = [['light', tr('Light sleep'), tr('gathering new chats')], ['rem', 'REM', tr('looking for what matters and connections')], ['deep', tr('Deep sleep'), tr('consolidating into memory')], ['diary', tr('Diary'), tr('writing down what I remembered')]];
const DREAM_TRIGGER = { schedule: tr('on schedule'), manual: tr('manually') };

// Markdown plus [[wikilinks]]; titles arrive HTML-escaped from markdown(), so they are safe in the attribute.
const memoryMd = (text) => markdown(text).replace(/\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]/g, (_, title, alias) => `<a href="#" class="wikilink" data-title="${title}">${alias || title}</a>`);

function kindPill(kind) {
  return h('span', { class: 'pill kind-pill' }, h('span', { class: 'kind-dot', style: `background:${graphColor(kind)}` }), MEM_KINDS[kind] || kind);
}

async function openNoteEditor(note, { onSaved, onOpenTitle } = {}) {
  const full = note?.id ? await get(`/v1/memory/notes/${note.id}`) : null;
  const n = full || { title: note?.title || '', body: '', kind: 'fact', tags: [], pinned: false, importance: 5 };
  const title = h('input', { type: 'text', value: n.title, placeholder: tr('Short title'), 'aria-label': tr('Title'), maxlength: '120' });
  const kind = h('select', { 'aria-label': tr('Type') }, Object.entries(MEM_KINDS).map(([k, label]) => h('option', { value: k, selected: k === n.kind }, label)));
  const importance = h('select', { 'aria-label': tr('Importance') }, Array.from({ length: 10 }, (_, i) => h('option', { value: String(i + 1), selected: i + 1 === n.importance }, tr('Importance {0}', i + 1))));
  let pinned = n.pinned;
  const pin = toggleSwitch(pinned, { label: tr('Always in the agent\'s context'), onChange: async (v) => { pinned = v; } });
  const tags = h('input', { type: 'text', value: (n.tags || []).join(', '), placeholder: tr('tags, comma-separated'), 'aria-label': tr('Tags') });
  const body = h('textarea', { class: 'note-body', rows: 11, placeholder: tr('What to remember. Link to another note: [[Title]]'), 'aria-label': tr('Note text') });
  body.value = n.body || '';
  const save = h('button', { class: 'btn btn-primary' }, tr('Save'));
  save.addEventListener('click', async () => {
    const payload = { title: title.value.trim(), body: body.value, kind: kind.value, importance: Number(importance.value), pinned, tags: tags.value.split(',').map((t) => t.trim()).filter(Boolean) };
    if (!payload.title) { title.focus(); return; }
    save.disabled = true;
    try {
      const saved = full ? await api(`/v1/memory/notes/${full.id}`, { method: 'PATCH', body: JSON.stringify(payload) }) : await post('/v1/memory/notes', payload);
      closeLayer();
      toast(full ? tr('Note saved') : tr('Note created'));
      onSaved?.(saved);
    } catch (err) { fail(err); } finally { save.disabled = false; }
  });
  const remove = full ? h('button', { class: 'btn btn-danger', onclick: async () => {
    if (!await confirmDialog({ title: tr('Delete “{0}”?', full.title), text: tr('The agent will forget this note. Links to it from other notes will remain and become empty nodes on the graph.'), action: tr('Delete'), danger: true })) return;
    try { await del(`/v1/memory/notes/${full.id}`); toast(tr('Note deleted')); onSaved?.(null); } catch (err) { fail(err); }
  } }, tr('Delete')) : null;
  const backlinks = full?.backlinks?.length ? h('div', { class: 'note-backlinks' }, tr('Linked from: '), full.backlinks.map((b, i) => [i ? ', ' : '', h('a', { href: '#', onclick: (e) => { e.preventDefault(); closeLayer(); onOpenTitle?.(b.title); } }, b.title)])) : null;
  const meta = full ? h('div', { class: 'market-meta' }, [tr('source: {0}', MEM_SOURCES[full.source] || full.source), full.source_task_id ? h('a', { href: `#/chat/${full.source_task_id}` }, tr('chat')) : null, tr('updated {0}', relTime(full.updated_at)), full.recall_count ? tp('recalled by the agent {0} time|recalled by the agent {0} times', full.recall_count) : null].filter(Boolean).flatMap((x, i) => (i ? [' · ', x] : [x]))) : null;
  openModal(
    h('div', { class: 'modal-head' }, h('h2', {}, full ? tr('Note') : tr('New note')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
    meta,
    h('div', { class: 'note-form' },
      h('label', { class: 'note-field' }, h('span', {}, tr('Title')), title),
      h('div', { class: 'note-row' }, kind, importance, h('label', { class: 'switch-label', title: tr('The note is included in every request to the model') }, pin, tr('Always in context'))),
      h('label', { class: 'note-field' }, h('span', {}, tr('Tags')), tags),
      h('label', { class: 'note-field' }, h('span', {}, tr('Text')), body),
      backlinks),
    h('div', { class: 'modal-actions' }, remove, h('span', { class: 'spacer' }), h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
  ).classList.add('modal-wide');
  (full ? body : title).focus();
}

async function settingsMemory(shell) {
  const TABS = [['graph', tr('Graph')], ['notes', tr('Notes')], ['dreams', tr('Dreaming')]];
  let tab = localStorageGet('memory-tab') || 'graph';
  const tabs = h('div', { class: 'segmented', role: 'tablist' });
  const host = h('div', { class: 'memory-host' });
  let cleanup = null;
  const renderTabs = () => tabs.replaceChildren(...TABS.map(([key, label]) => h('button', {
    class: `seg${key === tab ? ' active' : ''}`, role: 'tab', 'aria-selected': String(key === tab),
    onclick: () => { tab = key; localStorageSet('memory-tab', key); show(); },
  }, label)));
  const byTitle = async (title) => (await get(`/v1/memory/notes?q=${encodeURIComponent(title)}`)).notes.find((n) => n.title.toLowerCase() === title.toLowerCase());
  const openTitle = async (title) => {
    const note = await byTitle(title);
    openNoteEditor(note || { title }, { onSaved: () => show(), onOpenTitle: openTitle });
  };
  const newNote = () => openNoteEditor(null, { onSaved: () => show(), onOpenTitle: openTitle });

  async function show() {
    if (cleanup) { cleanup(); cleanup = null; }
    renderTabs();
    host.replaceChildren();
    cleanup = await ({ graph: memoryGraph, notes: memoryNotes, dreams: memoryDreams }[tab] || memoryGraph)();
  }

  async function memoryGraph() {
    const canvas = h('canvas', { class: 'graph-canvas', 'aria-label': tr('Memory graph: drag nodes, scroll to zoom') });
    const side = h('aside', { class: 'graph-side hidden' });
    const search = h('input', { type: 'search', placeholder: tr('Find a note'), 'aria-label': tr('Find a note on the graph') });
    let withTags = localStorageGet('graph-tags') === '1';
    const tagsChip = h('button', { class: `chip${withTags ? ' accent' : ''}`, 'aria-pressed': String(withTags) }, '#', tr('Tags'));
    let data = { nodes: [], links: [] };
    const graph = createGraph(canvas, { onSelect: (node) => preview(node) });
    const empty = h('div', { class: 'graph-empty hidden' }, orb('md'), h('h3', {}, tr('Memory is empty for now')), h('p', {}, tr('The agent will start remembering on its own, and dreaming will gather what matters from chats. You can also add a note manually.')), h('button', { class: 'btn btn-primary', onclick: newNote }, icon('plus'), tr('New note')));

    async function load() {
      data = await get(`/v1/memory/graph?tags=${withTags}`);
      empty.classList.toggle('hidden', data.nodes.length > 0);
      graph.setData(data);
    }
    async function preview(node) {
      if (!node) { side.classList.add('hidden'); return; }
      side.classList.remove('hidden');
      const close = h('button', { class: 'icon-btn', 'aria-label': tr('Close'), onclick: () => { side.classList.add('hidden'); graph.select(null); } }, icon('x'));
      if (node.kind === 'tag') {
        const notes = data.links.filter((l) => l.target === node.id).map((l) => data.nodes.find((x) => x.id === l.source)).filter(Boolean);
        side.replaceChildren(h('div', { class: 'graph-side-head' }, h('h3', {}, node.label), close), h('div', { class: 'graph-side-list' }, notes.map((x) => h('button', { class: 'menu-item', onclick: () => { graph.select(x.id); preview(x); } }, h('span', { class: 'kind-dot', style: `background:${graphColor(x.kind)}` }), x.label))));
        return;
      }
      if (node.ghost) {
        side.replaceChildren(h('div', { class: 'graph-side-head' }, h('h3', {}, node.label), close), h('p', { class: 'muted' }, tr('This note is linked to, but doesn\'t exist yet.')), h('button', { class: 'btn btn-primary btn-sm', onclick: () => openNoteEditor({ title: node.label }, { onSaved: load, onOpenTitle: openTitle }) }, icon('plus'), tr('Create note')));
        return;
      }
      side.replaceChildren(h('div', { class: 'graph-side-head' }, h('h3', {}, node.label), close), h('p', { class: 'muted' }, tr('Loading...')));
      let n;
      try { n = await get(`/v1/memory/notes/${node.id}`); } catch (err) { fail(err); return; }
      const bodyEl = h('div', { class: 'prose graph-side-body', html: memoryMd(n.body || tr('_Empty_')) });
      bodyEl.addEventListener('click', (e) => {
        const link = e.target.closest('.wikilink');
        if (!link) return;
        e.preventDefault();
        const target = data.nodes.find((x) => !x.kind.startsWith('tag') && x.label.toLowerCase() === link.dataset.title.toLowerCase());
        if (target) { graph.select(target.id); preview(target); }
      });
      side.replaceChildren(
        h('div', { class: 'graph-side-head' }, h('h3', {}, n.title), close),
        h('div', { class: 'graph-side-meta' }, kindPill(n.kind), n.pinned ? h('span', { class: 'pill accent', title: tr('Always in the agent\'s context') }, icon('pin'), tr('pinned')) : null, (n.tags || []).map((t) => h('span', { class: 'pill tag' }, `#${t}`))),
        bodyEl,
        n.backlinks.length ? h('div', { class: 'note-backlinks' }, tr('Linked from: '), n.backlinks.map((b, i) => [i ? ', ' : '', h('a', { href: '#', onclick: (e) => { e.preventDefault(); graph.select(b.id); preview(data.nodes.find((x) => x.id === b.id)); } }, b.title)])) : null,
        h('div', { class: 'market-meta' }, tr('source: {0} · importance {1}', MEM_SOURCES[n.source] || n.source, n.importance)),
        h('button', { class: 'btn btn-sm', onclick: () => openNoteEditor(n, { onSaved: async () => { await load(); side.classList.add('hidden'); }, onOpenTitle: openTitle }) }, tr('Edit')),
      );
    }
    tagsChip.addEventListener('click', async () => {
      withTags = !withTags;
      localStorageSet('graph-tags', withTags ? '1' : '0');
      tagsChip.classList.toggle('accent', withTags);
      tagsChip.setAttribute('aria-pressed', String(withTags));
      await load();
    });
    search.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const q = search.value.trim().toLowerCase();
      const node = data.nodes.find((x) => x.label.toLowerCase() === q) || data.nodes.find((x) => x.label.toLowerCase().includes(q));
      if (node) { graph.select(node.id); preview(node); } else toast(tr('No such note found'));
    });
    const legend = h('div', { class: 'graph-legend' }, Object.entries(MEM_KINDS).map(([k, label]) => h('span', {}, h('span', { class: 'kind-dot', style: `background:${graphColor(k)}` }), label)));
    host.append(
      h('div', { class: 'graph-toolbar' },
        h('div', { class: 'settings-search graph-search' }, icon('search'), search),
        tagsChip,
        h('span', { class: 'spacer' }),
        h('button', { class: 'icon-btn', title: tr('Zoom out'), 'aria-label': tr('Zoom out'), onclick: () => graph.zoom(1 / 1.3) }, h('span', { class: 'zoom-sign' }, '−')),
        h('button', { class: 'icon-btn', title: tr('Show all'), 'aria-label': tr('Show all'), onclick: () => graph.fit() }, icon('layers')),
        h('button', { class: 'icon-btn', title: tr('Zoom in'), 'aria-label': tr('Zoom in'), onclick: () => graph.zoom(1.3) }, icon('plus'))),
      h('div', { class: 'graph-stage' }, canvas, side, empty),
      legend,
    );
    await load();
    return () => graph.destroy();
  }

  async function memoryNotes() {
    const search = h('input', { type: 'search', placeholder: tr('Search notes'), 'aria-label': tr('Search notes') });
    const kindFilter = h('select', { 'aria-label': tr('Note type') }, h('option', { value: '' }, tr('All types')), Object.entries(MEM_KINDS).map(([k, label]) => h('option', { value: k }, label)));
    const list = h('div', { class: 'rows' }, h('div', { class: 'empty' }, tr('Loading...')));
    let timer = 0;
    async function load() {
      const q = search.value.trim();
      const { notes } = await get(`/v1/memory/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`);
      const shown = notes.filter((n) => !kindFilter.value || n.kind === kindFilter.value);
      list.replaceChildren(...(shown.length ? shown.map((n) => h('button', { class: 'note-item', onclick: () => openNoteEditor(n, { onSaved: load, onOpenTitle: openTitle }) },
        h('span', { class: 'kind-dot', style: `background:${graphColor(n.kind)}` }),
        h('div', { class: 'row-text' },
          h('div', { class: 'row-title' }, n.title, n.pinned ? h('span', { class: 'note-pin', title: tr('Always in the agent\'s context') }, icon('pin')) : null),
          h('div', { class: 'row-desc' }, n.snippet || tr('Empty')),
          h('div', { class: 'note-item-meta' }, [MEM_KINDS[n.kind] || n.kind, MEM_SOURCES[n.source] || n.source, relTime(n.updated_at), ...(n.tags || []).map((t) => `#${t}`)].join(' · ')))))
        : [h('div', { class: 'empty' }, q || kindFilter.value ? tr('Nothing found.') : tr('No notes yet. The agent will save what matters on its own, and dreaming will gather from chats.'))]));
    }
    search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => load().catch(fail), 200); });
    kindFilter.addEventListener('change', () => load().catch(fail));
    host.append(h('div', { class: 'graph-toolbar' }, h('div', { class: 'settings-search graph-search' }, icon('search'), search), kindFilter), list);
    await load();
    return () => clearTimeout(timer);
  }

  async function memoryDreams() {
    const box = h('div', {});
    let timer = 0;
    let signature = '';
    async function load() {
      const d = await get('/v1/memory/dreams');
      const s = d.settings;
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (zone && s.tz !== zone) { s.tz = zone; put({ tz: zone }); }
      clearTimeout(timer);
      timer = setTimeout(() => load().catch(() => {}), d.running ? 1500 : 20000);
      const sig = JSON.stringify(d);
      if (sig === signature) return;
      signature = sig;
      const current = d.runs.find((r) => r.status === 'running');
      const run = h('button', { class: 'btn btn-primary', disabled: d.running, onclick: async () => {
        try { await post('/v1/memory/dreams'); toast(tr('The agent is falling asleep')); signature = ''; await load(); } catch (err) { fail(err); }
      } }, icon('moon'), d.running ? tr('Dreaming...') : tr('Run now'));
      const hour = h('select', { 'aria-label': tr('Run hour') }, Array.from({ length: 24 }, (_, i) => h('option', { value: String(i), selected: i === s.hour }, tr('at {0}:00', String(i).padStart(2, '0')))));
      hour.addEventListener('change', () => put({ hour: Number(hour.value) }));
      const threshold = h('select', { 'aria-label': tr('Importance threshold') }, Array.from({ length: 10 }, (_, i) => h('option', { value: String(i + 1), selected: i + 1 === s.min_importance }, tr('importance from {0}', i + 1))));
      threshold.addEventListener('change', () => put({ min_importance: Number(threshold.value) }));
      const phaseIdx = current ? DREAM_PHASES.findIndex(([k]) => k === current.phase) : -1;
      box.replaceChildren(...[
        h('div', { class: `dream-card${d.running ? ' running' : ''}` },
          createOrb(60, { animate: true, live: d.running, className: 'md' }),
          h('div', { class: 'dream-text' },
            h('h2', {}, tr('Dreaming')),
            h('p', {}, tr('At night the agent goes through new chats: in light sleep it gathers what you said and what it did, in REM it looks for what matters and connections to what it already knows, in deep sleep it consolidates into memory only what passed the importance threshold, and in the morning it leaves an entry in the diary.')),
            h('div', { class: 'dream-controls' },
              h('label', { class: 'switch-label' }, toggleSwitch(s.dreaming, { label: tr('Every night'), onChange: (v) => put({ dreaming: v }) }), tr('Every night')),
              hour, threshold, h('span', { class: 'spacer' }), run))),
        current ? h('div', { class: 'dream-phases' }, DREAM_PHASES.map(([k, label, desc], i) => h('div', { class: `dream-phase${i < phaseIdx ? ' done' : i === phaseIdx ? ' current' : ''}` },
          h('span', { class: 'dream-phase-dot' }, i < phaseIdx ? icon('check') : String(i + 1)), h('div', {}, h('div', { class: 'dream-phase-title' }, label), h('div', { class: 'row-desc' }, desc))))) : null,
        h('div', { class: 'section-head dream-diary-head' }, h('div', {}, h('h2', {}, tr('Dream diary')))),
        d.runs.filter((r) => r.status !== 'running').length
          ? h('div', { class: 'dream-runs' }, d.runs.filter((r) => r.status !== 'running').map(dreamEntry))
          : h('div', { class: 'rows' }, h('div', { class: 'empty' }, tr('The agent hasn\'t dreamed yet.'))),
      ].filter(Boolean));
    }
    const put = async (values) => { try { await api('/v1/memory/dreams/settings', { method: 'PUT', body: JSON.stringify(values) }); } catch (err) { fail(err); } };
    function dreamEntry(r) {
      const st = r.stats || {};
      const status = { done: ['', ''], empty: [tr('no dreams'), ''], failed: [tr('error'), 'danger'] }[r.status] || [r.status, ''];
      const numbers = [st.chats != null && tr('chats: {0}', st.chats), st.created && tr('new: {0}', st.created), st.updated && tr('expanded: {0}', st.updated), st.reinforced && tr('reinforced: {0}', st.reinforced), st.discarded && tr('released: {0}', st.discarded)].filter(Boolean).join(' · ');
      return h('article', { class: 'dream-entry' },
        h('div', { class: 'dream-entry-head' }, h('span', { class: 'dream-date' }, new Date(r.started_at).toLocaleString(locale, { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })), h('span', { class: 'market-meta' }, DREAM_TRIGGER[r.trigger] || r.trigger), status[0] ? h('span', { class: `pill ${status[1]}` }, status[0]) : null),
        numbers ? h('div', { class: 'market-meta' }, numbers) : null,
        r.status === 'empty' ? h('p', { class: 'muted' }, tr('There were no new conversations, slept without dreaming.')) : null,
        r.error ? h('p', { class: 'dream-error' }, r.error) : null,
        r.diary ? h('div', { class: 'prose dream-diary' }, h('p', {}, r.diary)) : null,
        (st.themes || []).length ? h('div', { class: 'market-tags' }, st.themes.map((t) => h('span', { class: 'pill tag-kind' }, t))) : null,
        (r.changes || []).length ? h('div', { class: 'dream-changes' }, r.changes.map((c) => h('button', { class: `dream-change ${c.action}`, onclick: () => openNoteEditor({ id: c.id }, { onSaved: () => show(), onOpenTitle: openTitle }).catch(() => toast(tr('Note already deleted'), true)) },
          { created: '+', updated: '~', reinforced: '↑' }[c.action] || '', ` ${c.title}`))) : null);
    }
    host.append(box);
    await load();
    return () => clearTimeout(timer);
  }

  page(shell, tr('Memory'), tr('What the agent remembers about you, projects, and devices. Notes are linked with [[Title]], and dreaming gathers what matters from new chats at night.'),
    h('button', { class: 'btn', onclick: newNote }, icon('plus'), tr('New note')),
    tabs, host);
  shell.panel.querySelector('.page-inner').classList.add('page-wide');
  viewCleanups.push(() => { if (cleanup) cleanup(); });
  await show();
}

const RISK_SHORT = { read: tr('read'), write: tr('changes'), execute: tr('run'), network: tr('network'), destructive: tr('irreversible') };
const extKind = (e) => [e.instructions ? tr('Skill') : null, e.tools.length ? tr('Tools: {0}', e.tools.length) : null].filter(Boolean);
const extIcon = (e) => (e.instructions && e.tools.length ? 'layers' : e.instructions ? 'book' : 'terminal');

async function settingsMarketplace(shell) {
  const grid = h('div', { class: 'market-grid' }, h('div', { class: 'empty' }, tr('Loading the catalog...')));
  const note = h('p', { class: 'market-note hidden' });
  const search = h('input', { type: 'search', placeholder: tr('Search by name and description'), 'aria-label': tr('Search the Marketplace') });
  const FILTERS = [['all', tr('All')], ['skills', tr('Skills')], ['tools', tr('Tools')], ['installed', tr('Installed')]];
  let filter = localStorageGet('market-filter') || 'all';
  let items = [];
  const filterBar = h('div', { class: 'segmented', role: 'tablist' });
  const renderFilters = () => filterBar.replaceChildren(...FILTERS.map(([key, label]) => h('button', {
    class: `seg${key === filter ? ' active' : ''}`, role: 'tab', 'aria-selected': String(key === filter),
    onclick: () => { filter = key; localStorageSet('market-filter', key); renderFilters(); render(); },
  }, label, key === 'installed' ? h('span', { class: 'seg-count' }, String(items.filter((i) => i.installed).length)) : null)));

  async function act(fn, done) {
    try { await fn(); if (done) toast(done); await load(); } catch (err) { fail(err); }
  }
  const install = (e) => act(() => post('/v1/extensions', { id: e.id }), e.installed ? tr('Updated: {0}', txt(e.name)) : tr('Installed: {0}', txt(e.name)));
  const remove = async (e) => {
    if (!await confirmDialog({ title: tr('Delete “{0}”?', txt(e.name)), text: e.installed.source === 'custom' ? tr('This is your package, its contents will be removed from Core.') : tr('The agent will stop using it. You can install it again anytime.'), action: tr('Delete'), danger: true })) return;
    closeLayer();
    act(() => del(`/v1/extensions/${e.id}`), tr('Removed'));
  };
  const setEnabled = (e, enabled) => api(`/v1/extensions/${e.id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }).then(() => { e.installed.enabled = enabled; });

  function actions(e, big = false) {
    const size = big ? '' : ' btn-sm';
    if (!e.installed) return h('button', { class: `btn btn-primary${size}`, onclick: (ev) => { ev.stopPropagation(); closeLayer(); install(e); } }, icon('plus'), tr('Install'));
    return h('div', { class: 'market-actions', onclick: (ev) => ev.stopPropagation() },
      e.update ? h('button', { class: `btn btn-primary${size}`, onclick: () => { closeLayer(); install(e); } }, tr('Update to {0}', e.version)) : null,
      h('label', { class: 'switch-label' }, toggleSwitch(e.installed.enabled, { label: tr('Enable “{0}”', txt(e.name)), onChange: (v) => setEnabled(e, v) }), tr('Enabled')),
      big ? h('button', { class: 'btn btn-danger btn-sm', onclick: () => remove(e) }, tr('Delete')) : null);
  }

  function details(e) {
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, txt(e.name)), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('div', { class: 'market-meta' }, [e.author, tr('version {0}', e.installed ? e.installed.version : e.version), e.installed?.source === 'custom' ? tr('your package') : null].filter(Boolean).join(' · ')),
      h('p', {}, txt(e.description) || txt(e.summary)),
      e.tools.length ? [h('div', { class: 'field-label' }, tr('Tools')), h('div', { class: 'market-tools' }, e.tools.map((t) => h('div', { class: 'market-tool' },
        h('div', { class: 'market-tool-head' }, h('code', {}, t.name), h('span', { class: 'pill' }, RISK_SHORT[t.risk] || t.risk)),
        h('div', { class: 'row-desc' }, t.description),
        h('pre', { class: 'market-argv' }, `$ ${t.argv.join(' ')}`))))] : null,
      e.instructions ? [h('div', { class: 'field-label' }, tr('Instructions for the agent')), h('div', { class: 'prose market-instructions', html: markdown(e.instructions) })] : null,
      h('div', { class: 'modal-actions' }, actions(e, true)),
    ).classList.add('modal-wide');
  }

  function card(e) {
    return h('div', { class: `market-card${e.installed ? ' installed' : ''}`, role: 'button', tabindex: '0', onclick: () => details(e), onkeydown: (ev) => { if (ev.key === 'Enter') details(e); } },
      h('div', { class: 'market-card-head' }, h('span', { class: 'market-icon' }, icon(extIcon(e))), h('div', { class: 'market-title' }, h('div', {}, txt(e.name)), h('div', { class: 'market-meta' }, [e.author, e.installed?.source === 'custom' ? tr('your package') : `v${e.version}`].filter(Boolean).join(' · ')))),
      h('p', { class: 'market-summary' }, txt(e.summary)),
      h('div', { class: 'market-tags' }, extKind(e).map((k) => h('span', { class: 'pill tag-kind' }, k))),
      h('div', { class: 'market-foot' }, actions(e)));
  }

  function render() {
    const q = search.value.trim().toLowerCase();
    const shown = items.filter((e) => ({ all: true, skills: !!e.instructions, tools: e.tools.length > 0, installed: !!e.installed }[filter]))
      .filter((e) => !q || [txt(e.name), txt(e.summary), txt(e.description), e.id, ...(e.tags || []), ...e.tools.map((t) => t.name)].join(' ').toLowerCase().includes(q));
    grid.replaceChildren(...(shown.length ? shown.map(card) : [h('div', { class: 'empty' }, filter === 'installed' && !q ? tr('Nothing installed yet.') : tr('Nothing found.'))]));
  }

  async function load() {
    const data = await get('/v1/marketplace');
    items = data.items;
    note.textContent = data.error ? tr('The mensarium.com catalog is currently unavailable, showing packages bundled with this version of Mensarium.') : '';
    note.classList.toggle('hidden', !data.error);
    renderFilters();
    render();
  }

  function addCustom() {
    const ta = h('textarea', { class: 'market-yaml', rows: 14, spellcheck: 'false', 'aria-label': tr('Package manifest'),
      placeholder: tr('id: my-skill\nname: {en: My skill, ru: Мой навык}\nversion: 1.0.0\nsummary: Short description of what it does\ninstructions: |\n  # How to work\n  1. ...') });
    const save = h('button', { class: 'btn btn-primary' }, tr('Install'));
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        await api('/v1/extensions/custom', { method: 'POST', body: ta.value, headers: { 'Content-Type': 'text/plain' } });
        closeLayer();
        toast(tr('Package installed'));
        await load();
      } catch (err) { fail(err); } finally { save.disabled = false; }
    });
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, tr('Custom skill or tool')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('p', {}, tr('Paste a YAML manifest. A skill is an instructions field with instructions for the agent, a tool is a tools list with a command in argv; you can include both. Same format as catalog packages.')),
      ta,
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
    ).classList.add('modal-wide');
    ta.focus();
  }

  search.addEventListener('input', render);
  page(shell, tr('Marketplace'), tr('Skills tell the agent how to do the work, tools give it ready-made commands. The agent sees what\'s installed starting from the next step; commands still go through approval and the device\'s allowed program lists.'),
    h('button', { class: 'btn', onclick: addCustom }, icon('plus'), tr('Add your own')),
    h('div', { class: 'market-bar' }, filterBar, h('div', { class: 'settings-search market-search' }, icon('search'), search)),
    note,
    grid,
  );
  await load();
}

async function settingsProfiles(shell) {
  const profiles = await get('/v1/agent-profiles');
  page(shell, tr('Profiles'), tr('A profile sets the agent\'s tools, its limits, and the actions that wait for approval in ask-before-acting mode.'), null,
    profiles.map((p) => section(tr('{0}, version {1}', p.name, p.version), p.id, h('div', { class: 'rows' },
      row(tr('Model'), tr('Temperature {0}', p.llm.temperature), p.llm.model, true),
      row(tr('Tools'), null, null),
      h('div', { class: 'row-extra' }, p.allowed_tools.map((t) => h('span', { class: 'pill tag' }, t))),
      row(tr('Require approval'), tr('In “Ask before acting” mode, you approve each such action separately.'), h('span', {}, p.approval.required_risks.map((r) => (RISK[r] || [r])[0]).join(', '))),
      row(tr('Limits'), null, tr('{0} steps, {1} actions, {2} min', p.limits.max_steps, p.limits.max_tool_calls, Math.round(p.limits.max_wall_time_s / 60))),
    ))),
  );
}

async function settingsAudit(shell) {
  const LABELS = {
    'task.created': tr('Task created'), 'task.succeeded': tr('Task completed'), 'task.stopped': tr('Task stopped'),
    'tool.execute': tr('Sent to device'), 'tool.result': tr('Result from device'), 'tool.denied': tr('Blocked by policy'),
    'approval.requested': tr('Approval requested'), 'approval.approved': tr('Approved'), 'approval.rejected': tr('Rejected'),
    'target.paired': tr('Device paired'), 'target.revoked': tr('Device access revoked'), 'pairing.code_created': tr('Pairing code created'),
    'core.started': tr('Core started'), 'task.cancel': tr('Task canceled'), 'task.pause': tr('Task paused'), 'task.resume': tr('Task resumed'),
    'task.deleted': tr('Chat deleted'), 'task.mode': tr('Access mode changed'), 'profile.imported': tr('Profile imported'),
    'task.model': tr('Chat model changed'), 'llm.default_model': tr('Default model changed'),
    'target.tool': tr('Device tool toggled'),
    'extension.installed': tr('Package installed'), 'extension.toggled': tr('Package enabled or disabled'), 'extension.removed': tr('Package removed'),
    'tool.core': tr('Core tool'),
    'memory.note_created': tr('Note created'), 'memory.note_updated': tr('Note edited'), 'memory.note_deleted': tr('Note deleted'),
    'target.update': tr('Device agent update'), 'core.update': tr('Core update'),
    'memory.dreamed': tr('Dream'), 'memory.dream_started': tr('Dream started'), 'memory.dream_settings': tr('Dreaming settings'),
  };
  const ACTORS = { core: 'Core', target: tr('device'), user: tr('you') };
  const describe = (p) => {
    const title = p.task_id ? state.tasks.find((t) => t.id === p.task_id) : null;
    return [
      p.display || p.tool,
      p.name,
      p.title,
      p.id && !p.task_id && p.id,
      p.created != null && tr('new notes: {0}', p.created),
      p.source === 'custom' && tr('custom package'),
      p.status && (EXEC_STATUS[p.status] || statusOf(p.status)[0]),
      p.exit_code != null && tr('code {0}', p.exit_code),
      p.mode && (MODES[p.mode]?.label || p.mode),
      p.model,
      p.enabled != null && `${p.tool}: ${p.enabled ? tr('enabled') : tr('disabled')}`,
      p.reason && policyText(reasonText(p.reason)),
      p.version && tr('version {0}', p.version),
      p.to && `${p.from || '?'} → ${p.to}`,
      p.task_id && (title ? `«${taskTitle(title)}»` : tr('deleted chat')),
    ].filter(Boolean).join(' · ');
  };
  const list = h('div', {});
  const load = async () => {
    const events = await get('/v1/audit?limit=200');
    list.replaceChildren(events.length ? h('div', { class: 'rows' }, events.map((e) => h('div', { class: 'audit-item' },
      h('div', { class: 'audit-time' }, new Date(e.created_at).toLocaleString(locale), h('div', { class: 'mono', title: e.hash }, e.hash.slice(7, 17))),
      h('div', {}, h('div', { class: 'audit-type' }, LABELS[e.event_type] || e.event_type, h('span', { class: 'audit-actor' }, ` · ${ACTORS[e.actor] || e.actor}`)),
        h('div', { class: 'audit-payload', title: JSON.stringify(e.payload) }, describe(e.payload)))))) : h('div', { class: 'rows' }, h('div', { class: 'empty' }, tr('No events yet.'))));
  };
  page(shell, tr('Activity log'), tr('Each event is linked to the previous one\'s hash, so a record can\'t be changed or deleted unnoticed.'),
    h('button', { class: 'btn', onclick: () => load().catch(fail) }, icon('refresh'), tr('Update')),
    list,
  );
  await load();
}

// ---------- router ----------

function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

async function route() {
  viewCleanups.forEach((fn) => { try { fn(); } catch { /* noop */ } });
  viewCleanups = [];
  closeLayer();
  const hash = location.hash || '#/';
  try {
    let m;
    if ((m = hash.match(/^#\/chat\/([^/]+)$/)) || (m = hash.match(/^#\/tasks\/([^/]+)$/))) await viewChat(m[1]);
    else if ((m = hash.match(/^#\/settings\/?(\w*)$/))) await viewSettings(m[1] || 'overview');
    else await viewNewChat();
  } catch (err) { fail(err); }
}

document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === ',') { e.preventDefault(); go('#/settings/overview'); }
  if (e.key !== 'Escape') return;
  const navOpen = document.querySelector('.shell.nav-open');
  if ($layer.firstChild || navOpen) {
    closeLayer();
    navOpen?.classList.remove('nav-open');
    e.stopImmediatePropagation();
  }
});

async function boot() {
  try {
    state.system = await get('/v1/system');
    await refreshData();
  } catch (err) {
    if (err instanceof AuthError) { showLogin(); return; }
    toast(err.message, true);
  }
  state.shell = null;
  window.removeEventListener('hashchange', route);
  window.addEventListener('hashchange', route);
  route();
}

boot();
