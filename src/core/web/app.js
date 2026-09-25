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
  plug: '<path d="M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0z"/><path d="M12 16v5"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.7 5.7 3.7 9s-1.2 6.3-3.7 9c-2.5-2.7-3.7-5.7-3.7-9S9.5 5.7 12 3z"/>',
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
// Code spans and links are stashed first so emphasis rules never reach inside them.
function inlineMd(s) {
  const stash = [];
  const keep = (html) => `\u0000${stash.push(html) - 1}\u0000`;
  return esc(s)
    .replace(/`([^`\n]+)`/g, (_, c) => keep(`<code>${c}</code>`))
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => keep(`<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`))
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^\w*])\*([^*\s][^*\n]*?)\*(?![\w*])/g, '$1<em>$2</em>')
    .replace(/(^|\W)_([^_\s][^_\n]*?)_(?!\w)/g, '$1<em>$2</em>')
    .replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
    .replace(/\u0000(\d+)\u0000/g, (_, i) => stash[i] || '');
}

const TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
const tableCells = (row) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));

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
    if (line.includes('|') && (lines[i + 1] || '').includes('|') && TABLE_SEP.test(lines[i + 1])) {
      flushPara(); flushList();
      const align = tableCells(lines[i + 1]).map((c) => (c.endsWith(':') ? (c.startsWith(':') ? 'center' : 'right') : ''));
      const row = (tag, r) => tableCells(r).map((c, j) => `<${tag}${align[j] ? ` style="text-align:${align[j]}"` : ''}>${inlineMd(c)}</${tag}>`).join('');
      const body = [];
      for (i += 2; i < lines.length && lines[i].includes('|'); i++) body.push(`<tr>${row('td', lines[i])}</tr>`);
      i--;
      out.push(`<div class="table-wrap"><table><thead><tr>${row('th', line)}</tr></thead><tbody>${body.join('')}</tbody></table></div>`);
      continue;
    }
    if (/^\s*>/.test(line)) {
      flushPara(); flushList();
      const quote = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) quote.push(lines[i].replace(/^\s*>\s?/, ''));
      i--;
      out.push(`<blockquote>${markdown(quote.join('\n'))}</blockquote>`);
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flushPara(); flushList();
      out.push('<hr>');
      continue;
    }
    const bullet = line.match(/^(\s*)[-*]\s+(.*)$/);
    const numbered = line.match(/^(\s*)(\d+)[.)]\s+(.*)$/);
    const heading = line.match(/^\s*(#{1,6})\s+(.*)$/);
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
      const tag = heading[1].length <= 2 ? 'h2' : 'h3';
      out.push(`<${tag}>${inlineMd(heading[2])}</${tag}>`);
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
const TOOL_ICON = { 'files.list': 'folder', 'files.read': 'file', 'files.search': 'search', 'files.stat': 'file', 'files.find': 'search', 'files.write': 'file', 'files.edit': 'file', 'files.mkdir': 'folder', 'files.move': 'folder', 'files.copy': 'folder', 'files.delete': 'trash', 'git.status': 'git', 'git.diff': 'git', 'system.info': 'cpu', 'process.list': 'cpu', 'process.kill': 'ban', 'net.ports': 'link', 'net.http': 'globe', 'shell.exec': 'terminal', 'shell.bash': 'terminal', 'skills.read': 'book', 'memory.search': 'graph', 'memory.read': 'graph', 'memory.save': 'graph', 'web.search': 'globe', 'web.fetch': 'globe' };
// Plugin texts are either plain strings or {en, ru} maps.
const txt = (v) => (typeof v === 'string' ? v : (v?.[lang] || v?.en || ''));
// Plain text with bare https links turned into anchors; everything else stays text.
const linkify = (text) => String(text).split(/(https?:\/\/[^\s]+)/g).map((part, i) => (i % 2 ? h('a', { href: part, target: '_blank', rel: 'noopener' }, part) : part));
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
      onclick: () => { selected = t; localStorageSet('target', t.id); renderChip(); modeCtl.refresh(); hint.textContent = hintText(); banner.replaceChildren(outdatedBanner(selected) || ''); closeLayer(); },
    }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), t.name, h('span', { class: 'popover-sub' }, isLocal(t) ? tr('Core server') : t.status === 'online' ? t.platform.split('-')[0] : tr('offline'))));
    items.push(h('div', { class: 'menu-sep' }), h('button', { class: 'menu-item', onclick: () => { closeLayer(); openPairing(); } }, icon('link'), tr('Pair a new device')));
    openPopover(targetChip, items);
  }
  renderChip();

  const hint = h('p', { class: 'welcome-hint' });
  if (!state.system) { try { state.system = await get('/v1/system'); } catch { /* shown without version info */ } }
  const banner = h('div', { class: 'welcome-banner' }, outdatedBanner(selected) || '');
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
      banner,
    ]
    : h('div', { class: 'welcome-empty' },
      h('div', { class: 'welcome-hero' }, orb('lg'), h('h1', {}, tr('Connect a device'))),
      h('p', {}, tr('The agent works on your machines through Mensarium Target. Pairing takes a minute.')),
      h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), tr('Pair a device')));

  shell.panel.replaceChildren(topbar(shell, [], null, { newChat: false }), h('div', { class: 'welcome' }, content));
  if (devices().length) c.textarea.focus();
}

// A device whose agent is older than Core and misses base tools: offer the update right in the chat.
function outdatedBanner(t) {
  const s = state.system;
  const caps = t?.capabilities || {};
  if (!t || !s || isLocal(t) || !t.agent_version || t.agent_version === s.version || !(caps.missing_tools || []).length) return null;
  const pending = state.updates.get(t.id);
  const text = h('span', {}, tr('The agent on “{0}” is version {1}, Core is {2}: some tools are unavailable until it updates.', t.name, t.agent_version, s.version));
  if (pending) return h('div', { class: 'note-banner' }, icon('refresh'), h('span', {}, tr('“{0}” is updating to {1}…', t.name, pending.version)));
  let action = null;
  if (caps.remote_update && t.status === 'online') {
    action = h('button', { class: 'btn btn-primary btn-sm', onclick: async (e) => {
      e.currentTarget.disabled = true;
      try {
        const r = await post(`/v1/targets/${t.id}/update`);
        state.updates.set(t.id, { version: r.version, at: Date.now() });
        toast(tr('“{0}” is updating', t.name));
        e.currentTarget.closest('.note-banner')?.replaceWith(outdatedBanner(t));
      } catch (err) { fail(err); e.currentTarget.disabled = false; }
    } }, icon('refresh'), tr('Update the agent'));
  } else if (!caps.remote_update) {
    action = h('code', {}, 'mensarium update');
  }
  return h('div', { class: 'note-banner' }, icon('alert'), text, action);
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

  if (!state.system) { try { state.system = await get('/v1/system'); } catch { /* shown without version info */ } }
  const banner = outdatedBanner(target());
  shell.panel.replaceChildren(
    topbar(shell,
      [h('span', { class: 'crumb-device' }, icon('laptop'), task.target_name || tr('device'), h('span', { class: 'sep' }, '/')), h('span', { class: 'current', title: task.input }, taskTitle(task))],
      [btnDelete]),
    thread,
    h('div', { class: 'thread-banner' }, banner || ''),
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
      case 'files.stat': return tr('Checking {0}', base(a.path));
      case 'files.find': return tr('Finding {0}', clip(a.pattern, 40));
      case 'files.write': return tr('Writing {0}', base(a.path));
      case 'files.edit': return tr('Editing {0}', base(a.path));
      case 'files.mkdir': return tr('Creating folder {0}', base(a.path));
      case 'files.move': return tr('Moving {0}', base(a.source));
      case 'files.copy': return tr('Copying {0}', base(a.source));
      case 'files.delete': return tr('Deleting {0}', base(a.path));
      case 'git.status': return tr('Checking git status');
      case 'git.diff': return tr('Reading the git diff');
      case 'system.info': return tr('Checking the system');
      case 'process.list': return tr('Listing processes');
      case 'process.kill': return tr('Stopping process {0}', a.pid);
      case 'net.ports': return tr('Checking listening ports');
      case 'net.http': return tr('Requesting {0}', (() => { try { return new URL(a.url).host; } catch { return clip(a.url, 40); } })());
      case 'shell.bash': return tr('Running {0}', clip(a.script.split('\n')[0], 56));
      case 'skills.read': return tr('Loading skill {0}', a.path ? `${a.name} ${a.path}` : a.name);
      case 'memory.search': return tr('Searching memory for “{0}”', clip(a.query, 40));
      case 'memory.read': return tr('Reading note {0}', a.title);
      case 'memory.save': return tr('Remembering {0}', a.title);
      case 'web.search': return tr('Searching the web for “{0}”', clip(a.query, 40));
      case 'web.fetch': return tr('Reading {0}', (() => { try { return new URL(a.url).host; } catch { return clip(a.url, 40); } })());
      default:
        if (tool.startsWith('mcp.')) { const [, server, name] = tool.split('.'); return tr('Calling {0}: {1}', server, name); }
        return a.command ? tr('Running {0}', clip(a.command, 56)) : tool;
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
  ['providers', 'robot', tr('Providers')],
  ['devices', 'laptop', tr('Devices')],
  ['memory', 'graph', tr('Memory')],
  ['skills', 'book', tr('Skills')],
  ['plugins', 'package', tr('Plugins')],
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
  const views = { overview: settingsOverview, providers: settingsProviders, model: settingsProviders, devices: settingsDevices, memory: settingsMemory, skills: settingsSkills, plugins: settingsPlugins, marketplace: settingsPlugins, profiles: settingsProfiles, audit: settingsAudit };
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

async function settingsProviders(shell) {
  const [data, sys] = await Promise.all([get('/v1/providers'), get('/v1/system')]);
  state.system = sys;
  const health = sys.provider.health || {};
  const active = data.providers.find((x) => x.active) || data.providers[0];
  const kinds = Object.fromEntries(data.kinds.map((k) => [k.kind, k]));
  const models = h('div', { class: 'rows' }, h('div', { class: 'empty' }, tr('Loading the list...')));

  const reload = () => settingsProviders(shell).catch(fail);
  const activate = async (x) => {
    try { await post(`/v1/providers/${x.id}/activate`); state.models = null; toast(tr('Active provider: {0}', x.title)); reload(); } catch (err) { fail(err); }
  };
  const remove = async (x) => {
    if (!await confirmDialog({ title: tr('Remove “{0}”?', x.title), text: tr('Its settings and saved key are deleted from Core.'), action: tr('Remove'), danger: true })) return;
    try { await del(`/v1/providers/${x.id}`); toast(tr('Removed')); reload(); } catch (err) { fail(err); }
  };

  function editor(x) {
    const adding = !x;
    const kindSel = h('select', { 'aria-label': tr('Type') }, data.kinds.map((k) => h('option', { value: k.kind, selected: x ? k.kind === x.kind : k.kind === 'ollama_local' }, k.title)));
    const taken = new Set(data.providers.map((y) => y.id));
    const freeId = (kind) => { let id = kind; for (let i = 2; taken.has(id); i++) id = `${kind}-${i}`; return id; };
    const id = h('input', { type: 'text', value: x ? x.id : freeId(kindSel.value), disabled: !adding, 'aria-label': tr('Name in the config') });
    const base = h('input', { type: 'text', value: x ? x.base_url : kinds[kindSel.value].base_url, 'aria-label': tr('API address') });
    const key = h('input', { type: 'password', autocomplete: 'off', placeholder: x?.has_key ? tr('Saved. Type to replace') : '', 'aria-label': tr('API key') });
    const listId = `models-${Math.random().toString(36).slice(2)}`;
    const modelList = h('datalist', { id: listId });
    const model = h('input', { type: 'text', value: x ? x.default_model : kinds[kindSel.value].default_model, list: listId, 'aria-label': tr('Default model') });
    const timeout = h('input', { type: 'number', value: x ? x.timeout_s : 90, min: 5, max: 600, 'aria-label': tr('Timeout, s') });
    const retries = h('input', { type: 'number', value: x ? x.max_retries : 2, min: 0, max: 5, 'aria-label': tr('Retries') });
    let makeActive = adding && !data.providers.length;
    const activeSwitch = adding ? h('label', { class: 'switch-label' }, toggleSwitch(makeActive, { label: tr('Make it active'), onChange: async (v) => { makeActive = v; } }), tr('Make it active')) : null;
    const keyHint = h('div', { class: 'row-desc' });
    const statusDot = h('span', { class: 'dot' });
    const statusText = h('span', {}, tr('Check the connection to load the models.'));
    const status = h('div', { class: 'plugin-status' }, statusDot, statusText);
    const setStatus = (kind, text) => { status.className = `plugin-status ${kind}`; statusDot.className = `dot ${{ ok: 'ok', error: 'danger', busy: 'accent live' }[kind] || ''}`; statusText.textContent = text; };
    let touchedBase = !!x;
    base.addEventListener('input', () => { touchedBase = true; });
    const syncKind = () => {
      const k = kinds[kindSel.value];
      if (!touchedBase) base.value = k.base_url;
      if (adding) { id.value = freeId(k.kind); if (!model.value || !x) model.value = k.default_model; }
      keyHint.replaceChildren(...(k.needs_key ? [tr('Required. '), k.key_url ? linkify(k.key_url) : ''] : [tr('Only if the server asks for one.')]));
    };
    kindSel.addEventListener('change', syncKind);
    syncKind();
    const check = h('button', { class: 'btn btn-sm', onclick: async (e) => {
      e.preventDefault();
      check.disabled = true;
      setStatus('busy', tr('Connecting...'));
      try {
        const r = await post('/v1/providers/test', { kind: kindSel.value, base_url: base.value.trim(), api_key: key.value || null, id: x?.id || null });
        if (r.ok) {
          modelList.replaceChildren(...r.models.map((m) => h('option', { value: m })));
          if (r.models.length && !r.models.includes(model.value)) model.value = r.models.includes(kinds[kindSel.value].default_model) ? kinds[kindSel.value].default_model : r.models[0];
          setStatus('ok', tr('Available, {0} models', r.models.length));
        } else {
          setStatus('error', tr('Error: {0}', r.error));
        }
      } catch (err) { fail(err); } finally { check.disabled = false; }
    } }, icon('refresh'), tr('Check connection'));
    status.append(h('span', { class: 'spacer' }), check);
    const save = h('button', { class: 'btn btn-primary' }, tr('Save'));
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        await api(`/v1/providers/${encodeURIComponent(id.value.trim())}`, { method: 'PUT', body: JSON.stringify({
          kind: kindSel.value, base_url: base.value.trim(), default_model: model.value.trim(), api_key: key.value || null,
          timeout_s: Number(timeout.value) || 90, max_retries: Number(retries.value) || 0,
        }) });
        if (makeActive) await post(`/v1/providers/${encodeURIComponent(id.value.trim())}/activate`);
        state.models = null;
        closeLayer();
        toast(tr('Saved'));
        reload();
      } catch (err) { fail(err); } finally { save.disabled = false; }
    });
    const field = (label, control, hint) => h('label', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, h('span', {}, label)), control, hint || null);
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, adding ? tr('Add a provider') : x.title), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('div', { class: 'plugin-form' },
        h('div', { class: 'plugin-grid' }, field(tr('Type'), kindSel), field(tr('Name in the config'), id)),
        field(tr('API address'), base),
        field(tr('API key'), key, keyHint),
        status,
        field(tr('Default model'), h('div', {}, model, modelList)),
        h('div', { class: 'plugin-grid' }, field(tr('Timeout, s'), timeout), field(tr('Retries'), retries)),
        activeSwitch),
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
    ).classList.add('modal-wide');
  }

  const rows = h('div', { class: 'rows' }, data.providers.map((x) => h('div', { class: 'row' },
    h('div', { class: 'row-text' },
      h('div', { class: 'row-title' }, x.title, x.id !== x.kind ? h('code', { class: 'provider-id' }, x.id) : null, x.active ? h('span', { class: 'pill accent' }, tr('active')) : null),
      h('div', { class: 'row-desc' }, [x.base_url, x.default_model, x.needs_key || x.has_key ? (x.has_key ? tr('key saved') : tr('no key')) : null].filter(Boolean).join(' · '))),
    h('div', { class: 'row-value' },
      x.active ? null : h('button', { class: 'btn btn-sm', onclick: () => activate(x) }, tr('Make active')),
      h('button', { class: 'icon-btn', title: tr('Edit'), 'aria-label': tr('Edit'), onclick: () => editor(x) }, icon('sliders')),
      x.active ? null : h('button', { class: 'icon-btn', title: tr('Remove'), 'aria-label': tr('Remove'), onclick: () => remove(x) }, icon('trash'))))));

  page(shell, tr('Providers'), tr('Where the agent thinks: the LLM provider and its models. Keys are stored only on the Core server; switching the active provider applies from the next step of running tasks.'),
    h('button', { class: 'btn btn-primary', onclick: () => editor(null) }, icon('plus'), tr('Add a provider')),
    h('div', { class: 'hero provider-hero' }, h('span', { class: 'market-icon' }, icon('robot')), h('div', { class: 'hero-text' },
      h('h2', {}, active ? active.title : '—'),
      h('p', {}, [sys.provider.base_url, sys.provider.model].join(' · '))),
      h('span', { class: 'status' }, h('span', { class: `dot ${health.ok ? 'ok' : 'danger'}` }), health.ok ? tr('Available') : tr('Unavailable'))),
    health.ok ? null : h('p', { class: 'market-note' }, health.detail || ''),
    section(tr('Default model'), tr('For new chats with the active provider. In a chat the model is changed with the robot button in the input.'), models),
    section(tr('Providers'), null, rows),
  );
  const render = (ids) => {
    models.replaceChildren(ids.length
      ? h('div', { class: 'row-extra model-grid' }, ids.map((mid) => h('button', {
        class: `pill tag model-pill${mid === state.system.provider.model ? ' accent' : ''}`,
        'aria-pressed': String(mid === state.system.provider.model),
        onclick: async () => {
          if (mid === state.system.provider.model) return;
          try {
            await api('/v1/system/model', { method: 'PUT', body: JSON.stringify({ model: mid }) });
            state.system.provider.model = mid;
            toast(tr('Default model: {0}', mid));
            render(ids);
          } catch (err) { fail(err); }
        },
      }, mid)))
      : h('div', { class: 'empty' }, tr('The provider did not return any models.')));
  };
  try {
    state.models = null;
    render((await loadModels()).map((m) => m.id));
  } catch (err) {
    models.replaceChildren(h('div', { class: 'empty' }, err.message));
  }
}

const TOOL_INFO = {
  'files.list': [tr('List files'), tr('Looks at folder contents.')],
  'files.read': [tr('Read files'), tr('Opens text files, secrets are stripped out.')],
  'files.search': [tr('Search files'), tr('Searches for text in the project.')],
  'files.stat': [tr('File details'), tr('Size, permissions and modification time.')],
  'files.find': [tr('Find files'), tr('Finds files by name pattern.')],
  'files.write': [tr('Write files'), tr('Creates or overwrites a file, with approval.')],
  'files.edit': [tr('Edit files'), tr('Replaces an exact fragment in a file, with approval.')],
  'files.mkdir': [tr('Create folders'), tr('Creates a folder, with approval.')],
  'files.move': [tr('Move files'), tr('Moves or renames, with approval.')],
  'files.copy': [tr('Copy files'), tr('Copies a file or folder, with approval.')],
  'files.delete': [tr('Delete files'), tr('Deletes one file or an empty folder, always confirmed.')],
  'git.status': [tr('Git status'), tr('Branch and changed files.')],
  'git.diff': [tr('Git diff'), tr('Shows the diff.')],
  'system.info': [tr('System info'), tr('OS, CPU, memory, disk and uptime.')],
  'process.list': [tr('Processes'), tr('Lists running processes.')],
  'process.kill': [tr('Stop processes'), tr('Stops a process of this user, always confirmed.')],
  'net.ports': [tr('Listening ports'), tr('Ports and the processes behind them.')],
  'net.http': [tr('HTTP requests'), tr('Requests from the device, including localhost, with approval.')],
  'shell.exec': [tr('Run commands'), tr('Runs one allowed program without a shell.')],
  'shell.bash': [tr('Bash scripts'), tr('Runs any bash script; each one is approved by you. Can be turned off on the device.')],
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
  const pluginTools = Object.fromEntries(await Promise.all(devices().map(async (t) => [t.id, await get(`/v1/targets/${t.id}/plugin-tools`).catch(() => [])])));
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
      (pluginTools[t.id] || []).length ? [
        h('div', { class: 'device-sub' }, tr('Plugin tools'), h('span', {}, tr('Commands need “Run commands” and the program in the allowed list; MCP tools run on the device’s MCP servers.'))),
        h('div', { class: 'tool-rows' }, pluginTools[t.id].map((tool) => h('div', { class: 'tool-row' },
          icon(tool.program ? 'terminal' : 'plug'),
          h('div', { class: 'row-text' }, h('div', { class: 'tool-row-title' }, tool.name, h('code', {}, txt(tool.plugin))), h('div', { class: 'row-desc' }, tool.description)),
          !tool.program || programs.includes('*') || programs.includes(tool.program) ? null : h('span', { class: 'pill warn', title: tr('The program isn\'t in the device\'s allowed list') }, tr('no {0}', tool.program)),
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
const RISK_CHOICES = [
  ['read', tr('Read: no approval')],
  ['network', tr('Network: with approval')],
  ['execute', tr('Run: with approval')],
  ['write', tr('Changes: with approval')],
  ['destructive', tr('Irreversible: always confirm')],
];
const pluginKinds = (p) => [
  p.provides.device_tools.length ? tr('Device tools: {0}', p.provides.device_tools.length) : null,
  p.provides.core_tools.length ? tr('In Core: {0}', p.provides.core_tools.join(', ')) : null,
  p.provides.mcp ? 'MCP' : null,
].filter(Boolean);
const pluginIcon = (p) => (p.provides.mcp ? 'plug' : p.provides.core_tools.length ? 'globe' : 'terminal');
const settingTitle = (key, spec) => txt(spec.title) || key;

const OS_LABELS = { darwin: 'macOS', linux: 'Linux', win32: 'Windows' };

async function settingsSkills(shell) {
  const list = h('div', {}, h('div', { class: 'empty' }, tr('Loading...')));
  const search = h('input', { type: 'search', placeholder: tr('Search skills'), 'aria-label': tr('Search skills') });
  let items = [];
  let folder = '';

  async function act(fn, done) {
    try { const r = await fn(); if (done) toast(done); await load(); return r; } catch (err) { fail(err); return null; }
  }
  const setEnabled = (s, enabled) => api(`/v1/skills/${s.name}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }).then((v) => { Object.assign(s, v); render(); });
  const remove = async (s) => {
    if (!await confirmDialog({ title: tr('Delete “{0}”?', s.name), text: s.shadows ? tr('Your copy is deleted and the built-in skill is used again.') : tr('The skill folder is removed from Core.'), action: tr('Delete'), danger: true })) return;
    closeLayer();
    act(() => del(`/v1/skills/${s.name}`), tr('Removed'));
  };

  const pills = (s) => [
    s.shadows ? h('span', { class: 'pill accent' }, tr('replaces the built-in')) : null,
    s.always ? h('span', { class: 'pill' }, tr('always')) : null,
    ...s.os.map((o) => h('span', { class: 'pill' }, OS_LABELS[o] || o)),
    s.requires_tools.length ? h('span', { class: 'pill', title: s.requires_tools.join(', ') }, tp('needs {0} tool|needs {0} tools', s.requires_tools.length)) : null,
  ].filter(Boolean);

  function skillRow(s) {
    return h('div', { class: 'row skill-row' },
      h('span', { class: 'market-icon' }, s.emoji || icon('book')),
      h('div', { class: 'row-text' },
        h('div', { class: 'row-title' }, h('code', {}, s.name), ...pills(s)),
        h('div', { class: 'row-desc' }, s.description)),
      h('div', { class: 'row-value' },
        toggleSwitch(s.enabled, { label: tr('Enable “{0}”', s.name), onChange: (v) => setEnabled(s, v) }),
        h('button', { class: 'btn btn-sm', onclick: () => editor(s.name) }, s.source === 'user' ? tr('Edit') : tr('View'))));
  }

  async function editor(name) {
    let s = null;
    if (name) {
      try { s = await get(`/v1/skills/${name}`); } catch (err) { fail(err); return; }
    }
    const isUser = s?.source === 'user';
    const field = (label, control, hint) => h('label', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, h('span', {}, label)), control, hint ? h('div', { class: 'row-desc' }, hint) : null);
    const nameInput = h('input', { type: 'text', value: s?.name || '', placeholder: 'my-skill', disabled: !!s, 'aria-label': tr('Name'), maxlength: 64 });
    const description = h('input', { type: 'text', value: s?.description || '', placeholder: tr('One line: what it does and when to use it'), 'aria-label': tr('Description'), maxlength: 1024 });
    const body = h('textarea', { class: 'market-yaml skill-body', rows: 18, spellcheck: 'false', 'aria-label': tr('Instructions'), placeholder: tr('# How to work\n\n1. Read the relevant files with files.read.\n2. ...\n\nReport format: ...') });
    body.value = s?.body || '';
    const homepage = h('input', { type: 'text', value: s?.homepage || '', placeholder: 'https://', 'aria-label': tr('Website') });
    let alwaysValue = !!s?.always;
    const always = toggleSwitch(alwaysValue, { label: tr('Offer it always'), onChange: async (v) => { alwaysValue = v; } });
    const osBoxes = Object.entries(OS_LABELS).map(([key, label]) => {
      const box = h('input', { type: 'checkbox', value: key, checked: (s?.os || []).includes(key) });
      return h('label', { class: 'check-label' }, box, label);
    });
    const requires = h('input', { type: 'text', value: (s?.requires_tools || []).join(', '), placeholder: 'git.diff, shell.exec, mcp.github.*', 'aria-label': tr('Required tools') });
    const save = h('button', { class: 'btn btn-primary' }, s && !isUser ? tr('Save as my copy') : tr('Save'));
    save.addEventListener('click', async () => {
      save.disabled = true;
      const payload = {
        name: s ? undefined : nameInput.value.trim().toLowerCase(),
        description: description.value.trim(),
        body: body.value,
        homepage: homepage.value.trim() || null,
        always: alwaysValue,
        os: osBoxes.map((l) => l.firstChild).filter((b) => b.checked).map((b) => b.value),
        requires_tools: requires.value.split(',').map((x) => x.trim()).filter(Boolean),
      };
      try {
        if (s) await api(`/v1/skills/${s.name}`, { method: 'PUT', body: JSON.stringify(payload) });
        else await post('/v1/skills', payload);
        closeLayer();
        toast(tr('Saved'));
        await load();
      } catch (err) { fail(err); } finally { save.disabled = false; }
    });
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, s ? (isUser ? tr('Edit skill') : tr('Built-in skill')) : tr('New skill')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      s && !isUser ? h('p', { class: 'row-desc' }, tr('Saving creates your own copy in {0}; the agent then uses it instead of the built-in one.', `${folder}/${s.name}`)) : null,
      s?.files?.length ? h('p', { class: 'row-desc' }, tr('Files the skill ships: {0}', s.files.join(', '))) : null,
      h('div', { class: 'plugin-form' },
        h('div', { class: 'plugin-grid' }, field(tr('Name'), nameInput, s ? null : tr('Lowercase letters, digits and dashes; also the folder name')), field(tr('Website'), homepage, null)),
        field(tr('Description'), description, tr('The agent sees only this line until it loads the skill, so say when the skill applies.')),
        field(tr('Instructions'), body, tr('Markdown. Name the tools to use, the order of steps and the report format.')),
        h('details', { class: 'skill-advanced' }, h('summary', {}, tr('When to offer the skill')),
          h('div', { class: 'plugin-form' },
            h('div', { class: 'plugin-grid' },
              field(tr('Required tools'), requires, tr('Comma-separated; the skill is offered only when all of them are available on the device. Globs like mcp.github.* work.')),
              field(tr('Devices'), h('div', { class: 'check-row' }, osBoxes), tr('Leave all unchecked for any device.'))),
            h('label', { class: 'switch-label' }, always, tr('Offer it always, even when the required tools are missing'))))),
      h('div', { class: 'modal-actions' },
        isUser ? h('button', { class: 'btn btn-danger btn-sm', onclick: () => remove(s) }, tr('Delete')) : null,
        h('span', { class: 'spacer' }),
        h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
    ).classList.add('modal-wide');
    (s ? description : nameInput).focus();
  }

  function render() {
    const q = search.value.trim().toLowerCase();
    const match = (s) => !q || [s.name, s.description, ...s.requires_tools].join(' ').toLowerCase().includes(q);
    const mine = items.filter((s) => s.source === 'user' && match(s));
    const bundled = items.filter((s) => s.source === 'bundled' && match(s));
    list.replaceChildren(
      section(tr('Your skills'), tr('Files in {0}. Edit them here or in that folder.', folder),
        mine.length ? h('div', { class: 'rows' }, mine.map(skillRow)) : h('div', { class: 'empty rows' }, q ? tr('Nothing found.') : tr('No skills of your own yet. Create one or open a built-in skill and save it as your copy.'))),
      section(tr('Built-in'), tr('Shipped with Mensarium. Turn off the ones you do not need.'),
        bundled.length ? h('div', { class: 'rows' }, bundled.map(skillRow)) : h('div', { class: 'empty rows' }, tr('Nothing found.'))),
    );
  }

  async function load() {
    const data = await get('/v1/skills');
    items = data.items;
    folder = data.folder;
    render();
  }

  search.addEventListener('input', render);
  page(shell, tr('Skills'), tr('A skill is a SKILL.md file with instructions for one kind of work: how to review code, write tests, investigate a failure. The agent sees the names and descriptions and loads a skill with skills.read when the task matches. Same format as Agent Skills, so skills from other tools work here.'),
    [h('button', { class: 'btn btn-primary', onclick: () => editor(null) }, icon('plus'), tr('New skill'))],
    h('div', { class: 'market-bar' }, h('div', { class: 'settings-search market-search' }, icon('search'), search)),
    list,
  );
  await load();
}

function pluginState(p, devices) {
  if (!p.installed) return null;
  if (!p.installed.enabled) return [tr('Off'), ''];
  if (p.missing.length) return [tr('Needs setup'), 'warn'];
  if (!p.provides.mcp) return null;
  const where = p.placement === 'core' ? 'Core' : devices[p.placement]?.name || tr('device');
  const st = p.status || {};
  if (st.state === 'ok') return [tr('{0} · {1} tools', where, (st.tools || []).length), 'ok'];
  if (st.state === 'error') return [tr('{0} · error', where), 'danger'];
  return [tr('{0} · connecting', where), 'accent'];
}

const PLUGIN_CATEGORIES = [
  ['development', tr('Development')],
  ['browser', tr('Browser')],
  ['web', tr('Web and search')],
  ['databases', tr('Databases')],
  ['cloud', tr('Cloud and infrastructure')],
  ['observability', tr('Monitoring')],
  ['productivity', tr('Productivity')],
  ['communication', tr('Communication')],
  ['automation', tr('Automation')],
  ['system', tr('System')],
  ['other', tr('Other')],
];

async function settingsPlugins(shell) {
  const grid = h('div', { class: 'market-groups' }, h('div', { class: 'empty' }, tr('Loading the catalog...')));
  const note = h('p', { class: 'market-note hidden' });
  const search = h('input', { type: 'search', placeholder: tr('Search by name and description'), 'aria-label': tr('Search plugins') });
  let installedOnly = localStorageGet('market-installed') === '1';
  let items = [];
  let devices = {};
  let poll = 0;
  const count = h('span', { class: 'seg-count' });
  const installedSwitch = h('label', { class: 'switch-label' },
    toggleSwitch(installedOnly, { label: tr('Installed only'), onChange: async (v) => { installedOnly = v; localStorageSet('market-installed', v ? '1' : '0'); render(); } }),
    tr('Installed only'), count);

  async function act(fn, done) {
    try { const r = await fn(); if (done) toast(done); await load(); return r; } catch (err) { fail(err); return null; }
  }
  const install = (p) => act(() => post('/v1/plugins', { id: p.id }), p.installed ? tr('Updated: {0}', txt(p.name)) : tr('Installed: {0}', txt(p.name)));
  const remove = async (p) => {
    if (!await confirmDialog({ title: tr('Remove “{0}”?', txt(p.name)), text: p.installed.source === 'custom' ? tr('This is your plugin, its contents will be removed from Core.') : tr('The agent will stop using it and its saved secrets are deleted. You can install it again anytime.'), action: tr('Remove'), danger: true })) return;
    closeLayer();
    act(() => del(`/v1/plugins/${p.id}`), tr('Removed'));
  };
  const setEnabled = (p, enabled) => api(`/v1/plugins/${p.id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }).then((v) => { Object.assign(p, v); render(); });

  function cardActions(p) {
    if (!p.installed) return h('button', { class: 'btn btn-primary btn-sm', onclick: (ev) => { ev.stopPropagation(); install(p).then((v) => v?.missing?.length && details(v)); } }, icon('plus'), tr('Install'));
    const state = pluginState(p, devices);
    return h('div', { class: 'market-actions', onclick: (ev) => ev.stopPropagation() },
      h('label', { class: 'switch-label' }, toggleSwitch(p.installed.enabled, { label: tr('Enable “{0}”', txt(p.name)), onChange: (v) => setEnabled(p, v) }), tr('On')),
      state ? h('span', { class: `pill ${state[1]}` }, state[0]) : null,
      p.update ? h('button', { class: 'btn btn-sm', onclick: () => install(p) }, tr('Update to {0}', p.version)) : null);
  }

  function settingsForm(p) {
    const inputs = {};
    const secretInputs = {};
    const cleared = new Set();
    const rows = Object.entries(p.settings || {}).map(([key, spec]) => {
      const value = p.config[key];
      let control;
      if (spec.secret) {
        const isSet = !!value?.set;
        const input = h('input', { type: 'password', autocomplete: 'off', placeholder: isSet ? tr('Saved. Type to replace') : (spec.placeholder || ''), 'aria-label': settingTitle(key, spec) });
        secretInputs[key] = input;
        const clear = isSet && !spec.required ? h('button', { class: 'link-btn', onclick: (e) => { e.preventDefault(); cleared.add(key); input.value = ''; input.placeholder = tr('Will be deleted on save'); } }, tr('Delete')) : null;
        control = h('div', { class: 'secret-field' }, input, h('span', { class: `pill ${isSet ? 'ok' : spec.required ? 'warn' : ''}` }, isSet ? tr('set') : tr('not set')), clear);
      } else if (spec.type === 'boolean') {
        let current = !!value;
        control = toggleSwitch(current, { label: settingTitle(key, spec), onChange: async (v) => { current = v; } });
        inputs[key] = { get value() { return current; } };
      } else if (spec.enum) {
        control = h('select', { 'aria-label': settingTitle(key, spec) }, spec.enum.map((o) => h('option', { value: o, selected: o === value }, o)));
        inputs[key] = control;
      } else {
        control = h('input', { type: spec.type === 'integer' || spec.type === 'number' ? 'number' : 'text', value: value ?? '', placeholder: spec.placeholder || '', min: spec.minimum, max: spec.maximum, 'aria-label': settingTitle(key, spec) });
        inputs[key] = control;
      }
      const help = txt(spec.help);
      return h('div', { class: 'plugin-field' },
        h('div', { class: 'plugin-field-head' }, h('span', {}, settingTitle(key, spec)), spec.required ? h('span', { class: 'req' }, tr('required')) : null),
        control,
        help ? h('div', { class: 'row-desc' }, linkify(help)) : null);
    });
    const collect = () => {
      const values = {};
      for (const [key, input] of Object.entries(inputs)) values[key] = input.value;
      const secrets = {};
      for (const [key, input] of Object.entries(secretInputs)) if (input.value) secrets[key] = input.value;
      for (const key of cleared) if (!secrets[key]) secrets[key] = null;
      return { values, secrets };
    };
    return { rows, collect };
  }

  function mcpBlock(p, onChange) {
    if (!p.provides.mcp) return null;
    const m = p.mcp || {};
    const st = p.status || {};
    const where = h('select', { 'aria-label': tr('Where it runs') },
      h('option', { value: 'core', selected: p.placement === 'core' }, tr('In Core (the server)')),
      Object.values(devices).map((d) => h('option', { value: d.id, selected: p.placement === d.id, disabled: !d.plugins && p.placement !== d.id }, d.plugins ? d.name : tr('{0} (agent too old or offline)', d.name))),
      p.placement ? null : h('option', { value: '', selected: true, disabled: true }, tr('Choose a device')));
    const risk = h('select', { 'aria-label': tr('Risk') }, RISK_CHOICES.map(([k, label]) => h('option', { value: k, selected: k === p.risk }, label)));
    const disabled = new Set(p.disabled_tools || []);
    const toolsList = (st.tools || []).length ? h('div', { class: 'tool-rows' }, st.tools.map((t) => h('div', { class: 'tool-row' },
      icon('plug'),
      h('div', { class: 'row-text' }, h('div', { class: 'tool-row-title' }, t.name), t.description ? h('div', { class: 'row-desc' }, t.description.slice(0, 220)) : null),
      toggleSwitch(!disabled.has(t.name), { label: t.name, onChange: async (v) => {
        if (v) disabled.delete(t.name); else disabled.add(t.name);
        Object.assign(p, await api(`/v1/plugins/${p.id}/config`, { method: 'PUT', body: JSON.stringify({ disabled_tools: [...disabled] }) }));
      } })))) : null;
    const probe = h('button', { class: 'btn btn-sm', onclick: async () => {
      probe.disabled = true;
      probe.replaceChildren(h('span', { class: 'spinner' }), tr('Connecting...'));
      try { Object.assign(p, await post(`/v1/plugins/${p.id}/probe`)); onChange(); } catch (err) { fail(err); onChange(); }
    } }, icon('refresh'), tr('Check connection'));
    const stateText = { ok: tr('Connected, {0} tools', (st.tools || []).length), error: tr('Error: {0}', st.error || ''), connecting: tr('Connecting...'), off: tr('Off'), setup: tr('Needs setup') }[st.state] || tr('Not started yet');
    const runs = m.url || [m.command, ...(m.args || [])].join(' ');
    return {
      where, risk,
      el: h('div', { class: 'plugin-mcp' },
        h('div', { class: 'field-label' }, tr('MCP server')),
        h('pre', { class: 'market-argv' }, `${m.transport === 'http' ? 'http' : '$'} ${runs}`),
        h('div', { class: 'plugin-grid' },
          h('label', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, h('span', {}, tr('Where it runs'))), where),
          h('label', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, h('span', {}, tr('Risk of its tools'))), risk)),
        p.installed ? h('div', { class: `plugin-status ${st.state || ''}` }, h('span', { class: `dot ${st.state === 'ok' ? 'ok' : st.state === 'error' ? 'danger' : 'accent live'}` }), h('span', {}, stateText), h('span', { class: 'spacer' }), probe) : null,
        p.installed && p.placement && p.placement !== 'core' ? h('p', { class: 'row-desc' }, tr('On a device the program must be in its list of allowed programs, and the device must allow plugins from the Core.')) : null,
        toolsList),
    };
  }

  function details(p) {
    const form = settingsForm(p);
    const mcp = mcpBlock(p, () => { closeLayer(); details(items.find((x) => x.id === p.id) || p); });
    const coreRisk = !p.provides.mcp && p.provides.core_tools.length
      ? h('select', { 'aria-label': tr('Risk') }, RISK_CHOICES.map(([k, label]) => h('option', { value: k, selected: k === p.risk }, label)))
      : null;
    const save = h('button', { class: 'btn btn-primary' }, p.installed ? tr('Save') : tr('Install'));
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        let view = p;
        if (!p.installed) view = await post('/v1/plugins', { id: p.id });
        const { values, secrets } = form.collect();
        const body = { values, secrets };
        if (mcp && mcp.where.value) body.placement = mcp.where.value;
        if (mcp) body.risk = mcp.risk.value;
        if (coreRisk) body.risk = coreRisk.value;
        if (Object.keys(values).length || Object.keys(secrets).length || mcp || coreRisk) view = await api(`/v1/plugins/${p.id}/config`, { method: 'PUT', body: JSON.stringify(body) });
        toast(view.missing.length ? tr('Saved, still needs: {0}', view.missing.map((k) => (k === '_placement' ? tr('where it runs') : settingTitle(k, p.settings[k] || {}))).join(', ')) : tr('Saved'));
        closeLayer();
        await load();
      } catch (err) { fail(err); } finally { save.disabled = false; }
    });
    const what = [
      p.provides.core_tools.length ? h('div', { class: 'plugin-provides' }, icon('globe'), h('div', { class: 'row-text' }, h('div', { class: 'tool-row-title' }, tr('Tools in Core: {0}', p.provides.core_tools.join(', '))), h('div', { class: 'row-desc' }, tr('They run on the Core server; requests to the network go through approval unless you lower the risk.')), coreRisk ? h('label', { class: 'plugin-field plugin-risk' }, h('div', { class: 'plugin-field-head' }, h('span', {}, tr('Risk of its tools'))), coreRisk) : null)) : null,
      p.tools.length ? [h('div', { class: 'field-label' }, tr('Tools on devices')), h('div', { class: 'market-tools' }, p.tools.map((t) => h('div', { class: 'market-tool' },
        h('div', { class: 'market-tool-head' }, h('code', {}, t.name), h('span', { class: 'pill' }, RISK_SHORT[t.risk] || t.risk)),
        h('div', { class: 'row-desc' }, t.description),
        h('pre', { class: 'market-argv' }, `$ ${t.argv.join(' ')}`))))] : null,
    ];
    const state = pluginState(p, devices);
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, txt(p.name)), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('div', { class: 'market-meta' }, [p.author, tr('version {0}', p.installed ? p.installed.version : p.version), p.installed?.source === 'custom' ? tr('your plugin') : null].filter(Boolean).join(' · '), p.homepage ? [' · ', h('a', { href: p.homepage, target: '_blank', rel: 'noopener' }, tr('Website'))] : null, state ? [' ', h('span', { class: `pill ${state[1]}` }, state[0])] : null),
      h('p', {}, txt(p.description) || txt(p.summary)),
      what,
      mcp ? mcp.el : null,
      form.rows.length ? [h('div', { class: 'field-label' }, tr('Settings')), h('div', { class: 'plugin-form' }, form.rows)] : null,
      h('div', { class: 'modal-actions' },
        p.installed ? h('button', { class: 'btn btn-danger btn-sm', onclick: () => remove(p) }, tr('Remove')) : null,
        h('span', { class: 'spacer' }),
        p.update ? h('button', { class: 'btn', onclick: () => { closeLayer(); install(p); } }, tr('Update to {0}', p.version)) : null,
        (!p.installed || form.rows.length || mcp || coreRisk) ? save : null),
    ).classList.add('modal-wide');
  }

  function card(p) {
    return h('div', { class: `market-card${p.installed ? ' installed' : ''}`, role: 'button', tabindex: '0', onclick: () => details(p), onkeydown: (ev) => { if (ev.key === 'Enter') details(p); } },
      h('div', { class: 'market-card-head' }, h('span', { class: 'market-icon' }, icon(pluginIcon(p))), h('div', { class: 'market-title' }, h('div', {}, txt(p.name)), h('div', { class: 'market-meta' }, [p.author, p.installed?.source === 'custom' ? tr('your plugin') : `v${p.version}`].filter(Boolean).join(' · ')))),
      h('p', { class: 'market-summary' }, txt(p.summary)),
      h('div', { class: 'market-tags' }, pluginKinds(p).map((k) => h('span', { class: 'pill tag-kind' }, k))),
      h('div', { class: 'market-foot' }, cardActions(p)));
  }

  function render() {
    const q = search.value.trim().toLowerCase();
    count.textContent = String(items.filter((i) => i.installed).length);
    const shown = items.filter((p) => !installedOnly || p.installed)
      .filter((p) => !q || [txt(p.name), txt(p.summary), txt(p.description), p.id, p.category, ...(p.tags || []), ...p.provides.device_tools, ...p.provides.core_tools].join(' ').toLowerCase().includes(q));
    const groups = PLUGIN_CATEGORIES.map(([key, label]) => [label, shown.filter((p) => (p.category || 'other') === key).sort((a, b) => (!!b.installed - !!a.installed) || txt(a.name).localeCompare(txt(b.name)))])
      .filter(([, list]) => list.length);
    grid.replaceChildren(...(groups.length
      ? groups.map(([label, list]) => h('div', { class: 'market-group' }, h('h2', { class: 'market-group-title' }, label, h('span', { class: 'seg-count' }, String(list.length))), h('div', { class: 'market-grid' }, list.map(card))))
      : [h('div', { class: 'empty' }, installedOnly && !q ? tr('Nothing installed yet.') : tr('Nothing found.'))]));
  }

  async function load() {
    const data = await get('/v1/plugins');
    items = data.items;
    devices = Object.fromEntries(data.devices.map((d) => [d.id, d]));
    note.textContent = data.error ? tr('The mensarium.com catalog is currently unavailable, showing plugins bundled with this version of Mensarium.') : '';
    note.classList.toggle('hidden', !data.error);
    render();
    clearTimeout(poll);
    if (items.some((p) => p.installed?.enabled && p.status?.state === 'connecting')) poll = setTimeout(() => load().catch(() => {}), 2000);
  }

  function addCustom() {
    const ta = h('textarea', { class: 'market-yaml', rows: 14, spellcheck: 'false', 'aria-label': tr('Plugin manifest'),
      placeholder: 'id: my-tools\nname: {en: My tools, ru: Мои инструменты}\nversion: 1.0.0\nsummary: What it does\ncategory: development\ntools:\n  - name: my.tool\n    description: ...\n    argv: [program, --flag]' });
    const save = h('button', { class: 'btn btn-primary' }, tr('Install'));
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        await api('/v1/plugins/custom', { method: 'POST', body: ta.value, headers: { 'Content-Type': 'text/plain' } });
        closeLayer();
        toast(tr('Plugin installed'));
        await load();
      } catch (err) { fail(err); } finally { save.disabled = false; }
    });
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, tr('Your own plugin')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('p', {}, tr('Paste a YAML manifest. Device tools are a tools list with a command in argv, an MCP server is an mcp block; settings go into config. Same format as catalog plugins. Instructions for the agent are skills, they live on the Skills page.')),
      ta,
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
    ).classList.add('modal-wide');
    ta.focus();
  }

  function addMcp() {
    const name = h('input', { type: 'text', placeholder: 'github', 'aria-label': tr('Name') });
    const transport = h('select', { 'aria-label': tr('Connection') }, h('option', { value: 'stdio' }, tr('Program (stdio)')), h('option', { value: 'http' }, tr('Address (HTTP)')));
    const command = h('input', { type: 'text', placeholder: 'npx -y @modelcontextprotocol/server-everything', 'aria-label': tr('Command') });
    const url = h('input', { type: 'text', placeholder: 'https://example.com/mcp', 'aria-label': tr('Address') });
    const where = h('select', { 'aria-label': tr('Where it runs') }, h('option', { value: 'core' }, tr('In Core (the server)')), Object.values(devices).filter((d) => d.plugins).map((d) => h('option', { value: d.id }, d.name)));
    const risk = h('select', { 'aria-label': tr('Risk') }, RISK_CHOICES.map(([k, label]) => h('option', { value: k, selected: k === 'network' }, label)));
    const env = h('textarea', { class: 'market-yaml', rows: 3, spellcheck: 'false', placeholder: 'KEY=value', 'aria-label': tr('Environment variables') });
    const secretEnv = h('textarea', { class: 'market-yaml', rows: 2, spellcheck: 'false', placeholder: 'API_TOKEN=...', 'aria-label': tr('Secret values') });
    const description = h('input', { type: 'text', placeholder: tr('What it is for'), 'aria-label': tr('Description') });
    const field = (label, control, hint) => h('label', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, h('span', {}, label)), control, hint ? h('div', { class: 'row-desc' }, hint) : null);
    const cmdField = field(tr('Command'), command, tr('The program must be installed where the server runs; on a device it must also be in its allowed programs.'));
    const urlField = field(tr('Address'), url, null);
    const sync = () => { cmdField.classList.toggle('hidden', transport.value !== 'stdio'); urlField.classList.toggle('hidden', transport.value === 'stdio'); };
    transport.addEventListener('change', sync);
    sync();
    const pairs = (text) => Object.fromEntries(text.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.indexOf('='); return i > 0 ? [l.slice(0, i).trim(), l.slice(i + 1)] : [l, '']; }));
    const save = h('button', { class: 'btn btn-primary' }, tr('Add'));
    save.addEventListener('click', async () => {
      save.disabled = true;
      const http = transport.value === 'http';
      const body = { name: name.value.trim().toLowerCase(), transport: transport.value, command: http ? null : command.value.trim(), url: http ? url.value.trim() : null, placement: where.value, risk: risk.value, description: description.value.trim() };
      body[http ? 'headers' : 'env'] = pairs(env.value);
      body[http ? 'secret_headers' : 'secret_env'] = pairs(secretEnv.value);
      try {
        const view = await post('/v1/plugins/mcp', body);
        closeLayer();
        toast(tr('MCP server added, connecting'));
        await load();
        details(items.find((x) => x.id === view.id) || view);
      } catch (err) { fail(err); } finally { save.disabled = false; }
    });
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, tr('Add an MCP server')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('p', {}, tr('The agent gets the server’s tools as mcp.<name>.<tool>. Secret values are stored in Core and never reach the model; a server with secrets runs only in Core.')),
      h('div', { class: 'plugin-form' },
        h('div', { class: 'plugin-grid' }, field(tr('Name'), name, tr('Lowercase letters, digits and dashes')), field(tr('Connection'), transport, null)),
        cmdField, urlField,
        h('div', { class: 'plugin-grid' }, field(tr('Where it runs'), where, null), field(tr('Risk of its tools'), risk, null)),
        field(tr('Environment variables or headers'), env, tr('One KEY=value per line: environment for a program, HTTP headers for an address.')),
        field(tr('Secret values'), secretEnv, tr('Same format; stored as secrets in Core.')),
        field(tr('Description'), description, null)),
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
    ).classList.add('modal-wide');
    name.focus();
  }

  search.addEventListener('input', render);
  page(shell, tr('Plugins'), tr('Plugins add abilities to the agent: tools on devices, tools in Core such as web search, and MCP servers. Everything is configured here or with mensarium plugins on the Core server.'),
    [h('button', { class: 'btn', onclick: addCustom }, icon('plus'), tr('Your own plugin')), h('button', { class: 'btn btn-primary', onclick: addMcp }, icon('plug'), tr('Add an MCP server'))],
    h('div', { class: 'market-bar' }, h('div', { class: 'settings-search market-search' }, icon('search'), search), installedSwitch),
    note,
    grid,
  );
  viewCleanups.push(() => clearTimeout(poll));
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
    'extension.installed': tr('Plugin installed'), 'extension.toggled': tr('Plugin enabled or disabled'), 'extension.removed': tr('Plugin removed'),
    'plugin.installed': tr('Plugin installed'), 'plugin.toggled': tr('Plugin enabled or disabled'), 'plugin.removed': tr('Plugin removed'),
    'plugin.configured': tr('Plugin settings changed'),
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
      p.source === 'custom' && tr('custom plugin'),
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
