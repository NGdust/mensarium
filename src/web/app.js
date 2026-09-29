// Mensarium web UI. Vanilla ES module, no build step, no dependencies.

import { LANGUAGES, lang, locale, setLang, t as tr, tp } from './i18n.js';
import { THEMES, setTheme, themeChoice } from './theme.js';
import { createOrb } from './orb.js';
import { createMemoryMap, graphColor } from './graph.js';

const $app = document.getElementById('app');
const $toasts = document.getElementById('toasts');
const $layer = document.getElementById('layer');

const state = { system: null, gateway: null, coreOffline: false, limits: null, limitsBusy: new Set(), targets: [], tasks: [], projects: [], shell: null, lastChat: '#/', updates: new Map() };
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
  if (res.status === 503 && data?.error === 'core-offline') {
    setCoreOffline(true);
    throw Object.assign(new Error(tr('Core is offline')), { status: 503, code: 'core-offline' });
  }
  if (!res.ok) {
    const detail = Array.isArray(data?.detail) ? data.detail.map((d) => String(d.msg).replace(/^Value error, /, '')).join('; ') : data?.detail;
    throw Object.assign(new Error(detail || tr('Request error ({0})', res.status)), { status: res.status });
  }
  return data;
}
const get = (path) => api(path);
const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body || {}) });
const del = (path) => api(path, { method: 'DELETE' });

function fail(err) {
  if (err instanceof AuthError) { showLogin(); return; }
  if (err?.code === 'core-offline') return;
  toast(err.message || String(err), true);
}

// ---------- gateway ----------

async function loadGateway() {
  try {
    const res = await fetch('/v1/gateway', { credentials: 'same-origin' });
    state.gateway = res.ok ? await res.json() : null;
  } catch { state.gateway = null; }
  return state.gateway;
}

let offlineTimer = null;
function setCoreOffline(offline) {
  if (state.coreOffline === offline) return;
  state.coreOffline = offline;
  document.body.classList.toggle('core-offline', offline);
  let banner = document.getElementById('core-offline');
  if (offline) {
    if (!banner) {
      banner = h('div', { id: 'core-offline', class: 'offline-banner', role: 'status' }, icon('alert'), h('span', {}, tr('Core is offline, reconnecting...')));
      document.body.prepend(banner);
    }
    if (!offlineTimer) offlineTimer = setInterval(async () => {
      const g = await loadGateway();
      if (g && g.online) {
        setCoreOffline(false);
        state.system = null;
        state.shell = null;
        boot();
      }
    }, 5000);
  } else {
    banner?.remove();
    if (offlineTimer) { clearInterval(offlineTimer); offlineTimer = null; }
  }
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
  panelRight: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M15 4v16"/>',
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
  paperclip: '<path d="m21 11.5-8.6 8.6a5 5 0 0 1-7-7l9-9a3.3 3.3 0 0 1 4.7 4.7l-9 9a1.7 1.7 0 0 1-2.4-2.4L16 7.3"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/>',
  fileText: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m21 16-5-5-8 8"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a1 1 0 0 1 1-1h9"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  gauge: '<path d="M12 14 16 8"/><path d="M4 18a9 9 0 1 1 16 0"/><circle cx="12" cy="14" r="1"/>',
  alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  exclaim: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>',
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
  send: '<path d="m21 3-7 18-4-8-8-4z"/><path d="M21 3 10 13"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  user: '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20c0-4 3.4-6.5 7.5-6.5s7.5 2.5 7.5 6.5"/>',
  agents: '<circle cx="9" cy="8" r="3.2"/><path d="M3 19c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 13.6c2.7.3 4.5 2.3 4.5 5.4"/>',
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
  IDLE: [tr('New'), '', false],
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
  full: { label: tr('Full access'), icon: 'bolt', cls: 'full', desc: tr('Any file, program or system command without asking, within OS permissions.') },
};
const TEMPLATES = [
  ['cpu', tr('Device resources'), tr('Check the device resources: CPU load, memory, free disk space, uptime. List the top processes by CPU and memory and say whether anything looks off.')],
  ['pulse', tr('What is slowing it down'), tr('The device is slow. Find the processes that load the CPU and memory the most and suggest what can be closed. Don\'t stop any process without asking.')],
  ['layers', tr('What takes up disk space'), tr('Find what takes up the most space in the home folder: the largest folders and files, caches, old downloads. Don\'t delete anything, just list them with sizes.')],
  ['link', tr('Open ports'), tr('Show which ports are listening on the device and which processes own them. Point out anything unexpected.')],
  ['terminal', tr('Why tests are failing'), tr('Run the project\'s tests, find why they\'re failing, and explain it. Don\'t change files yet.')],
  ['git', tr('What changed'), tr('Show what changed in the repository since the last commit, and briefly describe the changes.')],
];
const TOOL_ICON = { 'files.list': 'folder', 'files.read': 'file', 'files.search': 'search', 'files.stat': 'file', 'files.find': 'search', 'files.write': 'file', 'files.edit': 'file', 'files.mkdir': 'folder', 'files.move': 'folder', 'files.copy': 'folder', 'files.delete': 'trash', 'git.status': 'git', 'git.diff': 'git', 'system.info': 'cpu', 'process.list': 'cpu', 'process.kill': 'ban', 'net.ports': 'link', 'net.http': 'globe', 'shell.exec': 'terminal', 'shell.bash': 'terminal', 'screen.capture': 'laptop', 'screen.windows': 'sidebar', 'input.mouse': 'cpu', 'input.type': 'cpu', 'input.key': 'cpu', 'app.open': 'bolt', 'system.volume': 'pulse', 'skills.read': 'book', 'memory.search': 'graph', 'memory.read': 'graph', 'memory.save': 'graph', 'web.search': 'globe', 'web.fetch': 'globe', 'gmail.search': 'send', 'gmail.read': 'send', 'gmail.send': 'send', 'drive.search': 'folder', 'drive.read': 'file', 'plan.update': 'list', 'agent.spawn': 'agents', 'agent.wait': 'agents' };
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
const isThisDevice = (t) => t && t.id === state.gateway?.target_id;
const fullAccessOf = (t) => t?.capabilities?.full_access || 'disabled';
const fullAccessBlock = (t) => (fullAccessOf(t) === 'outdated'
  ? tr('The device agent is outdated (v{0}). Update it in Settings → Devices.', t.agent_version)
  : tr('Disabled on the device: allow_full_access in its config.'));
const devices = () => state.targets.filter((t) => t.status !== 'revoked').sort((a, b) => isThisDevice(b) - isThisDevice(a));
const taskTitle = (t) => ((t.input || '').split('\n')[0] || tr('Untitled')).slice(0, 80);
// A folder project never shows git words (branch, commit, merge): only a repo project may.
const KIND_ICON = { repo: 'git', folder: 'folder' };
const kindLabel = (p) => (p.kind === 'repo' ? tr('Git repository') : tr('Folder'));
// Core's file_limit_mb for a project that does not set its own.
const DEFAULT_FILE_LIMIT_MB = 100;

// ---------- overlays ----------

// A popover opened over a modal closes on its own and leaves the modal; otherwise the whole layer goes.
function closeLayer() {
  const pops = $layer.querySelectorAll(':scope > .popover, :scope > .pop-catcher');
  if (pops.length && $layer.querySelector(':scope > .backdrop')) pops.forEach((n) => n.remove());
  else $layer.replaceChildren();
}
function clearLayer() { $layer.replaceChildren(); }

function openPopover(anchor, items, cls = '', align = 'left') {
  if ($layer.querySelector(':scope > .backdrop')) $layer.querySelectorAll(':scope > .popover, :scope > .pop-catcher').forEach((n) => n.remove());
  else clearLayer();
  const pop = h('div', { class: `popover ${cls}`, role: 'menu' }, items);
  $layer.append(h('div', { class: 'pop-catcher', onclick: closeLayer }), pop);
  const place = () => {
    const r = anchor.getBoundingClientRect();
    const top = r.top - pop.offsetHeight - 8 > 8 ? r.top - pop.offsetHeight - 8 : r.bottom + 8;
    const left = align === 'right' ? r.right - pop.offsetWidth : r.left;
    pop.style.top = `${top}px`;
    pop.style.left = `${Math.max(8, Math.min(left, innerWidth - pop.offsetWidth - 8))}px`;
  };
  place();
  return place;
}

function openModal(...content) {
  clearLayer();
  const modal = h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' }, content);
  const backdrop = h('div', { class: 'backdrop', onclick: (e) => { if (e.target === backdrop) closeLayer(); } }, modal);
  $layer.append(backdrop);
  return modal;
}

function confirmDialog({ title, text, action, danger = false, extra = null }) {
  return new Promise((resolve) => {
    const done = (value) => { closeLayer(); resolve(value); };
    const ok = h('button', { class: `btn ${danger ? 'btn-danger-solid' : 'btn-primary'}`, onclick: () => done(true) }, action);
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, title)),
      h('p', {}, text),
      extra,
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
    h('div', { class: 'field-label' }, tr('Install Mensarium (skip if installed)')),
    line(data.install_command),
    h('div', { class: 'field-label' }, tr('Then pair, worker and web UI are asked next')),
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

function languageSelect() {
  return h('select', { class: 'lang-select', 'aria-label': tr('Language'), onchange: (e) => { if (e.target.value !== lang) setLang(e.target.value); } },
    Object.entries(LANGUAGES).map(([code, name]) => h('option', { value: code, selected: code === lang }, name)));
}

const THEME_NAMES = { dark: () => tr('Dark'), light: () => tr('Light'), auto: () => tr('System theme') };

function themeSelect() {
  return h('select', { class: 'theme-select', 'aria-label': tr('Theme'), onchange: (e) => { if (e.target.value !== themeChoice) setTheme(e.target.value); } },
    THEMES.map((key) => h('option', { value: key, selected: key === themeChoice }, THEME_NAMES[key]())));
}

// ---------- usage limits ----------

async function loadLimits() {
  try { state.limits = await get('/v1/limits'); } catch { return state.limits; }
  renderLimitBanners();
  state.limitsRender?.();
  return state.limits;
}

async function refreshLimits(providerId) {
  if (state.limitsBusy.has(providerId)) return;
  state.limitsBusy.add(providerId);
  state.limitsRender?.();
  try { state.limits = await post('/v1/limits/refresh', { provider_id: providerId }); renderLimitBanners(); }
  catch (err) { fail(err); }
  finally { state.limitsBusy.delete(providerId); state.limitsRender?.(); }
}

function untilText(iso) {
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return '';
  if (ms <= 0) return tr('resets now');
  const m = Math.round(ms / 60000);
  if (m < 60) return tr('resets in {0} min', m);
  const hours = Math.floor(m / 60);
  if (hours < 24) return tr('resets in {0} h {1} min', hours, m % 60);
  if (hours < 24 * 14) return tr('resets in {0} d {1} h', Math.floor(hours / 24), hours % 24);
  return tr('resets {0}', new Date(iso).toLocaleString(locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }));
}

const windowLabel = (w) => ({ '5 hours': tr('5-hour window'), '7 days': tr('weekly window'), 'credits': tr('credits'), 'requests per minute': tr('requests per minute'), 'tokens per minute': tr('tokens per minute') }[w.label] || w.label);
const hotWindows = (p, d = state.limits) => (p?.windows || []).filter((w) => w.used_percent >= (d?.threshold || 0.75) * 100);

function meter(w, threshold) {
  const pct = Math.min(100, Math.max(0, w.used_percent));
  const level = pct >= 90 ? 'danger' : pct >= threshold * 100 ? 'warn' : '';
  return h('div', { class: `limit-row ${level}` },
    h('div', { class: 'limit-label' }, h('span', {}, windowLabel(w), w.model ? h('code', { class: 'provider-id' }, modelLabel(w.model)) : null), h('span', { class: 'limit-pct' }, `${Math.round(pct)}%`)),
    h('div', { class: 'meter', role: 'progressbar', 'aria-valuenow': String(Math.round(pct)), 'aria-valuemin': '0', 'aria-valuemax': '100' }, h('div', { class: 'meter-fill', style: `width:${pct}%` })),
    h('div', { class: 'row-desc' }, [w.detail, w.resets_at ? untilText(w.resets_at) : null].filter(Boolean).join(' · ')));
}

function limitsBody() {
  const d = state.limits;
  if (!d) return [h('div', { class: 'empty rows' }, tr('Limits are not loaded yet.'))];
  if (!d.providers.length) return [h('div', { class: 'empty rows' }, tr('No providers yet.'))];
  return d.providers.map((p) => h('div', { class: 'limit-provider' },
    h('div', { class: 'limit-provider-head' },
      h('strong', {}, p.title, p.provider_id !== p.kind ? h('code', { class: 'provider-id' }, p.provider_id) : null),
      h('span', { class: 'spacer' }),
      p.checked_at ? h('span', { class: 'market-meta', title: p.source }, tr('checked {0}', relTime(p.checked_at))) : null,
      p.supported ? h('button', { class: `icon-btn${state.limitsBusy.has(p.provider_id) ? ' spinning' : ''}`, title: tr('Refresh'), 'aria-label': tr('Refresh'), disabled: state.limitsBusy.has(p.provider_id), onclick: () => refreshLimits(p.provider_id) }, icon('refresh')) : null),
    p.windows.length ? p.windows.map((w) => meter(w, d.threshold)) : h('p', { class: 'row-desc' }, p.error ? tr('Error: {0}', p.error) : p.note ? tr(p.note) : (p.supported ? tr('No data yet.') : tr('This provider does not report limits.')))));
}

function limitsModal() {
  const body = h('div', { class: 'limits-list' });
  const render = () => body.replaceChildren(...limitsBody());
  render();
  state.limitsRender = () => { if (body.isConnected) render(); };
  openModal(
    h('div', { class: 'modal-head' }, h('h2', {}, tr('Usage limits')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
    h('p', { class: 'row-desc' }, tr('The Core checks the limits on its own: Codex and OpenRouter every 10 minutes, Claude Code every 30 minutes with a tiny haiku call. The arrow next to a provider checks it right now.')),
    body,
    h('div', { class: 'modal-actions' }, h('span', { class: 'spacer' }), h('button', { class: 'btn btn-primary', onclick: closeLayer }, tr('Close'))),
  ).classList.add('modal-wide');
  loadLimits();
}

function limitBanner() {
  const d = state.limits;
  const p = d?.providers.find((x) => x.provider_id === d.active);
  const hot = hotWindows(p, d);
  if (!p || !hot.length) return null;
  const worst = hot.reduce((a, b) => (b.used_percent > a.used_percent ? b : a));
  const parts = hot.map((w) => [tr('{0}: {1}% used', windowLabel(w), Math.round(w.used_percent)), w.resets_at ? untilText(w.resets_at) : null].filter(Boolean).join(' · '));
  return h('div', { class: `limit-strip${worst.used_percent >= 90 ? ' danger' : ''}`, role: 'status' }, icon('gauge'),
    h('span', { title: p.title }, parts.join(' · ')),
    h('button', { class: 'link-btn', onclick: limitsModal }, tr('View usage')));
}

function renderLimitBanners() {
  for (const box of document.querySelectorAll('.composer-notice')) box.replaceChildren(limitBanner() || '');
}

// ---------- login ----------

function showLogin() {
  cleanupAll();
  state.shell = null;
  const label = tr('Gateway token');
  const input = h('input', { type: 'password', placeholder: label, autocomplete: 'current-password', 'aria-label': label });
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
    h('p', {}, tr('The token is issued by the command '), h('code', {}, state.gateway?.core ? 'mensarium core token' : 'mensarium client gateway token'), tr(' on this machine.')),
    input, btn,
  )));
  input.focus();
}

// ---------- data ----------

async function refreshData() {
  const [targets, tasks, projects] = await Promise.all([
    get('/v1/targets'),
    get('/v1/tasks'),
    // A Core older than this client has no projects yet.
    get('/v1/projects').catch((err) => (err.status === 404 ? { items: [] } : Promise.reject(err))),
  ]);
  state.targets = targets;
  state.tasks = tasks;
  state.projects = projects.items;
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

// A device reads at a glance by its first letter on a hue of its own, the same in every list.
const DEVICE_HUES = [265, 310, 355, 40, 85, 130, 175, 220];
function deviceBadge(id, name, online, status) {
  let n = 0;
  for (const ch of id || '') n = (n * 31 + ch.charCodeAt(0)) >>> 0;
  const label = name || id || '?';
  return h('span', { class: `device-badge${online ? '' : ' off'}`, style: `--hue:${DEVICE_HUES[n % DEVICE_HUES.length]}`, title: online ? label : `${label} · ${tr('offline')}` },
    [...label.trim()][0]?.toUpperCase() || '?', status ? h('span', { class: `dot ${status}` }) : null);
}

function ensureAppShell() {
  if (state.shell && state.shell.kind === 'app') return state.shell;
  const sessions = h('div', { class: 'sessions' });
  const projectsBox = h('div', { class: 'projects' });
  const devicesCount = h('span', { class: 'count' });
  const newChat = h('a', { class: 'icon-btn nav-add', href: '#/', title: tr('New chat'), 'aria-label': tr('New chat') }, icon('plus'));
  const newProject = h('a', { class: 'icon-btn nav-add', href: '#/projects/new', title: tr('Create project'), 'aria-label': tr('Create project') }, icon('plus'));
  const automationsLink = h('a', { class: 'nav-item nav-automations', href: '#/automations' }, icon('clock'), tr('Automations'));
  const devicesLink = h('a', { class: 'nav-item', href: '#/settings/devices' }, icon('laptop'), tr('Devices'), devicesCount);
  const folded = new Set(JSON.parse(localStorageGet('nav-collapsed') || '[]'));
  // The list right after a folded head is hidden by CSS, so the head only flips aria-expanded.
  const navSection = (key, label, add) => h('div', { class: 'nav-head' },
    h('button', { class: 'nav-section', 'aria-expanded': String(!folded.has(key)), onclick: (e) => {
      if (folded.has(key)) folded.delete(key); else folded.add(key);
      e.currentTarget.setAttribute('aria-expanded', String(!folded.has(key)));
      localStorageSet('nav-collapsed', JSON.stringify([...folded]));
    } }, icon('chevron'), h('span', {}, label)),
    add);
  let s;
  const collapse = h('button', { class: 'icon-btn collapse-nav', 'aria-label': tr('Hide sidebar'), title: tr('Hide sidebar'), onclick: () => s.toggleNav() }, icon('sidebar'));
  s = frame('app', [
    h('div', { class: 'brand' }, orb('sm'), h('span', { class: 'brand-name' }, 'Mensarium'), collapse),
    automationsLink,
    navSection('projects', tr('Projects'), newProject),
    projectsBox,
    navSection('chats', tr('Chats'), newChat),
    sessions,
    h('div', { class: 'sidebar-foot' }, devicesLink, h('div', { class: 'sidebar-foot-row' },
      h('a', { class: 'nav-item', href: '#/settings/overview' }, icon('sliders'), tr('Settings')),
      h('button', { class: 'icon-btn limits-btn', title: tr('Usage limits'), 'aria-label': tr('Usage limits'), onclick: limitsModal }, icon('gauge')))),
  ]);

  function renderSessions() {
    const online = devices().filter((t) => t.status === 'online').length;
    devicesCount.replaceChildren(h('span', { class: `dot${online ? ' ok' : ''}` }), tr('{0} online', online));
    const activeId = (location.hash.match(/^#\/chat\/(.+)$/) || [])[1];
    const activeProject = state.tasks.find((t) => t.id === activeId)?.project_id;
    const onAutomations = location.hash.startsWith('#/automations');
    automationsLink.classList.toggle('active', onAutomations);
    newProject.classList.toggle('active', location.hash === '#/projects/new');
    newChat.classList.toggle('active', !activeId && !onAutomations && !location.hash.startsWith('#/settings') && !location.hash.startsWith('#/projects'));
    const isOnline = (id) => state.targets.some((t) => t.id === id && t.status === 'online');
    projectsBox.replaceChildren(...state.projects.map((p) => {
      const active = activeProject === p.id || location.hash === `#/projects/${p.id}` || location.hash === `#/projects/${p.id}/new`;
      const busy = p.status === 'creating' || p.syncing;
      return h('div', { class: `project-head${active ? ' active' : ''}` },
        h('a', { class: 'project-link', href: `#/projects/${p.id}`, title: `${p.source_name || ''}:${p.source_path}` },
          deviceBadge(p.source_target_id, p.source_name, p.source_online, busy ? 'accent live' : p.status === 'error' ? 'danger' : ''),
          h('span', { class: 'session-title' }, p.name)),
        p.status === 'ready' ? h('a', { class: 'icon-btn session-add', href: `#/projects/${p.id}/new`, title: tr('New chat in project'), 'aria-label': tr('New chat in project') }, icon('plus')) : null);
    }));
    // Project chats live on their project's page; the sidebar lists the rest.
    const plain = state.tasks.filter((t) => !t.project_id);
    sessions.replaceChildren(...(plain.length ? plain.map((t) => {
      const [, kind, live] = statusOf(t.status);
      // Only what needs a look gets a mark: work in progress, a pending decision, an error.
      const mark = kind && kind !== 'ok' ? `${kind}${live ? ' live' : ''}` : '';
      return h('a', { class: `session${t.id === activeId ? ' active' : ''}`, href: `#/chat/${t.id}`, title: t.input },
        deviceBadge(t.target_id, t.target_name, isOnline(t.target_id), mark),
        h('span', { class: 'session-title' }, taskTitle(t)),
        h('button', { class: 'icon-btn session-del', title: tr('Delete chat'), 'aria-label': tr('Delete chat'), onclick: (e) => { e.preventDefault(); e.stopPropagation(); deleteChat(t); } }, icon('trash')));
    }) : [h('div', { class: 'sessions-empty' }, tr('Chats with the agent will appear here.'))]));
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

// Files the browser accepts before the upload; the Core checks the bytes again and decides the real type.
const MAX_FILE_BYTES = 12 * 1024 * 1024;
const MAX_FILES = 10;

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const fileKind = (a) => (a.type === 'image' || (a.mime || '').startsWith('image/') ? 'image' : 'fileText');

// One block per attached file: a small thumbnail for pictures (click opens it large), an icon with the name and
// size for the rest (click downloads).
function attachmentList(files) {
  if (!files?.length) return null;
  return h('div', { class: 'attachments' }, files.map((a) => {
    const url = `/v1/artifacts/${a.id}`;
    const image = fileKind(a) === 'image';
    const body = [
      image ? h('img', { src: url, alt: a.name, loading: 'lazy' }) : icon('fileText'),
      h('span', { class: 'attachment-name' }, a.name),
      h('span', { class: 'attachment-meta' }, fmtBytes(a.size)),
    ];
    if (!image) return h('a', { class: 'attachment', href: url, target: '_blank', rel: 'noopener', title: a.name }, body);
    return h('button', { class: 'attachment is-image', type: 'button', title: tr('Open the picture'), onclick: () => openPicture(url, a.name) }, body);
  }));
}

function openPicture(url, name) {
  const modal = openModal(
    h('img', { class: 'picture-full', src: url, alt: name }),
    h('div', { class: 'picture-foot' }, h('span', { class: 'attachment-name' }, name), h('span', { class: 'spacer' }),
      h('a', { class: 'btn', href: url, target: '_blank', rel: 'noopener' }, tr('Open in a new tab')),
      h('button', { class: 'btn', onclick: closeLayer }, tr('Close'))),
  );
  modal.classList.add('modal-picture');
}

// Dictation through the browser's speech recognition. Chrome, Edge and Safari have it; the page must be secure
// (https or localhost), otherwise the browser never grants the microphone.
const SpeechApi = window.SpeechRecognition || window.webkitSpeechRecognition;
const dictationProblem = () => (!window.isSecureContext ? tr('The microphone works only on a secure page: open the interface over https or from localhost.')
  : !SpeechApi ? tr('This browser has no speech recognition; use Chrome, Edge or Safari.') : '');

function dictation(ta, onChange) {
  const problem = dictationProblem();
  const btn = h('button', { class: `mic${problem ? ' unavailable' : ''}`, type: 'button', title: problem || tr('Dictate'), 'aria-label': tr('Dictate'), 'aria-pressed': 'false' }, icon('mic'));
  let rec = null;
  let base = '';
  const stop = () => { rec?.stop(); };
  const ended = () => {
    rec = null;
    btn.classList.remove('listening');
    btn.setAttribute('aria-pressed', 'false');
    btn.title = tr('Dictate');
  };
  const start = () => {
    if (problem) { toast(problem, true); return; }
    rec = new SpeechApi();
    rec.lang = locale;
    rec.continuous = true;
    rec.interimResults = true;
    base = ta.value && !/\s$/.test(ta.value) ? `${ta.value} ` : ta.value;
    rec.onresult = (e) => {
      let done = '';
      let interim = '';
      for (const r of e.results) (r.isFinal ? (done += r[0].transcript) : (interim += r[0].transcript));
      ta.value = base + done + interim;
      onChange();
    };
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') toast(tr('Microphone access was denied'), true);
      else if (e.error !== 'aborted' && e.error !== 'no-speech') toast(tr('Dictation failed: {0}', e.error), true);
    };
    rec.onend = ended;
    try { rec.start(); } catch (err) { ended(); fail(err); return; }
    btn.classList.add('listening');
    btn.setAttribute('aria-pressed', 'true');
    btn.title = tr('Stop dictation');
  };
  btn.addEventListener('click', () => (rec ? stop() : start()));
  return { el: btn, stop, set disabled(v) { btn.disabled = v; if (v) stop(); } };
}

// The round button sends a message; while the agent works it becomes a pulsing stop, on a pause it resumes.
function composer({ placeholder, chips, tail, above, onSend, onStop, onResume }) {
  const ta = h('textarea', { rows: 1, placeholder, 'aria-label': placeholder });
  const send = h('button', { class: 'send', disabled: true });
  const notice = h('div', { class: 'composer-notice' }, limitBanner() || '');
  const picker = h('input', { type: 'file', multiple: true, hidden: true, 'aria-hidden': 'true' });
  const attach = h('button', { class: 'icon-btn attach', type: 'button', title: tr('Attach files'), 'aria-label': tr('Attach files'), onclick: () => picker.click() }, icon('paperclip'));
  const strip = h('div', { class: 'attach-strip' });
  const mic = dictation(ta, () => { grow(); sync(); });
  const box = h('div', { class: 'composer' },
    notice,
    strip,
    h('div', { class: 'composer-input' }, ta),
    h('div', { class: 'composer-bar' }, attach, chips, h('span', { class: 'spacer' }), tail, mic.el, send),
    picker,
  );
  let mode = 'idle';
  let hint = '';
  let busy = false;
  let shown = '';
  let files = [];
  const action = () => (mode === 'running' ? 'stop' : mode === 'paused' && !ta.value.trim() && !files.length ? 'resume' : 'send');
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
    send.disabled = busy || (a === 'send' && !ta.value.trim() && !files.length);
    ta.disabled = mode === 'running';
    attach.disabled = busy || mode === 'running';
    mic.disabled = busy || mode === 'running';
    ta.placeholder = mode === 'running' ? hint : mode === 'paused' ? tr('Resume the agent or write what to do next') : placeholder;
  };
  const grow = () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`; };
  const renderFiles = () => {
    strip.replaceChildren(...files.map((f) => h('div', { class: `attach-row${f.url ? ' is-image' : ''}${f.state ? ` ${f.state}` : ''}` },
      f.url ? h('img', { src: f.url, alt: '' }) : icon('fileText'),
      h('span', { class: 'attach-name' }, f.file.name),
      h('span', { class: 'attach-meta' }, f.state === 'uploading' ? tr('Uploading...') : fmtBytes(f.file.size)),
      h('button', { class: 'icon-btn attach-remove', type: 'button', title: tr('Remove'), 'aria-label': tr('Remove {0}', f.file.name), onclick: () => { if (f.url) URL.revokeObjectURL(f.url); files = files.filter((x) => x !== f); renderFiles(); sync(); } }, icon('x')))));
    box.classList.toggle('has-files', files.length > 0);
  };
  const addFiles = (list) => {
    for (const file of list) {
      if (files.length >= MAX_FILES) { toast(tr('At most {0} files per message', MAX_FILES), true); break; }
      if (file.size > MAX_FILE_BYTES) { toast(tr('“{0}” is larger than {1} MB', file.name, MAX_FILE_BYTES / 1024 / 1024), true); continue; }
      if (!file.size) { toast(tr('“{0}” is empty', file.name), true); continue; }
      files.push({ file, url: file.type.startsWith('image/') ? URL.createObjectURL(file) : null, state: '' });
    }
    renderFiles();
    sync();
  };
  picker.addEventListener('change', () => { addFiles(picker.files); picker.value = ''; });
  ta.addEventListener('paste', (e) => {
    const pasted = [...(e.clipboardData?.files || [])];
    if (pasted.length) { e.preventDefault(); addFiles(pasted); }
  });
  let dragDepth = 0;
  box.addEventListener('dragenter', (e) => { if (e.dataTransfer?.types.includes('Files')) { dragDepth += 1; box.classList.add('drop'); } });
  box.addEventListener('dragleave', () => { if (dragDepth > 0) dragDepth -= 1; if (!dragDepth) box.classList.remove('drop'); });
  box.addEventListener('dragover', (e) => { if (e.dataTransfer?.types.includes('Files')) e.preventDefault(); });
  box.addEventListener('drop', (e) => { e.preventDefault(); dragDepth = 0; box.classList.remove('drop'); if (mode !== 'running' && !busy) addFiles(e.dataTransfer.files); });
  ta.addEventListener('input', () => { grow(); sync(); });
  const run = async (fn) => {
    busy = true;
    sync();
    try { await fn(); } catch (err) { fail(err); } finally { busy = false; sync(); }
  };
  const upload = async (f) => {
    f.state = 'uploading';
    renderFiles();
    try {
      const meta = await api(`/v1/attachments?name=${encodeURIComponent(f.file.name)}`, { method: 'POST', body: f.file, headers: { 'Content-Type': 'application/octet-stream' } });
      f.state = '';
      return meta.id;
    } catch (err) {
      f.state = 'failed';
      renderFiles();
      throw new Error(tr('“{0}”: {1}', f.file.name, err.message || String(err)));
    }
  };
  const submit = () => {
    const text = ta.value.trim();
    if ((!text && !files.length) || mode === 'running' || busy) return;
    mic.stop();
    return run(async () => {
      const ids = [];
      for (const f of files) ids.push(await upload(f));
      await onSend(text, ids);
      for (const f of files) if (f.url) URL.revokeObjectURL(f.url);
      files = [];
      renderFiles();
      ta.value = '';
      grow();
    });
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
    el: h('div', { class: 'composer-wrap' }, above, box),
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
          text: tr('The agent will access all files, run any program and system command, and use the network on “{0}” without asking, within the OS account permissions. You can switch back anytime.', target()?.name || tr('the device')),
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
const defaultProvider = () => state.system?.provider?.name || '';
const MODEL_NOTES = { 'mistral-large-3:675b': () => tr('uncensored') };
const modelLabel = (id) => (MODEL_NOTES[id] ? `${id} · ${MODEL_NOTES[id]()}` : id);
function loadModels() {
  if (!state.models) state.models = get('/v1/models').catch((err) => { state.models = null; throw err; });
  return state.models;
}

// One list of every provider's models, grouped by provider; a pick sets both the provider and the model.
function modelSwitch(initial, { onPick }) {
  let { provider = '', model = '' } = initial || {};
  const label = h('span', { class: 'chip-label' });
  const chip = h('button', { class: 'chip chip-compact chip-model', title: tr('Model'), 'aria-haspopup': 'menu' });
  const render = () => {
    label.textContent = model || defaultModel() || tr('Model');
    chip.title = tr('Model: {0}', [provider || defaultProvider(), label.textContent].filter(Boolean).join(' · '));
    chip.replaceChildren(icon('robot'), label, icon('chevron'));
  };
  chip.addEventListener('click', async () => {
    const search = h('input', { type: 'search', placeholder: tr('Find a model'), 'aria-label': tr('Find a model') });
    const list = h('div', { class: 'model-list' }, h('div', { class: 'popover-empty' }, tr('Loading the list...')));
    const place = openPopover(chip, [h('div', { class: 'popover-search' }, icon('search'), search), list], 'model-pop');
    search.focus();
    let groups;
    try { groups = await loadModels(); } catch (err) { list.replaceChildren(h('div', { class: 'popover-empty' }, err.message)); return; }
    const cur = { provider: provider || defaultProvider(), model: model || defaultModel() };
    const item = (g, id) => {
      const on = g.provider_id === cur.provider && id === cur.model;
      return h('button', {
        class: `menu-item${on ? ' selected' : ''}`,
        role: 'menuitemradio',
        'aria-checked': String(on),
        onclick: async () => {
          closeLayer();
          if (on) return;
          try { await onPick(g.provider_id, id); provider = g.provider_id; model = id; render(); } catch (err) { fail(err); }
        },
      }, h('span', { class: 'mi-model' }, modelLabel(id)), g.default && id === g.default_model ? h('span', { class: 'popover-sub' }, tr('default')) : null, on ? icon('check') : null);
    };
    const renderList = () => {
      const q = search.value.trim().toLowerCase();
      const shown = groups.map((g) => {
        const ids = g.models.map((m) => m.id);
        if (g.provider_id === cur.provider && cur.model && !ids.includes(cur.model)) ids.unshift(cur.model);
        const hit = !q || g.title.toLowerCase().includes(q) || g.provider_id.includes(q);
        return { g, ids: hit ? ids : ids.filter((id) => id.toLowerCase().includes(q)) };
      }).filter(({ g, ids }) => ids.length || (!q && g.error));
      list.replaceChildren(...(shown.length ? shown.flatMap(({ g, ids }) => [
        h('div', { class: 'menu-group' }, g.title, g.provider_id !== g.kind ? h('code', { class: 'provider-id' }, g.provider_id) : null),
        ...(ids.length ? ids.map((id) => item(g, id)) : [h('div', { class: 'popover-empty' }, tr('Error: {0}', g.error))]),
      ]) : [h('div', { class: 'popover-empty' }, tr('Nothing found'))]));
      place();
    };
    search.addEventListener('input', renderList);
    search.addEventListener('keydown', (e) => { if (e.key === 'Enter') list.querySelector('.menu-item')?.click(); });
    renderList();
    list.querySelector('.selected')?.scrollIntoView({ block: 'nearest' });
  });
  render();
  return {
    el: chip,
    value: () => ({ provider, model }),
    set(value) { ({ provider = '', model = '' } = value || {}); render(); },
  };
}

// Plan for one user turn. A paused turn keeps its folded plan; finished turns and new messages clear it.
function planStrip(items = []) {
  let current = items;
  let active = true;
  const list = h('div', { class: 'plan-list' });
  const count = h('span', { class: 'plan-count' });
  const el = h('div', { class: 'plan', hidden: true });
  const head = h('button', { class: 'plan-head', 'aria-expanded': 'true', onclick: () => {
    el.classList.toggle('folded');
    head.setAttribute('aria-expanded', String(!el.classList.contains('folded')));
  } }, icon('list'), h('span', { class: 'plan-title' }, tr('Plan')), count, icon('chevron'));
  el.append(head, list);
  const set = (next) => {
    current = next;
    if (!next.length) { el.hidden = true; list.replaceChildren(); count.textContent = ''; return; }
    const done = next.filter((i) => i.status === 'done').length;
    el.hidden = false;
    count.textContent = `${done}/${next.length}`;
    list.replaceChildren(...next.map((i) => h('div', { class: `plan-item ${i.status}` },
      i.status === 'done' ? icon('check') : i.status === 'in_progress' && active ? h('span', { class: 'spinner' }) : h('span', { class: 'plan-box' }),
      h('span', { class: 'plan-text' }, i.title))));
    const open = active && done !== next.length;
    el.classList.toggle('folded', !open);
    head.setAttribute('aria-expanded', String(open));
  };
  set(items);
  return { el, set, setStatus(status) {
    active = isRunning(status);
    set(!active && status !== 'PAUSED' ? [] : current);
  } };
}

// Sub-agents of a chat: a counter chip next to the model, a modal with each agent's assignment, activity and report.
function agentsPanel() {
  const agents = new Map();
  let list = null;
  const chip = h('button', { class: 'chip chip-agents', hidden: true, 'aria-haspopup': 'dialog' });
  const status = (a) => {
    const [label, cls] = statusOf(a.status);
    a.statusEl.className = `pill ${cls}`;
    a.statusEl.replaceChildren(...[isRunning(a.status) ? h('span', { class: 'dot accent live' }) : null, label].filter(Boolean));
  };
  const panel = (a) => {
    if (!a.panel) {
      a.statusEl = h('span', { class: 'pill' });
      a.panel = h('div', { class: 'agent' },
        h('div', { class: 'agent-head' }, icon('agents'), h('span', { class: 'agent-label' }, a.label), a.model ? h('span', { class: 'agent-model' }, a.model) : null, a.statusEl),
        h('details', { class: 'agent-task' }, h('summary', {}, tr('Assignment')), h('div', { class: 'agent-task-text' }, a.task)),
        a.log, a.result);
    }
    status(a);
    return a.panel;
  };
  const render = () => {
    const all = [...agents.values()];
    const running = all.filter((a) => isRunning(a.status)).length;
    chip.hidden = !all.length;
    chip.title = running ? tr('{0} agents, {1} running', all.length, running) : tp('{0} agent|{0} agents', all.length);
    chip.setAttribute('aria-label', chip.title);
    chip.replaceChildren(icon('agents'), h('span', { class: 'chip-label' }, String(all.length)), ...(running ? [h('span', { class: 'dot accent live' })] : []));
  };
  chip.addEventListener('click', () => {
    list = h('div', { class: 'agents-list' }, [...agents.values()].map(panel));
    openModal(h('div', { class: 'modal-head' }, h('h2', {}, tr('Sub-agents')), h('button', { class: 'icon-btn', 'aria-label': tr('Close'), onclick: closeLayer }, icon('x'))), list)
      .classList.add('modal-wide', 'modal-agents');
  });
  return {
    el: chip,
    get: (id) => agents.get(id),
    add(p) {
      const a = { id: p.agent_id, label: p.label, task: p.task, model: p.model, status: 'NEW', log: h('div', { class: 'agent-log' }), result: h('div', { class: 'agent-result prose' }) };
      agents.set(a.id, a);
      render();
      if (list?.isConnected) list.append(panel(a));
      return a;
    },
    setStatus(a, value) { a.status = value; render(); if (a.panel) status(a); },
  };
}

// Chip with the tokens this chat spent (its sub-agents included); the popover shows what fills the context and
// breaks the tokens down per model.
function fmtTokens(n) {
  const [value, unit] = n >= 1e6 ? [n / 1e6, 'M'] : n >= 1e3 ? [n / 1e3, 'K'] : [n || 0, ''];
  return `${value.toLocaleString(locale, { maximumFractionDigits: unit && value < 100 ? 1 : 0 })}${unit}`;
}

const CONTEXT_PARTS = {
  system: 'System prompt',
  tools: 'Tools',
  plugins: 'Plugins and MCP',
  instructions: 'User instructions',
  skills: 'Skills',
  memory: 'Memory',
  messages: 'Chat history',
  free: 'Free until compaction',
  reserve: 'Beyond compaction',
};

// Splits n cells between the values: every non-empty value gets at least one, the rest go by the largest remainder.
function waffleCells(values, n = 100) {
  const sum = values.reduce((a, b) => a + b, 0) || 1;
  const exact = values.map((v) => (v / sum) * n);
  const cells = exact.map((x) => (x > 0 ? Math.max(1, Math.floor(x)) : 0));
  const order = exact.map((_, i) => i).filter((i) => exact[i] > 0).sort((a, b) => (exact[b] % 1) - (exact[a] % 1));
  let left = n - cells.reduce((a, b) => a + b, 0);
  for (let k = 0; left > 0; k++, left--) cells[order[k % order.length]]++;
  for (; left < 0; left++) cells[cells.indexOf(Math.max(...cells))]--;
  return cells;
}

// What the chat's last model request was made of, against the model's window. The free part of the window is split
// at the size where the history gets compacted: the agent never fills the window beyond it.
function contextView(ctx) {
  const size = Math.max(ctx.window || ctx.limit, ctx.tokens) || 1;
  const compactAt = Math.min(ctx.limit, size);
  const parts = [
    ...ctx.parts.filter((p) => p.tokens > 0),
    { key: 'free', tokens: Math.max(0, compactAt - ctx.tokens) },
    { key: 'reserve', tokens: ctx.window ? Math.max(0, size - Math.max(compactAt, ctx.tokens)) : 0 },
  ].filter((p) => p.tokens > 0 || p.key === 'free');
  const over = ctx.window && ctx.tokens > ctx.window;
  const pct = (n) => {
    const v = (n / size) * 100;
    return v > 0 && v < 0.1 ? `<${(0.1).toLocaleString(locale)}%` : `${v.toLocaleString(locale, { maximumFractionDigits: v < 10 ? 1 : 0 })}%`;
  };
  const cells = waffleCells(parts.map((p) => p.tokens));
  const view = h('section', { class: 'ctx' },
    h('div', { class: 'ctx-head' }, h('strong', {}, tr('Context')),
      ctx.model ? h('span', { class: 'ctx-model', title: ctx.provider || '' }, ctx.model) : null),
    h('div', { class: 'ctx-total' },
      h('span', { class: 'ctx-used' }, `${ctx.estimated ? '≈' : ''}${fmtTokens(ctx.tokens)}`),
      h('span', { class: 'ctx-of' }, tr('of {0} tokens', fmtTokens(size))),
      h('span', { class: 'ctx-pct-total' }, pct(ctx.tokens))),
    h('div', { class: 'ctx-body' },
      h('div', { class: 'ctx-grid', 'aria-hidden': 'true' }, parts.map((p, i) =>
        Array.from({ length: cells[i] }, () => h('i', { class: 'ctx-cell', 'data-part': p.key })))),
      h('div', { class: 'ctx-legend' }, parts.map((p) =>
        h('div', { class: 'ctx-row', 'data-part': p.key, title: p.key === 'reserve' ? tr('The agent does not use this part of the window: the history is compacted before it') : p.tokens.toLocaleString(locale) },
          h('i', { class: 'ctx-swatch' }),
          h('span', { class: 'ctx-name' }, tr(CONTEXT_PARTS[p.key] || p.key), p.count ? h('span', { class: 'ctx-count' }, p.count) : null),
          h('span', { class: 'ctx-tokens' }, fmtTokens(p.tokens)),
          h('span', { class: 'ctx-pct' }, pct(p.tokens)))))),
    h('div', { class: 'ctx-foot' },
      h('span', {}, tr('History is compacted at {0}', fmtTokens(ctx.limit))),
      h('span', { class: over ? 'ctx-window over' : 'ctx-window' },
        !ctx.window ? tr('Model window is unknown')
          : over ? tr('Does not fit the model window of {0}', fmtTokens(ctx.window))
            : tr('Free in the window: {0}', fmtTokens(ctx.window - ctx.tokens)))));
  const focus = (key) => view.querySelectorAll('[data-part]').forEach((e) => e.classList.toggle('dim', Boolean(key) && e.dataset.part !== key));
  view.addEventListener('mouseover', (e) => focus(e.target.closest('[data-part]')?.dataset.part));
  view.addEventListener('mouseleave', () => focus(null));
  return view;
}

// Percent for the compact readouts: a non-empty share never rounds down to a flat 0%.
function fmtPct(v) {
  if (v > 0 && v < 1) return `<1%`;
  return `${Math.round(v).toLocaleString(locale)}%`;
}

// Ring gauge for the composer chip: how full the context window is, coloured as it fills up.
const RING_LEN = 2 * Math.PI * 8;

function ctxRing() {
  const el = h('span', {
    class: 'ctx-ring',
    html: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle class="ctx-ring-track" cx="10" cy="10" r="8"/><circle class="ctx-ring-fill" cx="10" cy="10" r="8"/></svg>',
  });
  const fill = el.querySelector('.ctx-ring-fill');
  return {
    el,
    // Returns the level so the chip label can follow the same colour.
    set(percent) {
      const v = Math.max(0, Math.min(100, percent || 0));
      const level = v >= 90 ? 'critical' : v >= 75 ? 'high' : v >= 50 ? 'mid' : 'low';
      fill.setAttribute('stroke-dasharray', `${(v / 100) * RING_LEN} ${RING_LEN}`);
      el.dataset.level = level;
      return level;
    },
  };
}

function usageMeter(taskId) {
  let data = null;
  let timer = null;
  let place = null;
  const chip = h('button', { class: 'chip chip-usage', hidden: true, 'aria-haspopup': 'dialog' });
  const ring = ctxRing();
  const body = h('div', { class: 'usage-body' });
  const cells = (u) => [u.calls, u.prompt_tokens, u.cached_tokens, u.cache_write_tokens, u.completion_tokens]
    .map((n, i) => h('td', { title: (n || 0).toLocaleString(locale) }, i ? fmtTokens(n) : String(n || 0)));
  const render = () => {
    const total = data.total.prompt_tokens + data.total.completion_tokens;
    chip.hidden = !data.total.calls;
    // The chip shows how full the context is; the token count stays in the tooltip and the popover.
    const ctx = data.context;
    const size = ctx ? Math.max(ctx.window || ctx.limit, ctx.tokens) || 0 : 0;
    const filled = size ? (ctx.tokens / size) * 100 : null;
    const spent = tr('Tokens in this chat: {0}', total.toLocaleString(locale));
    chip.title = filled == null ? spent : `${tr('Context filled: {0}', fmtPct(filled))} · ${spent}`;
    chip.setAttribute('aria-label', chip.title);
    if (filled == null) {
      delete chip.dataset.level;
      chip.replaceChildren(icon('gauge'), h('span', { class: 'chip-label' }, fmtTokens(total)));
    } else {
      chip.dataset.level = ring.set(filled);
      chip.replaceChildren(ring.el, h('span', { class: 'chip-label' }, fmtPct(filled)));
    }
    if (!body.isConnected) return;
    body.replaceChildren(
      ...(data.context ? [contextView(data.context)] : []),
      h('div', { class: 'usage-head' }, h('strong', {}, tr('Tokens in this chat')),
        data.agents ? h('span', { class: 'popover-sub' }, tp('with {0} sub-agent|with {0} sub-agents', data.agents)) : null),
      h('div', { class: 'usage-scroll' }, h('table', { class: 'usage-table' },
        h('thead', {}, h('tr', {}, [tr('Model'), tr('Calls'), tr('Input'), tr('From cache'), tr('To cache'), tr('Output')].map((x) => h('th', {}, x)))),
        h('tbody', {}, data.models.map((m) => h('tr', {},
          h('td', { title: m.model || '' }, m.model || '—', h('span', { class: 'usage-provider' }, m.provider || '')), cells(m)))),
        data.models.length > 1 ? h('tfoot', {}, h('tr', {}, h('td', {}, tr('Total')), cells(data.total))) : null)));
    place?.();
  };
  const refresh = async () => {
    try { data = await get(`/v1/tasks/${taskId}/usage`); } catch { return; }
    render();
  };
  chip.addEventListener('click', () => {
    place = openPopover(chip, body, 'usage-pop', 'right');
    render();
    refresh();
  });
  viewCleanups.push(() => clearTimeout(timer));
  return {
    el: chip,
    refresh,
    later() { clearTimeout(timer); timer = setTimeout(refresh, 800); },
  };
}

// ---------- new chat ----------

async function viewNewChat(projectId = null) {
  const shell = ensureAppShell();
  shell.setActive(null);
  let project = projectId ? state.projects.find((p) => p.id === projectId) : null;
  // The sidebar copy can lag behind the project page by a poll: ask Core before sending the user back.
  if (projectId && project?.status !== 'ready') {
    try { project = rememberProject(await get(`/v1/projects/${projectId}`)); } catch (err) { fail(err); go(err.status === 404 || !project ? '#/' : `#/projects/${projectId}`); return; }
    shell.renderSessions();
  }
  if (project && project.status !== 'ready') { go(`#/projects/${project.id}`); return; }
  if (project?.kind === 'repo') {
    history.replaceState(null, '', `#/projects/${project.id}`);
    await viewProject(project.id);
    openProjectChat(project);
    return;
  }
  const online = devices().filter((t) => t.status === 'online');
  // A project chat runs on the project's own device.
  const source = () => devices().find((t) => t.id === project.source_target_id);
  const offlineText = () => (project.source_name
    ? tr('“{0}” is offline. Turn it on to start a chat in this project.', project.source_name)
    : tr('The project\'s device is offline. Turn it on to start a chat in this project.'));
  let selected = project
    ? source() || null
    : online.find((t) => t.id === localStorageGet('target')) || online.find(isThisDevice) || online[0] || null;

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
    }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), t.name, h('span', { class: 'popover-sub' }, isThisDevice(t) ? tr('this device') : t.status === 'online' ? t.platform.split('-')[0] : tr('offline'))));
    items.push(h('div', { class: 'menu-sep' }), h('button', { class: 'menu-item', onclick: () => { closeLayer(); openPairing(); } }, icon('link'), tr('Pair a new device')));
    openPopover(targetChip, items);
  }
  renderChip();

  const hint = h('p', { class: 'welcome-hint' });
  if (!state.system) { try { state.system = await get('/v1/system'); } catch { /* shown without version info */ } }
  const banner = h('div', { class: 'welcome-banner' }, outdatedBanner(selected) || '');
  const hintText = (mode = modeCtl.effective()) => {
    if (project && source()?.status !== 'online') return offlineText();
    if (!project && !online.length) return tr('All devices are currently offline. Run mensarium client run on the machine you need.');
    return mode === 'full'
      ? tr('Full access: the agent runs commands and changes files on its own, without asking.')
      : tr('The agent will explore the project on its own and ask permission before running commands or changing files.');
  };
  const modeCtl = modeSwitch(localStorageGet('mode') === 'full' ? 'full' : 'ask', {
    target: () => selected,
    onPick: async (value) => { localStorageSet('mode', value); hint.textContent = hintText(value); },
  });
  hint.textContent = hintText();
  if (project) {
    // The source can come online or drop while the page is open; the shell poll refreshes state.targets.
    const iv = setInterval(() => { selected = source() || selected; hint.textContent = hintText(); }, 4000);
    viewCleanups.push(() => clearInterval(iv));
  }

  // The model picked for a new chat becomes the default for the next ones.
  const modelCtl = modelSwitch(null, { onPick: async (provider, model) => {
    await api('/v1/system/model', { method: 'PUT', body: JSON.stringify({ provider, model }) });
    if (state.system) state.system.provider = { ...state.system.provider, name: provider, model };
    state.models = null;
  } });
  const projectChip = project
    ? h('a', { class: 'chip', href: `#/projects/${project.id}`, title: `${project.source_name || ''}:${project.source_path}` }, icon(KIND_ICON[project.kind] || 'folder'), h('span', { class: 'chip-label' }, project.name))
    : null;

  const c = composer({
    placeholder: tr('Describe the task for the agent'),
    chips: [project ? projectChip : targetChip, h('span', { class: 'divider' }), modeCtl.el, modelCtl.el],
    onSend: async (text, attachments) => {
      if (project && source()?.status !== 'online') throw new Error(offlineText());
      if (!selected) throw new Error(tr('Select the device the agent will work on'));
      const task = await post('/v1/tasks', { target_id: selected.id, input: text, attachments, mode: modeCtl.effective(), model: modelCtl.value().model || undefined, provider: modelCtl.value().provider || undefined, project_id: project?.id });
      state.tasks.unshift(task);
      go(`#/chat/${task.id}`);
    },
  });

  const content = devices().length
    ? [
      h('div', { class: 'welcome-hero' }, orb('lg'), h('h1', {}, project ? tr('What needs to be done in “{0}”?', project.name) : tr('What needs to be done?'))),
      project ? null : h('div', { class: 'templates' }, TEMPLATES.map(([ic, label, text]) => h('button', { class: 'template', onclick: () => c.setText(text) }, icon(ic), label))),
      c.el,
      hint,
      banner,
    ]
    : h('div', { class: 'welcome-empty' },
      h('div', { class: 'welcome-hero' }, orb('lg'), h('h1', {}, tr('Connect a device'))),
      h('p', {}, tr('The agent works on your machines through Mensarium clients. Pairing takes a minute.')),
      h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), tr('Pair a device')));

  shell.panel.replaceChildren(topbar(shell, [], null, { newChat: false }), h('div', { class: 'welcome' }, content));
  if (devices().length) c.textarea.focus();
}

// A device whose agent is older than Core and misses base tools: offer the update right in the chat.
function outdatedBanner(t) {
  const s = state.system;
  const caps = t?.capabilities || {};
  if (!t || !s || !t.agent_version || t.agent_version === s.version || !(caps.missing_tools || []).length) return null;
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
  const changes = task.project_id && task.branch && !task.parent_id ? changesPanel(taskId) : null;
  const inRepo = state.projects.find((p) => p.id === task.project_id)?.kind === 'repo';
  const branchPill = !inRepo ? null : task.branch
    ? h('span', { class: 'pill tag branch-pill', title: baseName(task.base_ref) ? `${task.branch} · ${tr('from {0}', task.base_ref)}` : task.branch }, icon('git'), h('span', {}, task.branch))
    : h('span', { class: 'pill tag branch-pill', title: tr('No workspace: the agent works right in the project folder') }, icon('folder'), h('span', {}, tr('project folder')));

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
  const modelCtl = modelSwitch({ provider: task.provider, model: task.model }, {
    onPick: (provider, model) => post(`/v1/tasks/${taskId}/model`, { provider, model }),
  });
  const plan = planStrip(task.plan || []);
  const agents = agentsPanel();
  const usage = usageMeter(taskId);
  const c = composer({
    placeholder: task.input ? tr('Reply to the agent') : tr('Describe the task for the agent'),
    chips: [modeCtl.el, modelCtl.el, agents.el],
    tail: usage.el,
    above: plan.el,
    onSend: (text, attachments) => post(`/v1/tasks/${taskId}/messages`, { input: text, attachments }),
    onStop: () => act('pause'),
    onResume: () => act('resume'),
  });

  if (!state.system) { try { state.system = await get('/v1/system'); } catch { /* shown without version info */ } }
  const banner = outdatedBanner(target());
  const project = task.project_id ? state.projects.find((p) => p.id === task.project_id) : null;
  const crumb = project
    ? h('a', { class: 'crumb-device', href: `#/projects/${project.id}` }, icon(KIND_ICON[project.kind] || 'folder'), project.name, h('span', { class: 'sep' }, '/'))
    : h('span', { class: 'crumb-device' }, icon('laptop'), task.target_name || tr('device'), h('span', { class: 'sep' }, '/'));
  const chatBody = [thread, h('div', { class: 'thread-banner' }, banner || ''), c.el];
  shell.panel.replaceChildren(
    topbar(shell,
      [crumb, h('span', { class: 'current', title: task.input }, taskTitle(task))],
      [branchPill, changes?.btn, btnDelete].filter(Boolean)),
    ...(changes ? [h('div', { class: 'chat-split' }, h('div', { class: 'chat-main' }, chatBody), changes.el)] : chatBody),
  );

  function setStatus(status) {
    task.status = status;
    plan.setStatus(status);
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
  const shot = (id, cls) => {
    const url = `/v1/artifacts/${id}`;
    return h('a', { class: cls, href: url, target: '_blank', rel: 'noopener', title: tr('Open the screenshot') }, h('img', { src: url, alt: tr('Screenshot from the device') }));
  };

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
      case 'screen.capture': return tr('Looking at the screen');
      case 'screen.windows': return tr('Listing windows');
      case 'input.mouse': return tr('Mouse: {0} at {1},{2}', a.action, a.x, a.y);
      case 'input.type': return tr('Typing text');
      case 'input.key': return tr('Pressing {0}', a.keys);
      case 'app.open': return tr('Opening {0}', clip(a.target, 40));
      case 'system.volume': return tr('Volume: {0}', a.action);
      case 'skills.read': return tr('Loading skill {0}', a.path ? `${a.name} ${a.path}` : a.name);
      case 'memory.search': return tr('Searching memory for “{0}”', clip(a.query, 40));
      case 'memory.read': return tr('Reading note {0}', a.title);
      case 'memory.save': return tr('Remembering {0}', a.title);
      case 'web.search': return tr('Searching the web for “{0}”', clip(a.query, 40));
      case 'web.fetch': return tr('Reading {0}', (() => { try { return new URL(a.url).host; } catch { return clip(a.url, 40); } })());
      case 'plan.update': return tr('Updating the plan');
      case 'agent.spawn': return tr('Starting agent “{0}”', a.label);
      case 'agent.wait': return tr('Waiting for agents');
      default:
        if (tool.startsWith('mcp.')) { const [, server, name] = tool.split('.'); return tr('Calling {0}: {1}', server, name); }
        return a.command ? tr('Running {0}', clip(a.command, 56)) : tool;
    }
  }

  function toolCard(id, tool, display, into = logAdd) {
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
    into(card);
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
    if (p.image_artifact_id && !e.card.querySelector('.tool-shot')) e.card.insertBefore(shot(p.image_artifact_id, 'tool-shot'), e.noteEl);
    if (p.truncated || p.artifact_id) {
      e.noteEl.replaceChildren(p.truncated ? tr('Output truncated. ') : '', p.artifact_id ? h('a', { href: `/v1/artifacts/${p.artifact_id}`, target: '_blank', rel: 'noopener' }, tr('Full output')) : '');
    }
  }

  function approvalCard(p, agent = null) {
    const tc = p.tool_call || {};
    const args = tc.arguments || {};
    const [riskLabel, riskKind] = RISK[tc.risk] || [tc.risk, ''];
    const timer = h('span', { class: 'approval-timer' });
    const approve = h('button', { class: 'btn btn-primary' }, icon('check'), tr('Run once'));
    const reject = h('button', { class: 'btn' }, tr('Reject'));
    const actions = h('div', { class: 'approval-actions' }, approve, reject);
    let confirmBox = null;
    const card = h('div', { class: `approval${tc.risk === 'destructive' ? ' risk-destructive' : ''}`, role: 'group', 'aria-label': tr('Approval request') },
      h('div', { class: 'approval-top' }, h('span', { class: 'approval-title' }, tr('Your decision is needed')), agent ? h('span', { class: 'pill accent' }, icon('agents'), agent.label) : null, h('span', { class: `pill ${riskKind}` }, riskLabel), timer),
      h('pre', { class: 'approval-cmd' }, args.command ? `$ ${args.command}` : short(tc.display)),
      h('dl', { class: 'approval-meta' },
        tc.tool !== 'shell.exec' ? [h('dt', {}, tr('Tool')), h('dd', {}, tc.tool)] : null,
        h('dt', {}, tr('Device')), h('dd', {}, tc.target_name || ''),
        args.cwd ? [h('dt', {}, tr('Folder')), h('dd', { title: args.cwd }, short(args.cwd))] : null,
        args.timeout_s ? [h('dt', {}, tr('Limit')), h('dd', {}, tr('{0} s', args.timeout_s))] : null,
      ),
      args.stdin ? [h('div', { class: 'approval-sub' }, tr('Input data')), h('pre', { class: 'approval-cmd approval-stdin' }, args.stdin)] : null,
      args.prompt ? [h('div', { class: 'approval-sub' }, tr('Prompt')), h('pre', { class: 'approval-cmd approval-stdin' }, args.prompt)] : null,
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
    approvals.set(p.approval_id, { card, wrap, actions, iv, timer, confirmBox, agent });
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
    if (e.agent) { e.agent.log.append(e.card); e.wrap.remove(); } else if (work) { logAdd(e.card); e.wrap.remove(); }
  }

  // Events of a sub-agent arrive mirrored into this chat's stream; they fill the agent's own log in the modal,
  // while its approvals and a rolling line of its actions stay visible in the thread.
  function handleAgent(id, event, p, ev, live) {
    const a = agents.get(id);
    if (!a) return;
    const active = isRunning(task.status);
    const into = (node) => a.log.append(node);
    const anote = (ic, text, cls = '') => into(h('div', { class: `note ${cls}` }, icon(ic), h('span', {}, text)));
    switch (event) {
      case 'task.status':
        agents.setStatus(a, p.status);
        if (['PAUSED', 'CANCELED', 'FAILED', 'FAILED_RECOVERABLE'].includes(p.status)) anote('alert', `${statusOf(p.status)[0]}${p.reason ? `: ${reasonText(p.reason)}` : ''}`, p.status === 'FAILED' || p.status === 'FAILED_RECOVERABLE' ? 'error' : '');
        break;
      case 'llm.response':
        if (p.text && p.tool_call) into(h('div', { class: 'work-thought prose', html: markdown(p.text) }));
        break;
      case 'tool_call.denied':
        anote('ban', tr('Policy didn\'t allow {0}: {1}', p.tool, policyText(p.reason)));
        break;
      case 'tool_call.pending_approval':
        if (active) { stamp(ev); say(tr('Agent “{0}” is waiting for your decision', a.label), live); }
        approvalCard(p, a);
        break;
      case 'approval.decided':
        approvalDecided(p);
        break;
      case 'tool_call.executing':
        if (active) { stamp(ev); say(`${a.label}: ${actionText(p.tool, p.arguments, p.display)}`, live); }
        toolCard(p.tool_call_id, p.tool, p.display, into);
        break;
      case 'tool_call.result':
        toolResult(p);
        if (live) changes?.later();
        break;
      case 'task.final':
        a.result.replaceChildren(h('div', { class: 'agent-result-title' }, tr('Report')), h('div', { class: 'prose', html: markdown(p.text) }), ...(p.image_artifact_id ? [shot(p.image_artifact_id, 'msg-shot')] : []));
        break;
      case 'task.error':
        anote('alert', p.message, 'error');
        break;
      default:
    }
  }

  // The answer the model is writing for the llm.request with seq `draftFor`, from live llm.delta events that are
  // never stored; the stored llm.response or task.final settles it in place.
  let draftFor = null;
  let draft = null;
  function draftDelta(p) {
    if (p.request !== draftFor) return;
    const d = draft || (draft = { text: '', node: null, body: null });
    if (p.offset > d.text.length) return;
    d.text += p.text.slice(d.text.length - p.offset);
    if (!d.node) {
      if (!d.text.trim()) return;
      finishWork();
      d.body = h('div', { class: 'prose' });
      d.node = agentMsg(d.body, true);
    }
    d.body.innerHTML = markdown(d.text);
    if (stick) thread.scrollTop = thread.scrollHeight;
  }
  function settleDraft(body) {
    const d = draft;
    draft = null;
    if (!d?.node) return false;
    d.node.replaceChildren(orb(''), h('div', { class: 'msg-body' }, body));
    return true;
  }
  function dropDraft() {
    draft?.node?.remove();
    draft = null;
  }

  function handle({ event, seq, payload: p, created_at: createdAt }, live) {
    const ev = { created_at: createdAt };
    switch (event) {
      case 'user.message':
        plan.set([]); // Also clears stale plans while replaying events from older server versions.
        finishWork();
        lastAgent = false;
        add(h('div', { class: 'msg-user' }, h('div', { class: 'bubble-user' }, p.text ? h('div', { class: 'bubble-text' }, p.text) : null, attachmentList(p.attachments))));
        break;
      case 'task.status':
        setStatus(p.status);
        if (!isRunning(p.status)) finishWork();
        if (!isRunning(p.status) && p.status !== 'SUCCEEDED') dropDraft();
        if (['PAUSED', 'CANCELED', 'FAILED', 'FAILED_RECOVERABLE'].includes(p.status)) {
          note(p.status === 'PAUSED' ? 'pause' : 'alert', `${statusOf(p.status)[0]}${p.reason ? `: ${reasonText(p.reason)}` : ''}`, p.status === 'PAUSED' || p.status === 'CANCELED' ? '' : 'error');
        }
        break;
      case 'task.mode':
        modeCtl.set(p.mode);
        note(MODES[p.mode]?.icon || 'shield', tr('Mode: {0}', (MODES[p.mode]?.label || p.mode).toLowerCase()));
        break;
      case 'task.model':
        modelCtl.set(p);
        note('robot', tr('Model: {0}', [p.provider, p.model].filter(Boolean).join(' · ')));
        break;
      case 'task.plan':
        plan.set(p.items || []);
        break;
      case 'task.project':
        if (live) changes?.later(true);
        if (p.kind === 'revert') note('refresh', tr('Changes to {0} reverted', p.path));
        else if (p.kind === 'checkout' && p.error) note('alert', tr('Could not prepare the working copy: {0}', reasonText(p.error)), 'error');
        else if (p.kind === 'checkout') note(KIND_ICON[project?.kind] || 'folder', project?.kind === 'repo' && p.branch ? [tr('Working copy ready'), p.branch, p.base && p.base !== 'snapshot' ? tr('from {0}', p.base) : null].filter(Boolean).join(' · ') : tr('Working copy ready'));
        else if (p.error != null) note('alert', tr('Could not save this turn: {0}', p.error || tr('error')), 'error');
        else if (p.changed) note('file', tp('{0} file changed|{0} files changed', p.changed));
        break;
      case 'agent.spawned':
        stamp(ev);
        agents.add(p);
        logAdd(h('div', { class: 'note' }, icon('agents'), h('span', {}, tr('Started agent “{0}”', p.label))));
        break;
      case 'agent.event':
        handleAgent(p.agent_id, p.event, p.payload || {}, ev, live);
        if (live && p.event === 'llm.response') usage.later();
        break;
      case 'llm.request':
        dropDraft();
        draftFor = seq;
        stamp(ev);
        if (!work?.actions) say(tr('Thinking'), live);
        break;
      case 'llm.delta':
        draftDelta(p);
        break;
      case 'llm.response':
        draftFor = null;
        if (p.text && p.tool_call) {
          const body = h('div', { class: 'prose', html: markdown(p.text) });
          if (!settleDraft(body)) {
            finishWork();
            agentMsg(body);
          }
        } else if (p.tool_call) dropDraft();
        stamp(ev);
        if (live) usage.later();
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
        if (live) changes?.later();
        break;
      case 'task.final': {
        finishWork();
        const body = [h('div', { class: 'prose', html: markdown(p.text) }), p.image_artifact_id ? shot(p.image_artifact_id, 'msg-shot') : null];
        if (!settleDraft(body)) agentMsg(body);
        break;
      }
      case 'task.error':
        note('alert', p.message, 'error');
        break;
      case 'task.note':
        note('alert', p.message);
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
      if (ev.seq == null) { handle(ev, true); return; }
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
  usage.refresh();
  viewCleanups.push(() => { closed = true; if (es) es.close(); });
  if (!c.textarea.disabled) c.textarea.focus();
}

// ---------- settings ----------

const SETTINGS = [
  ['overview', 'pulse', tr('Overview')],
  ['providers', 'robot', tr('Providers')],
  ['devices', 'laptop', tr('Devices')],
  ['channels', 'send', tr('Channels')],
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

const field = (label, control, hint) => h('label', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, h('span', {}, label)), control, hint ? h('div', { class: 'row-desc' }, hint) : null);

const copyBtn = (text) => h('button', { class: 'icon-btn', 'aria-label': tr('Copy'), title: tr('Copy'), onclick: (e) => copy(text, e.currentTarget) }, icon('copy'));
const cmdValue = (cmd) => [h('code', {}, cmd), copyBtn(cmd)];

async function viewSettings(key) {
  if (key === 'instructions') { go('#/settings/memory'); return; }
  const shell = ensureSettingsShell();
  shell.setActive();
  const views = { overview: settingsOverview, providers: settingsProviders, model: settingsProviders, devices: settingsDevices, channels: settingsChannels, memory: settingsMemory, skills: settingsSkills, plugins: settingsPlugins, marketplace: settingsPlugins, profiles: settingsProfiles, audit: settingsAudit };
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
  await loadLimits();
  const limitsBox = h('div', { class: 'limits-list' });
  const renderLimits = () => limitsBox.replaceChildren(...limitsBody());
  renderLimits();
  state.limitsRender = () => { if (limitsBox.isConnected) renderLimits(); };
  page(shell, tr('Overview'), tr('Where the main agent is reachable, and how to check that devices are talking to it.'), [themeSelect(), languageSelect(), logout],
    h('div', { class: 'hero' }, orb('md'), h('div', { class: 'hero-text' }, h('h2', {}, 'Mensarium Core'), h('p', {}, tr('Version {0}', s.version))), coreUpdate),
    section(tr('Usage limits'), tr('How much of each connected provider\'s quota is used. The default provider, the one last picked for a new chat, warns above the chat input from {0}%.', Math.round((state.limits?.threshold || 0.75) * 100)), limitsBox),
    section(tr('Connection'), null, h('div', { class: 'rows' },
      row(tr('Core address'), tr('Other devices connect to it; the web UI opens here and on their gateways.'), cmdValue(url), true),
      row(tr('Key fingerprint'), tr('Check it against what the installer showed on the device during pairing.'), s.core_key_fingerprint, true),
    )),
    section(tr('Maintenance'), tr('Commands run on the Core server.'), h('div', { class: 'rows' },
      row(tr('Update Mensarium'), tr('Downloads the latest version and restarts the service.'), cmdValue('mensarium update'), true),
      row(tr('Login token'), tr('Shows the token for this web UI; run it on the machine that serves it.'), cmdValue(state.gateway?.core ? 'mensarium core token' : 'mensarium client gateway token'), true),
    )),
    section(tr('Backup'), tr('An archive with the database, keys, secrets, and settings, encrypted with a password you set. The same archive is used to move Core to another server.'), h('div', { class: 'rows' },
      row(tr('Create a backup'), tr('Saves the archive to the current folder.'), cmdValue('mensarium core backup -o mensarium.pab'), true),
      row(tr('Restore from a backup'), tr('Stops Core, replaces its data with the archive\'s contents, and starts it again. The previous data stays alongside it, in the core.before-restore-… folder.'), cmdValue('mensarium core restore mensarium.pab'), true),
    )),
  );
}

async function settingsProviders(shell) {
  const [data, sys] = await Promise.all([get('/v1/providers'), get('/v1/system')]);
  state.system = sys;
  const health = sys.provider?.health || {};
  const kinds = Object.fromEntries(data.kinds.map((k) => [k.kind, k]));

  const reload = () => settingsProviders(shell).catch(fail);
  const remove = async (x) => {
    if (!await confirmDialog({ title: tr('Remove “{0}”?', x.title), text: tr('Its settings and saved key are deleted from Core.'), action: tr('Remove'), danger: true })) return;
    try { await del(`/v1/providers/${x.id}`); closeLayer(); toast(tr('Removed')); reload(); } catch (err) { fail(err); }
  };

  function editor(x) {
    const adding = !x;
    const kindSel = h('select', { 'aria-label': tr('Type') }, data.kinds.map((k) => h('option', { value: k.kind, selected: x ? k.kind === x.kind : k.kind === 'ollama_local' }, k.title)));
    const taken = new Set(data.providers.map((y) => y.id));
    const freeId = (kind) => { let id = kind; for (let i = 2; taken.has(id); i++) id = `${kind}-${i}`; return id; };
    const id = h('input', { type: 'text', value: x ? x.id : freeId(kindSel.value), disabled: !adding, 'aria-label': tr('Name in the config') });
    const base = h('input', { type: 'text', value: x ? x.base_url : kinds[kindSel.value].base_url, 'aria-label': tr('API address') });
    const isCli = () => kinds[kindSel.value].transport === 'cli';
    const baseLabel = h('span', {}, tr('API address'));
    const key = h('input', { type: 'password', autocomplete: 'off', placeholder: x?.has_key ? tr('Saved. Type to replace') : '', 'aria-label': tr('API key') });
    const model = h('select', { 'aria-label': tr('Default model') });
    const vision = h('select', { 'aria-label': tr('Model for images') });
    const timeout = h('input', { type: 'number', value: x ? x.timeout_s : 90, min: 5, max: 600, 'aria-label': tr('Timeout, s') });
    const retries = h('input', { type: 'number', value: x ? x.max_retries : 2, min: 0, max: 5, 'aria-label': tr('Retries') });
    const keyHint = h('div', { class: 'row-desc' });
    const statusDot = h('span', { class: 'dot' });
    const statusText = h('span', {}, tr('Check the connection to load the models.'));
    const status = h('div', { class: 'plugin-status' }, statusDot, statusText);
    const setStatus = (kind, text) => { status.className = `plugin-status ${kind}`; statusDot.className = `dot ${{ ok: 'ok', error: 'danger', busy: 'accent live' }[kind] || ''}`; statusText.textContent = text; };
    // The lists hold what the provider returned plus the current values, so a saved model stays selectable before the check.
    const options = (ids, current) => [...new Set([current, ...ids].filter(Boolean))].map((m) => h('option', { value: m, selected: m === current }, modelLabel(m)));
    const fillModels = (ids, current, currentVision) => {
      model.replaceChildren(...options(ids, current));
      vision.replaceChildren(h('option', { value: '', selected: !currentVision }, tr('Same as the default model')), ...options(ids, currentVision));
    };
    fillModels([], x ? x.default_model : kinds[kindSel.value].default_model, x ? (x.vision_model || '') : (kinds[kindSel.value].vision_model || ''));
    let touchedBase = !!x;
    base.addEventListener('input', () => { touchedBase = true; });
    const syncKind = () => {
      const k = kinds[kindSel.value];
      if (!touchedBase) base.value = k.base_url;
      if (adding) { id.value = freeId(k.kind); fillModels([], k.default_model, k.vision_model || ''); }
      keyHint.replaceChildren(...(k.needs_key ? [tr('Required. '), k.key_url ? linkify(k.key_url) : ''] : [tr('Only if the server asks for one.')]).flat());
      baseLabel.textContent = isCli() ? tr('Command on the Core host') : tr('API address');
      keyField.hidden = isCli();
      visionField.hidden = isCli();
      statusText.textContent = isCli() ? tr('Check that the command works and is logged in.') : tr('Check the connection to load the models.');
    };
    kindSel.addEventListener('change', syncKind);
    const runCheck = async () => {
      check.disabled = true;
      setStatus('busy', tr('Connecting...'));
      try {
        const r = await post('/v1/providers/test', { kind: kindSel.value, base_url: base.value.trim(), api_key: key.value || null, id: x?.id || null });
        if (r.ok) {
          const preferred = kinds[kindSel.value].default_model;
          const pick = r.models.includes(model.value) ? model.value : r.models.includes(preferred) ? preferred : r.models[0] || model.value;
          fillModels(r.models, pick, r.models.includes(vision.value) ? vision.value : '');
          setStatus('ok', tr('Available, {0} models', r.models.length));
        } else {
          setStatus('error', tr('Error: {0}', r.error));
        }
      } catch (err) { fail(err); } finally { check.disabled = false; }
    };
    const check = h('button', { class: 'btn btn-sm', onclick: (e) => { e.preventDefault(); runCheck(); } }, icon('refresh'), tr('Check connection'));
    status.append(h('span', { class: 'spacer' }), check);
    const save = h('button', { class: 'btn btn-primary' }, tr('Save'));
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        await api(`/v1/providers/${encodeURIComponent(id.value.trim())}`, { method: 'PUT', body: JSON.stringify({
          kind: kindSel.value, base_url: base.value.trim(), default_model: model.value.trim(), api_key: key.value || null,
          timeout_s: Number(timeout.value) || 90, max_retries: Number(retries.value) || 0, vision_model: vision.value.trim() || null,
        }) });
        state.models = null;
        closeLayer();
        toast(tr('Saved'));
        reload();
      } catch (err) { fail(err); } finally { save.disabled = false; }
    });
    const field = (label, control, hint) => h('label', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, typeof label === 'string' ? h('span', {}, label) : label), control, hint || null);
    const keyField = field(tr('API key'), key, keyHint);
    const visionField = field(tr('Model for images'), vision, h('div', { class: 'row-desc' }, tr('Used automatically on steps where the agent looks at a screenshot; leave empty if the default model accepts images.')));
    syncKind();
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, adding ? tr('Add a provider') : x.title), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('div', { class: 'plugin-form' },
        h('div', { class: 'plugin-grid' }, field(tr('Type'), kindSel), field(tr('Name in the config'), id)),
        field(baseLabel, base),
        keyField,
        status,
        field(tr('Default model'), model, h('div', { class: 'row-desc' }, tr('Used when this provider is picked without a model. The model list in a chat shows every provider\'s models.'))),
        visionField,
        h('div', { class: 'plugin-grid' }, field(tr('Timeout, s'), timeout), field(tr('Retries'), retries))),
      h('div', { class: 'modal-actions' },
        x ? h('button', { class: 'btn btn-danger', onclick: () => remove(x) }, tr('Remove')) : null,
        h('span', { class: 'spacer' }),
        h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
    ).classList.add('modal-wide');
    if (x && (x.has_key || !kinds[x.kind].needs_key)) runCheck();
  }

  const connect = async (d, btn) => {
    btn.disabled = true;
    try {
      const pid = data.providers.some((p) => p.id === d.kind) ? `${d.kind}-2` : d.kind;
      await api(`/v1/providers/${pid}`, { method: 'PUT', body: JSON.stringify({ kind: d.kind, base_url: d.path, default_model: d.default_model, api_key: null, timeout_s: 180, max_retries: 1, vision_model: null }) });
      state.models = null;
      toast(tr('Connected: {0}', d.title));
      reload();
    } catch (err) { fail(err); btn.disabled = false; }
  };
  const detectedCard = (d) => {
    const btn = h('button', { class: 'btn btn-sm btn-primary', onclick: (e) => { e.stopPropagation(); connect(d, btn); } }, tr('Connect'));
    return h('div', { class: 'hero provider-hero provider-card' },
      h('span', { class: 'market-icon' }, icon('robot')),
      h('div', { class: 'hero-text' },
        h('h2', {}, d.title, d.version ? h('code', { class: 'provider-id' }, d.version) : null),
        h('p', {}, [d.path, d.logged_in === true ? tr('logged in') + (d.account ? ` (${d.account})` : '') : d.logged_in === false ? tr('not logged in: log in on the Core host first') : null, d.default_model ? tr('model {0}', d.default_model) : null].filter(Boolean).join(' · '))),
      btn);
  };

  const card = (x) => h('div', {
    class: 'hero provider-hero provider-card', role: 'button', tabindex: '0', onclick: () => editor(x),
    onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); editor(x); } },
  },
  h('span', { class: 'market-icon' }, icon('robot')),
  h('div', { class: 'hero-text' },
    h('h2', {}, x.title, x.id !== x.kind ? h('code', { class: 'provider-id' }, x.id) : null),
    h('p', {}, [x.base_url, x.default_model, x.vision_model ? tr('images: {0}', x.vision_model) : null, x.needs_key || x.has_key ? (x.has_key ? tr('key saved') : tr('no key')) : null].filter(Boolean).join(' · '))),
  icon('chevron'));

  page(shell, tr('Providers'), tr('Where the agent thinks: LLM providers and their models. Keys are stored only on the Core server; the model is picked in the chat from one list grouped by provider.'),
    h('button', { class: 'btn btn-primary', onclick: () => editor(null) }, icon('plus'), tr('Add a provider')),
    h('div', { class: 'provider-cards' }, data.providers.length ? data.providers.map(card) : h('div', { class: 'empty rows' }, tr('No providers yet.'))),
    health.ok ? null : h('p', { class: 'market-note' }, health.detail || ''),
    data.detected?.length ? section(tr('Found on the Core host'), tr('Local agent CLIs that can think for Mensarium through your subscription. Their own tools are switched off; only the answer is used.'),
      h('div', { class: 'provider-cards' }, data.detected.map(detectedCard))) : null,
  );
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
  'screen.capture': [tr('Screenshots'), tr('Shows the agent the screen as an image, with approval.')],
  'screen.windows': [tr('Windows'), tr('Lists open apps and windows.')],
  'input.mouse': [tr('Mouse'), tr('Moves and clicks at screen coordinates, with approval.')],
  'input.type': [tr('Keyboard: text'), tr('Types text into the focused window, with approval.')],
  'input.key': [tr('Keyboard: keys'), tr('Presses keys and shortcuts, with approval.')],
  'app.open': [tr('Open apps'), tr('Opens applications, files and links, with approval.')],
  'system.volume': [tr('Volume'), tr('Reads or changes the output volume, with approval.')],
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
      desktopStatus(t),
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

  function desktopStatus(t) {
    const d = (t.capabilities || {}).desktop || {};
    if (!('screen' in d) && !('input' in d)) return null;
    const mac = (t.platform || '').startsWith('darwin');
    const item = (label, value) => h('span', { class: `pill ${value === true ? 'ok' : value === false ? 'warn' : ''}` }, `${label}: ${value === true ? tr('allowed') : value === false ? tr('not allowed') : tr('unknown')}`);
    const hint = (d.screen === false || d.input === false)
      ? (mac ? tr('Allow Screen Recording and Accessibility for Mensarium in System Settings, Privacy & Security, or run mensarium client permissions on the device.') : tr('Install xdotool, wmctrl and scrot (or grim) on the device.'))
      : '';
    return h('div', { class: 'device-desktop' }, h('span', { class: 'device-text' }, tr('Screen and input:')), item(tr('screen'), d.screen), item(tr('input'), d.input), hint ? h('span', { class: 'row-desc' }, hint) : null);
  }

  function agentControl(t) {
    const caps = t.capabilities || {};
    const outdated = t.agent_version && s.version && t.agent_version !== s.version;
    const pending = state.updates.get(t.id);
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
            t.core_host ? h('span', { class: 'pill accent', title: tr('The machine the Core runs on: the agent works here through the Core itself.') }, tr('Core')) : null,
            isThisDevice(t) && !t.core_host ? h('span', { class: 'pill', title: tr('The machine this web UI runs on.') }, tr('This device')) : null,
            t.gateway_online && !isThisDevice(t) ? h('span', { class: 'pill', title: tr('This device runs a gateway: the web UI is open there too.') }, tr('gateway')) : null,
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

async function openNoteEditor(note, { onSaved, onOpenTitle, linkTo = null, centerId = null } = {}) {
  const full = note?.id ? await get(`/v1/memory/notes/${note.id}`) : null;
  const others = full ? [] : (await get('/v1/memory/notes')).notes;
  const center = others.find((x) => x.id === centerId);
  const link = full ? null : h('select', { 'aria-label': tr('Linked to') },
    h('option', { value: '' }, tr('No link')),
    [...(center ? [center] : []), ...others.filter((x) => x.id !== centerId).sort((a, b) => a.title.localeCompare(b.title))]
      .map((x) => h('option', { value: x.title, selected: x.title === (linkTo || center?.title) }, x.id === centerId ? tr('{0} (central)', x.title) : x.title)));
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
    const payload = { title: title.value.trim(), body: body.value, kind: kind.value, importance: Number(importance.value), pinned, tags: tags.value.split(',').map((t) => t.trim()).filter(Boolean), ...(link?.value ? { link_to: link.value } : {}) };
    if (!payload.title) { title.focus(); return; }
    save.disabled = true;
    try {
      const saved = full ? await api(`/v1/memory/notes/${full.id}`, { method: 'PATCH', body: JSON.stringify(payload) }) : await post('/v1/memory/notes', payload);
      closeLayer();
      toast(full ? tr('Note saved') : tr('Note created'));
      onSaved?.(saved);
    } catch (err) { fail(err); } finally { save.disabled = false; }
  });
  const remove = full && full.id !== centerId ? h('button', { class: 'btn btn-danger', onclick: async () => {
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
      link ? h('label', { class: 'note-field' }, h('span', {}, tr('Linked to')), link) : null,
      h('label', { class: 'note-field' }, h('span', {}, tr('Text')), body),
      backlinks),
    h('div', { class: 'modal-actions' }, remove, h('span', { class: 'spacer' }), h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
  ).classList.add('modal-wide');
  (full ? body : title).focus();
}

async function settingsChannels(shell) {
  const STATES = {
    off: [tr('Off'), ''],
    connecting: [tr('Connecting...'), 'accent live'],
    waiting_owner: [tr('Waiting for the owner'), 'warn'],
    ready: [tr('Connected'), 'ok'],
    error: [tr('Error'), 'danger'],
  };
  const body = h('div', {});
  let poll = 0;
  viewCleanups.push(() => clearTimeout(poll));

  const save = async (patch, done) => {
    try { await api('/v1/channels/telegram', { method: 'PUT', body: JSON.stringify(patch) }); if (done) toast(done); await load(); } catch (err) { fail(err); }
  };
  const unbind = async () => {
    if (!await confirmDialog({ title: tr('Unbind the owner?'), text: tr('The next Telegram account that writes to the bot becomes its owner. The current chat is closed for the bot.'), action: tr('Unbind') })) return;
    try { await post('/v1/channels/telegram/unbind'); toast(tr('Unbound')); await load(); } catch (err) { fail(err); }
  };
  const disconnect = async () => {
    if (!await confirmDialog({ title: tr('Disconnect Telegram?'), text: tr('The token and the owner binding are deleted from Core. Chats started from Telegram stay in the sidebar.'), action: tr('Disconnect'), danger: true })) return;
    try { await del('/v1/channels/telegram'); toast(tr('Disconnected')); await load(); } catch (err) { fail(err); }
  };

  function tokenForm(replacing) {
    const input = h('input', { type: 'password', autocomplete: 'off', placeholder: '123456789:AbCdEf...', 'aria-label': tr('Bot token') });
    const btn = h('button', { class: 'btn btn-primary', onclick: async () => {
      if (!input.value.trim()) { input.focus(); return; }
      btn.disabled = true;
      try { await save({ token: input.value.trim() }, tr('Bot connected')); closeLayer(); } finally { btn.disabled = false; }
    } }, replacing ? tr('Replace') : tr('Connect'));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') btn.click(); });
    return { input, btn };
  }

  function replaceDialog() {
    const { input, btn } = tokenForm(true);
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, tr('Replace the token')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('div', { class: 'plugin-form' }, h('label', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, h('span', {}, tr('Bot token'))), input)),
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), btn),
    );
    input.focus();
  }

  function render(data) {
    const tg = data.items[0];
    const [stateLabel, stateCls] = STATES[tg.state] || STATES.off;
    const { bot, owner } = tg;
    const link = bot?.username ? `https://t.me/${bot.username}` : null;
    const ownerName = owner ? (owner.name || (owner.username ? `@${owner.username}` : String(owner.user_id))) : '';
    const hero = h('div', { class: 'hero provider-hero' },
      h('span', { class: 'market-icon' }, icon('send')),
      h('div', { class: 'hero-text' }, h('h2', {}, 'Telegram'),
        h('p', {}, bot
          ? [link ? h('a', { href: link, target: '_blank', rel: 'noopener' }, `@${bot.username}`) : bot.name, owner ? ` · ${tr('bound to {0}', ownerName)}` : '']
          : tr('A bot you talk to from your phone: tasks, replies, and approval buttons.'))),
      tg.configured ? h('label', { class: 'switch-label' }, toggleSwitch(tg.enabled, { label: tr('Enable Telegram'), onChange: async (v) => { await api('/v1/channels/telegram', { method: 'PUT', body: JSON.stringify({ enabled: v }) }); await load(); } }), tr('On')) : null,
      h('span', { class: 'status' }, h('span', { class: `dot ${stateCls}` }), stateLabel));
    const sections = [tg.error ? h('p', { class: 'market-note' }, tg.error) : null];
    if (!tg.configured) {
      const { input, btn } = tokenForm(false);
      sections.push(section(tr('Bot token'), tr('Create a bot in @BotFather, copy its token and paste it here. The token stays on the Core server.'),
        h('div', { class: 'rows' }, h('div', { class: 'row' }, h('div', { class: 'row-text' }, h('div', { class: 'secret-field' }, input, btn))))));
    } else {
      const deviceSel = h('select', { 'aria-label': tr('Device'), onchange: () => save({ target_id: deviceSel.value }, tr('Saved')) },
        h('option', { value: '', selected: !tg.target_id }, tr('First available device')),
        data.devices.map((d) => h('option', { value: d.id, selected: d.id === tg.target_id }, d.online ? d.name : `${d.name} · ${tr('offline')}`)));
      const modeSel = h('select', { 'aria-label': tr('Access mode'), onchange: () => save({ mode: modeSel.value }, tr('Saved')) },
        Object.entries(MODES).map(([k, m]) => h('option', { value: k, selected: k === tg.mode }, m.label)));
      sections.push(
        section(tr('Owner'), tr('The bot answers only one Telegram account: the first one that writes to it after connecting.'), h('div', { class: 'rows' }, owner
          ? row(ownerName, [owner.username ? `@${owner.username}` : null, `id ${owner.user_id}`].filter(Boolean).join(' · '), h('button', { class: 'btn btn-sm', onclick: unbind }, tr('Unbind')))
          : row(tr('Waiting for the first message'), tr('Open the bot and send /start. Until then nobody can use it.'), link ? h('a', { class: 'btn btn-sm', href: link, target: '_blank', rel: 'noopener' }, tr('Open the bot')) : null))),
        section(tr('Tasks from Telegram'), tr('Each message continues the current chat; /new starts another one. The chat also appears in the sidebar.'), h('div', { class: 'rows' },
          row(tr('Device'), tr('Where the agent works.'), deviceSel),
          row(tr('Access mode'), MODES[tg.mode]?.desc, modeSel),
          row(tr('Current chat'), tg.task ? `${taskTitle(tg.task)} · ${tg.task.status.toLowerCase()}` : tr('No chat yet.'), tg.task ? h('a', { class: 'btn btn-sm', href: `#/chat/${tg.task.id}` }, tr('Open')) : null))),
        section(tr('Bot'), null, h('div', { class: 'rows' },
          row(tr('Replace the token'), tr('For another bot; the owner binding is reset when the bot changes.'), h('button', { class: 'btn btn-sm', onclick: replaceDialog }, tr('Replace'))),
          row(tr('Disconnect'), tr('Deletes the token and the binding from Core.'), h('button', { class: 'btn btn-sm btn-danger', onclick: disconnect }, tr('Disconnect'))))),
      );
    }
    body.replaceChildren(hero, ...sections.filter(Boolean));
  }

  async function load() {
    const data = await get('/v1/channels');
    render(data);
    clearTimeout(poll);
    if (['connecting', 'waiting_owner'].includes(data.items[0].state)) poll = setTimeout(() => load().catch(() => {}), 3000);
  }

  page(shell, tr('Channels'), tr('Talk to the agent from a messenger. Replies and approval buttons come to the chat; the bot listens only to the account it is bound to.'), null, body);
  await load();
}

async function settingsMemory(shell) {
  const TABS = [['graph', tr('Graph')], ['notes', tr('Notes')], ['dreams', tr('Dreaming')]];
  let tab = localStorageGet('memory-tab') || 'graph';
  let centerId = null;
  const tabs = h('div', { class: 'segmented mem-tabs', role: 'tablist', 'aria-label': tr('Memory') });
  const host = h('div', { class: 'mem-body' });
  let cleanup = null;
  const renderTabs = () => tabs.replaceChildren(...TABS.map(([key, label]) => h('button', {
    class: `seg${key === tab ? ' active' : ''}`, role: 'tab', 'aria-selected': String(key === tab),
    onclick: () => { tab = key; localStorageSet('memory-tab', key); show(); },
  }, label)));
  const byTitle = async (title) => (await get(`/v1/memory/notes?q=${encodeURIComponent(title)}`)).notes.find((n) => n.title.toLowerCase() === title.toLowerCase());
  const openTitle = async (title) => {
    const note = await byTitle(title);
    openNoteEditor(note || { title }, { onSaved: () => show(), onOpenTitle: openTitle, centerId });
  };
  const newNote = (linkTo = null) => openNoteEditor(null, { onSaved: () => show(), onOpenTitle: openTitle, linkTo, centerId });

  async function show() {
    if (cleanup) { cleanup(); cleanup = null; }
    renderTabs();
    host.replaceChildren();
    host.dataset.tab = tab;
    cleanup = await ({ graph: memoryGraph, notes: memoryNotes, dreams: memoryDreams }[tab] || memoryGraph)();
  }

  // The graph fills the whole panel: the central note in the middle, other notes on rings around it.
  async function memoryGraph() {
    const stage = h('div', { class: 'mm-stage', 'aria-label': tr('Memory graph: drag to move, scroll to zoom') });
    const side = h('aside', { class: 'graph-side mm-ui hidden' });
    const search = h('input', { type: 'search', placeholder: tr('Find a note'), 'aria-label': tr('Find a note on the graph') });
    let data = { nodes: [], links: [], center: null };
    let files = [];
    let limit = 20000;
    const map = createMemoryMap(stage, {
      icon,
      centerTitle: tr('About me'),
      countText: (n) => tp('{0} note around|{0} notes around', n),
      onSelect: (node) => preview(node),
      onFile: (name) => previewFile(name),
    });

    async function loadFiles() {
      const ins = await get('/v1/instructions');
      files = ins.items;
      limit = ins.limit;
      map.setFiles(files.map((f) => ({ name: f.name, custom: f.custom, over: f.content.length > limit, desc: INSTRUCTION_DESC[f.name] ? INSTRUCTION_DESC[f.name]() : f.description })));
    }
    function previewFile(name) {
      const f = files.find((x) => x.name === name);
      if (!f) return;
      side.classList.remove('hidden');
      side.replaceChildren(...[
        h('div', { class: 'graph-side-head' }, h('h3', {}, h('code', {}, f.name)), h('button', { class: 'icon-btn', 'aria-label': tr('Close'), onclick: hideSide }, icon('x'))),
        h('div', { class: 'graph-side-meta' }, f.custom ? h('span', { class: 'pill accent' }, tr('your text')) : h('span', { class: 'pill' }, tr('default')), f.content.length > limit ? h('span', { class: 'pill warn' }, tr('too long')) : null),
        h('p', { class: 'muted' }, INSTRUCTION_DESC[f.name] ? INSTRUCTION_DESC[f.name]() : f.description, ' ', tr('The agent reads it at the start of every chat.')),
        h('div', { class: 'prose graph-side-body', html: markdown(f.content || '') }),
        h('div', { class: 'market-meta' }, [tr('{0} / {1} characters', f.content.length.toLocaleString(locale), limit.toLocaleString(locale)), f.custom && f.updated_at ? tr('updated {0}', relTime(f.updated_at)) : null].filter(Boolean).join(' · ')),
        h('div', { class: 'graph-side-actions' },
          h('button', { class: 'btn btn-sm', onclick: () => openInstructionEditor(f, limit, async () => { await loadFiles(); previewFile(name); }) }, tr('Edit')),
          f.custom ? h('button', { class: 'btn btn-sm', onclick: async () => {
            try { await api(`/v1/instructions/${f.name}`, { method: 'PUT', body: JSON.stringify({ content: '' }) }); toast(tr('Back to the default')); await loadFiles(); previewFile(name); } catch (err) { fail(err); }
          } }, tr('Reset to default')) : null),
      ].filter(Boolean));
    }

    async function load() {
      data = await get('/v1/memory/graph');
      if (!data.center) {
        try { await post('/v1/memory/center', { title: tr('About me') }); data = await get('/v1/memory/graph'); } catch (err) { fail(err); }
      }
      centerId = data.center;
      map.setData(data);
    }
    const hideSide = () => { side.classList.add('hidden'); map.select(null); };
    async function preview(node) {
      if (!node) { hideSide(); return; }
      side.classList.remove('hidden');
      const close = h('button', { class: 'icon-btn', 'aria-label': tr('Close'), onclick: hideSide }, icon('x'));
      if (node.ghost) {
        side.replaceChildren(h('div', { class: 'graph-side-head' }, h('h3', {}, node.label), close), h('p', { class: 'muted' }, tr('This note is linked to, but doesn\'t exist yet.')), h('button', { class: 'btn btn-primary btn-sm', onclick: () => openNoteEditor({ title: node.label }, { onSaved: load, onOpenTitle: openTitle, centerId }) }, icon('plus'), tr('Create note')));
        return;
      }
      side.replaceChildren(h('div', { class: 'graph-side-head' }, h('h3', {}, node.label), close), h('p', { class: 'muted' }, tr('Loading...')));
      let n;
      try { n = await get(`/v1/memory/notes/${node.id}`); } catch (err) { fail(err); return; }
      const isCenter = n.id === centerId;
      const bodyEl = h('div', { class: 'prose graph-side-body', html: memoryMd(n.body || (isCenter ? tr('_Write here who you are and how you like to work: the agent always sees this note._') : tr('_Empty_'))) });
      bodyEl.addEventListener('click', (e) => {
        const link = e.target.closest('.wikilink');
        if (!link) return;
        e.preventDefault();
        const target = data.nodes.find((x) => x.label.toLowerCase() === link.dataset.title.toLowerCase());
        if (target) { map.select(target.id, { pan: true }); preview(target); }
      });
      const center = data.nodes.find((x) => x.id === centerId);
      const detached = !isCenter && map.isImplicit(n.id);
      const attach = detached && center ? h('button', { class: 'btn btn-sm', onclick: async () => {
        try { await api(`/v1/memory/notes/${n.id}`, { method: 'PATCH', body: JSON.stringify({ body: `${(n.body || '').trimEnd()}\n\n[[${center.label}]]`.trim() }) }); toast(tr('Linked')); await load(); map.select(n.id); preview(node); } catch (err) { fail(err); }
      } }, icon('link'), tr('Link to “{0}”', center.label)) : null;
      const makeCenter = isCenter ? null : h('button', { class: 'btn btn-sm', onclick: async () => {
        try { await post('/v1/memory/center', { note_id: n.id }); toast(tr('Now the central note')); await load(); map.fit(); map.select(n.id); preview(node); } catch (err) { fail(err); }
      } }, tr('Make central'));
      side.replaceChildren(...[
        h('div', { class: 'graph-side-head' }, h('h3', {}, n.title), close),
        h('div', { class: 'graph-side-meta' }, isCenter ? h('span', { class: 'pill accent' }, tr('central')) : null, kindPill(n.kind), n.pinned ? h('span', { class: 'pill accent', title: tr('Always in the agent\'s context') }, icon('pin'), tr('pinned')) : null, (n.tags || []).map((t) => h('span', { class: 'pill tag' }, `#${t}`))),
        detached ? h('p', { class: 'market-note' }, tr('Not linked to other notes yet, so it hangs on the central one.')) : null,
        bodyEl,
        n.backlinks.length ? h('div', { class: 'note-backlinks' }, tr('Linked from: '), n.backlinks.map((b, i) => [i ? ', ' : '', h('a', { href: '#', onclick: (e) => { e.preventDefault(); map.select(b.id, { pan: true }); preview(data.nodes.find((x) => x.id === b.id)); } }, b.title)])) : null,
        h('div', { class: 'market-meta' }, tr('source: {0} · importance {1}', MEM_SOURCES[n.source] || n.source, n.importance)),
        h('div', { class: 'graph-side-actions' },
          h('button', { class: 'btn btn-sm', onclick: () => openNoteEditor(n, { onSaved: async () => { await load(); map.select(n.id); }, onOpenTitle: openTitle, centerId }) }, tr('Edit')),
          h('button', { class: 'btn btn-sm', onclick: () => newNote(n.title) }, icon('plus'), tr('Linked note')),
          attach, makeCenter),
      ].filter(Boolean));
    }
    search.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const q = search.value.trim().toLowerCase();
      const node = data.nodes.find((x) => x.label.toLowerCase() === q) || data.nodes.find((x) => x.label.toLowerCase().includes(q));
      if (node) { map.select(node.id, { pan: true }); preview(node); } else toast(tr('No such note found'));
    });
    const legend = h('div', { class: 'graph-legend mm-legend mm-ui' }, Object.entries(MEM_KINDS).map(([k, label]) => h('span', {}, h('span', { class: 'kind-dot', style: `background:${graphColor(k)}` }), label)));
    stage.append(
      h('div', { class: 'mm-tools mm-ui' }, h('div', { class: 'settings-search graph-search' }, icon('search'), search)),
      h('div', { class: 'mm-zoom mm-ui' },
        h('button', { class: 'icon-btn', title: tr('Zoom in'), 'aria-label': tr('Zoom in'), onclick: () => map.zoom(1.25) }, icon('plus')),
        h('button', { class: 'icon-btn', title: tr('Show all'), 'aria-label': tr('Show all'), onclick: () => map.fit() }, icon('layers')),
        h('button', { class: 'icon-btn', title: tr('Zoom out'), 'aria-label': tr('Zoom out'), onclick: () => map.zoom(1 / 1.25) }, h('span', { class: 'zoom-sign' }, '−'))),
      legend,
      side,
    );
    host.append(stage);
    await load();
    await loadFiles().catch(fail);
    return () => map.destroy();
  }

  async function memoryNotes() {
    const search = h('input', { type: 'search', placeholder: tr('Search notes'), 'aria-label': tr('Search notes') });
    const kindFilter = h('select', { 'aria-label': tr('Note type') }, h('option', { value: '' }, tr('All types')), Object.entries(MEM_KINDS).map(([k, label]) => h('option', { value: k }, label)));
    const list = h('div', { class: 'rows' }, h('div', { class: 'empty' }, tr('Loading...')));
    let timer = 0;
    async function load() {
      const q = search.value.trim();
      const { notes, center: centerNote } = await get(`/v1/memory/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`);
      centerId = centerNote;
      const shown = notes.filter((n) => !kindFilter.value || n.kind === kindFilter.value);
      list.replaceChildren(...(shown.length ? shown.map((n) => h('button', { class: 'note-item', onclick: () => openNoteEditor(n, { onSaved: load, onOpenTitle: openTitle, centerId }) },
        h('span', { class: 'kind-dot', style: `background:${graphColor(n.kind)}` }),
        h('div', { class: 'row-text' },
          h('div', { class: 'row-title' }, n.title, n.id === centerId ? h('span', { class: 'pill accent' }, tr('central')) : null, n.pinned ? h('span', { class: 'note-pin', title: tr('Always in the agent\'s context') }, icon('pin')) : null),
          h('div', { class: 'row-desc' }, n.snippet || tr('Empty')),
          h('div', { class: 'note-item-meta' }, [MEM_KINDS[n.kind] || n.kind, MEM_SOURCES[n.source] || n.source, relTime(n.updated_at), ...(n.tags || []).map((t) => `#${t}`)].join(' · ')))))
        : [h('div', { class: 'empty' }, q || kindFilter.value ? tr('Nothing found.') : tr('No notes yet. The agent will save what matters on its own, and dreaming will gather from chats.'))]));
    }
    search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => load().catch(fail), 200); });
    kindFilter.addEventListener('change', () => load().catch(fail));
    const filesBox = h('div', { class: 'rows' }, h('div', { class: 'empty' }, tr('Loading...')));
    async function loadFiles() {
      const ins = await get('/v1/instructions');
      filesBox.replaceChildren(...ins.items.map((f) => h('button', { class: 'note-item', onclick: () => openInstructionEditor(f, ins.limit, loadFiles) },
        h('span', { class: 'mem-file-icon' }, icon('file')),
        h('div', { class: 'row-text' },
          h('div', { class: 'row-title' }, h('code', {}, f.name), f.custom ? null : h('span', { class: 'pill' }, tr('default')), f.content.length > ins.limit ? h('span', { class: 'pill warn' }, tr('too long')) : null),
          h('div', { class: 'row-desc' }, INSTRUCTION_DESC[f.name] ? INSTRUCTION_DESC[f.name]() : f.description)))));
    }
    host.append(h('div', { class: 'page' }, h('div', { class: 'page-inner page-wide' },
      section(tr('Instruction files'), tr('The agent reads these at the start of every chat: how to work, its persona and name, who you are. Each has a default until you write your own.'), filesBox),
      section(tr('Notes'), null, h('div', { class: 'graph-toolbar' }, h('div', { class: 'settings-search graph-search' }, icon('search'), search), kindFilter), list))));
    loadFiles().catch(fail);
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
        (r.changes || []).length ? h('div', { class: 'dream-changes' }, r.changes.map((c) => h('button', { class: `dream-change ${c.action}`, onclick: () => openNoteEditor({ id: c.id }, { onSaved: () => show(), onOpenTitle: openTitle, centerId }).catch(() => toast(tr('Note already deleted'), true)) },
          { created: '+', updated: '~', reinforced: '↑' }[c.action] || '', ` ${c.title}`))) : null);
    }
    host.append(h('div', { class: 'page' }, h('div', { class: 'page-inner page-wide' }, box)));
    await load();
    return () => clearTimeout(timer);
  }

  const newBtn = h('button', { class: 'btn btn-sm mem-new', 'aria-label': tr('New note'), onclick: () => newNote() }, icon('plus'), h('span', { class: 'mem-new-label' }, tr('New note')));
  shell.panel.replaceChildren(
    topbar(shell, [h('span', { class: 'current mem-title' }, tr('Memory')), tabs], [newBtn]),
    host,
  );
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

const INSTRUCTION_DESC = {
  'AGENTS.md': () => tr('Operating instructions: rules, priorities, how to work.'),
  'SOUL.md': () => tr('Persona and tone of the agent.'),
  'IDENTITY.md': () => tr('The name and style the agent presents itself with.'),
  'USER.md': () => tr('Who you are: role, timezone, languages and tools you prefer.'),
};
const INSTRUCTION_HINT = {
  'AGENTS.md': () => tr('# How to work\n\n- Answer in the language of the question.\n- Run the tests before reporting a change.\n- Do not touch files outside the task.'),
  'SOUL.md': () => tr('# Soul\n\nDirect and concise. When an idea looks wrong, say so and propose a better one.'),
  'IDENTITY.md': () => tr('# Identity\n\nName: ...\nStyle: ...'),
  'USER.md': () => tr('# User\n\nName, role, timezone, preferred languages and tools.'),
};

// The instruction files the agent reads at the start of every chat; an empty save brings the default back.
function openInstructionEditor(f, limit, onSaved) {
  const body = h('textarea', { class: 'market-yaml skill-body', rows: 18, spellcheck: 'false', 'aria-label': f.name, placeholder: INSTRUCTION_HINT[f.name] ? INSTRUCTION_HINT[f.name]() : '' });
  body.value = f.content;
  const count = h('div', { class: 'row-desc' });
  const updateCount = () => {
    const n = body.value.length;
    count.textContent = tr('{0} / {1} characters', n.toLocaleString(locale), limit.toLocaleString(locale));
    count.classList.toggle('over', n > limit);
  };
  body.addEventListener('input', updateCount);
  updateCount();
  const put = async (content, done) => {
    const saved = await api(`/v1/instructions/${f.name}`, { method: 'PUT', body: JSON.stringify({ content }) });
    closeLayer();
    toast(done);
    await onSaved?.(saved);
  };
  const save = h('button', { class: 'btn btn-primary' }, tr('Save'));
  save.addEventListener('click', async () => {
    save.disabled = true;
    try { await put(body.value, tr('Saved')); } catch (err) { fail(err); } finally { save.disabled = false; }
  });
  const reset = f.custom ? h('button', { class: 'btn btn-sm', onclick: () => put('', tr('Back to the default')).catch(fail) }, tr('Reset to default')) : null;
  openModal(
    h('div', { class: 'modal-head' }, h('h2', {}, f.name), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
    h('p', { class: 'row-desc' }, INSTRUCTION_DESC[f.name] ? INSTRUCTION_DESC[f.name]() : f.description, ' ', tr('The agent sees the first {0} characters at the start of every chat. Saving an empty text brings the default back.', limit.toLocaleString(locale))),
    h('div', { class: 'plugin-form' }, body, count),
    h('div', { class: 'modal-actions' }, reset, h('span', { class: 'spacer' }), h('button', { class: 'btn', onclick: closeLayer }, tr('Cancel')), save),
  ).classList.add('modal-wide');
  body.focus();
}

function pluginState(p, devices) {
  if (!p.installed) return null;
  if (!p.installed.enabled) return [tr('Off'), ''];
  if (p.missing.includes('_oauth') && p.missing.length === 1) return [tr('Not connected'), 'warn'];
  if (p.missing.length) return [tr('Needs setup'), 'warn'];
  if (p.oauth?.rescope) return [tr('Reconnect to grant access'), 'warn'];
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

  function toolRows(p, tools) {
    const disabled = new Set(p.disabled_tools || []);
    const granted = new Set(p.oauth?.scope || []);
    return h('div', { class: 'tool-rows' }, tools.map((t) => {
      const noScope = t.scope && p.oauth?.connected && !granted.has(t.scope);
      return h('div', { class: 'tool-row' },
        icon('plug'),
        h('div', { class: 'row-text' },
          h('div', { class: 'tool-row-title' }, t.name, t.risk ? h('span', { class: 'pill' }, RISK_SHORT[t.risk] || t.risk) : null),
          t.description ? h('div', { class: 'row-desc' }, t.description.slice(0, 220)) : null,
          noScope ? h('div', { class: 'row-desc warn' }, tr('Access not granted: turn it on in the settings and reconnect.')) : null),
        p.installed ? toggleSwitch(!disabled.has(t.name), { label: t.name, onChange: async (v) => {
          if (v) disabled.delete(t.name); else disabled.add(t.name);
          Object.assign(p, await api(`/v1/plugins/${p.id}/config`, { method: 'PUT', body: JSON.stringify({ disabled_tools: [...disabled] }) }));
        } }) : null);
    }));
  }

  function accountBlock(p, reopen) {
    if (!p.oauth) return null;
    const o = p.oauth;
    const needs = p.missing.filter((k) => k in (p.settings || {}));
    const redirectLine = h('div', { class: 'row-desc' });
    const manualNote = h('div', { class: 'row-desc hidden' }, tr('This address does not open in your browser: after signing in, copy the address the browser lands on and paste it below.'));
    const pasted = h('input', { type: 'text', placeholder: 'http://127.0.0.1:.../v1/oauth/callback?code=...&state=...', 'aria-label': tr('Address after sign-in') });
    const finish = h('button', { class: 'btn btn-sm btn-primary' }, tr('Finish'));
    finish.addEventListener('click', async () => {
      if (!pasted.value.trim()) return;
      finish.disabled = true;
      try { await post(`/v1/plugins/${p.id}/oauth/finish`, { url: pasted.value.trim() }); toast(tr('Connected')); await reopen(); } catch (err) { fail(err); } finally { finish.disabled = false; }
    });
    const manualRow = h('div', { class: 'secret-field hidden' }, pasted, finish);
    let manual = false;
    get(`/v1/oauth/redirect?origin=${encodeURIComponent(location.origin)}`).then((r) => {
      manual = r.manual;
      redirectLine.replaceChildren(...(o.own_client ? [tr('Redirect URI for the OAuth client: '), h('code', {}, r.redirect_uri), ' ', copyBtn(r.redirect_uri)] : []));
      manualNote.classList.toggle('hidden', !manual);
    }).catch(() => {});
    const connect = h('button', { class: `btn btn-sm${o.connected ? '' : ' btn-primary'}`, disabled: !p.installed || needs.length > 0 }, icon('link'), o.connected ? tr('Reconnect') : tr('Connect'));
    connect.addEventListener('click', async () => {
      connect.disabled = true;
      try {
        const r = await post(`/v1/plugins/${p.id}/oauth/start`, { origin: location.origin });
        const tab = window.open(r.url, '_blank', 'noopener');
        if (r.manual) {
          manualRow.classList.remove('hidden');
          pasted.focus();
        } else {
          const onMessage = async (ev) => {
            if (ev.data?.mensarium !== 'oauth') return;
            window.removeEventListener('message', onMessage);
            if (ev.data.ok) toast(tr('Connected'));
            await reopen();
          };
          window.addEventListener('message', onMessage);
        }
        if (!tab) toast(tr('Allow pop-ups for this page to sign in'));
      } catch (err) { fail(err); } finally { connect.disabled = false; }
    });
    const disconnect = o.connected ? h('button', { class: 'btn btn-sm', onclick: async () => {
      try { await api(`/v1/plugins/${p.id}/oauth`, { method: 'DELETE' }); toast(tr('Disconnected')); await reopen(); } catch (err) { fail(err); }
    } }, tr('Disconnect')) : null;
    const state = o.connected
      ? [h('span', { class: 'dot ok' }), h('span', {}, o.rescope ? tr('Connected, but not for everything that is turned on: reconnect') : tr('Connected {0}', relTime(o.connected_at)))]
      : [h('span', { class: 'dot' }), h('span', {}, needs.length ? tr('Save the settings above, then connect') : tr('Not connected'))];
    return h('div', { class: 'plugin-mcp' },
      h('div', { class: 'field-label' }, tr('Account')),
      h('div', { class: `plugin-status ${o.connected ? 'ok' : ''}` }, ...state, h('span', { class: 'spacer' }), disconnect, ' ', connect),
      redirectLine,
      manualNote,
      manualRow);
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
    const toolsList = (st.tools || []).length ? toolRows(p, st.tools) : null;
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
    const reopen = async () => { closeLayer(); await load(); details(items.find((x) => x.id === p.id) || p); };
    const mcp = mcpBlock(p, reopen);
    const account = accountBlock(p, reopen);
    const coreTools = p.core_tools || [];
    const coreRisk = !p.provides.mcp && coreTools.some((t) => !t.risk)
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
      coreTools.length ? h('div', { class: 'plugin-mcp' },
        h('div', { class: 'field-label' }, tr('Tools in Core')),
        h('div', { class: 'row-desc' }, coreRisk ? tr('They run on the Core server; requests to the network go through approval unless you lower the risk.') : tr('They run on the Core server; each tool carries its own risk, and a switch turns it off for the agent.')),
        coreRisk ? h('label', { class: 'plugin-field plugin-risk' }, h('div', { class: 'plugin-field-head' }, h('span', {}, tr('Risk of its tools'))), coreRisk) : null,
        toolRows(p, coreTools)) : null,
      p.tools.length ? [h('div', { class: 'field-label' }, tr('Tools on devices')), h('div', { class: 'market-tools' }, p.tools.map((t) => h('div', { class: 'market-tool' },
        h('div', { class: 'market-tool-head' }, h('code', {}, t.name), h('span', { class: 'pill' }, RISK_SHORT[t.risk] || t.risk)),
        h('div', { class: 'row-desc' }, t.description),
        h('pre', { class: 'market-argv' }, `$ ${t.argv.join(' ')}`))))] : null,
    ];
    const state = pluginState(p, devices);
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, txt(p.name)), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      h('div', { class: 'market-meta' }, [p.author, tr('version {0}', p.installed ? p.installed.version : p.version), p.installed?.source === 'custom' ? tr('your plugin') : null].filter(Boolean).join(' · '), p.homepage ? [' · ', h('a', { href: p.homepage, target: '_blank', rel: 'noopener' }, tr('Website'))] : null, state ? [' ', h('span', { class: `pill ${state[1]}` }, state[0])] : null),
      h('p', {}, linkify(txt(p.description) || txt(p.summary))),
      what,
      mcp ? mcp.el : null,
      form.rows.length ? [h('div', { class: 'field-label' }, tr('Settings')), h('div', { class: 'plugin-form' }, form.rows)] : null,
      account,
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
  page(shell, tr('Profiles'), tr('A profile sets the agent\'s tools and the actions that wait for approval in ask-before-acting mode.'), null,
    profiles.map((p) => section(tr('{0}, version {1}', p.name, p.version), p.id, h('div', { class: 'rows' },
      row(tr('Model'), tr('Temperature {0}', p.llm.temperature), p.llm.model, true),
      row(tr('Tools'), null, null),
      h('div', { class: 'row-extra' }, p.allowed_tools.map((t) => h('span', { class: 'pill tag' }, t))),
      row(tr('Require approval'), tr('In “Ask before acting” mode, you approve each such action separately.'), h('span', {}, p.approval.required_risks.map((r) => (RISK[r] || [r])[0]).join(', '))),
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

// ---------- automations ----------

const SCHEDULE_KINDS = { every: tr('Every N minutes or hours'), daily: tr('Every day'), weekly: tr('On days of the week'), once: tr('Once'), cron: tr('Cron expression') };
const WEEK = [1, 2, 3, 4, 5, 6, 0];
const RUN_STATUS = { running: [tr('Running'), 'accent'], ok: [tr('Done'), 'ok'], error: [tr('Error'), 'danger'], timeout: [tr('Timed out'), 'danger'], canceled: [tr('Canceled'), 'warn'], lost: [tr('Lost'), 'danger'] };
const DISABLED = { 'consecutive-failures': (a) => tr('Off after {0} failures', a.failures), 'one-shot-done': () => tr('Done'), 'never-fires': () => tr('Never fires again') };
const AUTO_ERRORS = { 'the time is in the past': tr('This time has already passed'), 'the schedule never fires': tr('The schedule never fires'), 'unknown or revoked device': tr('The device is unknown or revoked') };
const autoError = (err) => (AUTO_ERRORS[err.message] ? new Error(AUTO_ERRORS[err.message]) : err);
const pad2 = (n) => String(n).padStart(2, '0');
const browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const dayName = (d) => {
  const s = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(2026, 0, 4 + d)));
  return s[0].toUpperCase() + s.slice(1);
};
const fmtTime = (iso, tz) => new Date(iso).toLocaleString(locale, { timeZone: tz, weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

function inTime(iso) {
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (s < 60) return tr('in less than a minute');
  const m = Math.round(s / 60);
  if (m < 60) return tr('in {0} min', m);
  const hr = Math.round(m / 60);
  if (hr < 24) return tr('in {0} h', hr);
  return tr('in {0} d', Math.round(hr / 24));
}

// The clock of a time zone at a given instant, as year/month/day/hour/minute strings.
function wallParts(ms, tz) {
  return Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    .formatToParts(new Date(ms)).map((p) => [p.type, p.value]));
}
const wallOf = (iso, tz) => { const p = wallParts(Date.parse(iso), tz); return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`; };

// A datetime-local value read in the zone becomes ISO with that zone's offset at that moment.
function isoIn(value, tz) {
  const offset = (ms) => { const p = wallParts(ms, tz); return (Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - ms) / 60000; };
  const guess = Date.parse(`${value}:00Z`);
  const off = offset(guess - offset(guess) * 60000);
  const abs = Math.abs(off);
  return `${value}:00${off < 0 ? '-' : '+'}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`;
}

// The editor shows daily and weekly cron expressions as their own kinds; anything else stays raw cron.
function formFromSchedule(s) {
  const tz = s?.tz || browserTz();
  const soon = new Date(Math.ceil((Date.now() + 3600000) / 3600000) * 3600000).toISOString();
  const f = { kind: 'daily', n: 1, unit: 'h', time: '09:00', days: [1, 2, 3, 4, 5], at: wallOf(soon, tz), expr: '0 9 * * 1-5', tz };
  if (!s) return f;
  if (s.kind === 'every') {
    return { ...f, kind: 'every', ...(s.every_s % 60 ? { n: s.every_s, unit: 's' } : s.every_s % 3600 ? { n: Math.round(s.every_s / 60), unit: 'm' } : { n: s.every_s / 3600, unit: 'h' }) };
  }
  if (s.kind === 'at') return { ...f, kind: 'once', at: wallOf(s.at, tz) };
  const expr = s.expr.trim().split(/\s+/).join(' ');
  const m = expr.match(/^(\d{1,2}) (\d{1,2}) \* \* (\*|[0-6](?:,[0-6])*)$/);
  if (!m || Number(m[1]) > 59 || Number(m[2]) > 23) return { ...f, kind: 'cron', expr };
  const time = `${pad2(m[2])}:${pad2(m[1])}`;
  if (m[3] === '*') return { ...f, kind: 'daily', time };
  return { ...f, kind: 'weekly', time, days: WEEK.filter((d) => m[3].split(',').includes(String(d))) };
}

function scheduleFromForm(f) {
  const s = { kind: 'cron', at: null, every_s: null, expr: null, tz: f.tz };
  const [hh, mm] = (f.time || '').split(':').map(Number);
  if (f.kind === 'every') {
    if (!(Number(f.n) > 0)) throw new Error(tr('Set the interval'));
    return { ...s, kind: 'every', every_s: Math.round(Number(f.n) * (f.unit === 'h' ? 3600 : f.unit === 's' ? 1 : 60)) };
  }
  if (f.kind === 'once') {
    if (!f.at) throw new Error(tr('Set the date and time'));
    return { ...s, kind: 'at', at: isoIn(f.at, f.tz) };
  }
  if (f.kind === 'cron') return { ...s, expr: f.expr.trim() };
  if (!f.time || Number.isNaN(hh) || Number.isNaN(mm)) throw new Error(tr('Set the time'));
  if (f.kind === 'daily') return { ...s, expr: `${mm} ${hh} * * *` };
  if (!f.days.length) throw new Error(tr('Pick at least one day'));
  return { ...s, expr: `${mm} ${hh} * * ${f.days.join(',')}` };
}

function scheduleText(s) {
  const f = formFromSchedule(s);
  const text = {
    every: () => (f.unit === 'h' ? tr('Every {0} h', f.n) : f.unit === 's' ? tr('Every {0} s', f.n) : tr('Every {0} min', f.n)),
    daily: () => tr('Daily at {0}', f.time),
    weekly: () => tr('Weekly on {0} at {1}', f.days.map(dayName).join(', '), f.time),
    once: () => tr('Once at {0}', fmtTime(s.at, s.tz)),
    cron: () => tr('Cron {0}', f.expr),
  }[f.kind]();
  return s.kind === 'every' || s.tz === browserTz() ? text : `${text} (${s.tz})`;
}

const safeScheduleText = (a) => { try { return scheduleText(a.schedule); } catch { return a.schedule_text; } };
const createdBy = (a) => a.created_by === 'agent' ? tr('created by the agent') : a.created_by === 'core' ? tr('built in') : null;

const nextText = (a) => (a.enabled && a.next_run_at ? inTime(a.next_run_at) : DISABLED[a.disabled_reason]?.(a) || tr('Off'));

function tzSelect(value) {
  let zones;
  try { zones = Intl.supportedValuesOf('timeZone'); } catch { return h('input', { type: 'text', value, 'aria-label': tr('Time zone') }); }
  if (!zones.includes(value)) zones = [value, ...zones];
  return h('select', { 'aria-label': tr('Time zone') }, zones.map((z) => h('option', { value: z, selected: z === value }, z)));
}

async function runAutomation(id) {
  try {
    await post(`/v1/automations/${id}/run`);
    toast(tr('Started'));
  } catch (err) {
    if (err.status === 409) toast(tr('Already running'));
    else fail(err);
  }
}

function automationRow(a, reload) {
  const [label, cls] = a.running ? RUN_STATUS.running : RUN_STATUS[a.last_status] || [tr('No runs yet'), ''];
  const runBtn = h('button', { class: 'btn btn-sm', disabled: a.running, onclick: async () => { runBtn.disabled = true; await runAutomation(a.id); runBtn.disabled = false; reload().catch(() => {}); } }, icon('play'), tr('Run now'));
  return h('div', { class: 'row' },
    h('a', { class: 'row-text', href: `#/automations/${a.id}` },
      h('div', { class: 'row-title' }, h('span', { class: `dot ${cls}${a.running ? ' live' : ''}`, title: a.last_error || label }), a.name),
      h('div', { class: 'row-desc' }, [safeScheduleText(a), a.target_name || a.target_id, createdBy(a)].filter(Boolean).join(' · '))),
    h('div', { class: 'row-value' },
      h('span', { class: 'auto-next', title: a.next_run_at ? new Date(a.next_run_at).toLocaleString(locale) : null }, nextText(a)),
      toggleSwitch(a.enabled, { label: tr('Enable “{0}”', a.name), onChange: async (v) => {
        try { await post(`/v1/automations/${a.id}/${v ? 'enable' : 'disable'}`); } catch (err) { throw autoError(err); }
        reload().catch(() => {});
      } }),
      runBtn));
}

async function viewAutomations() {
  const shell = ensureAppShell();
  shell.setActive(null);
  const body = h('div', {});
  const newBtn = h('a', { class: 'btn btn-primary hidden', href: '#/automations/new' }, icon('plus'), tr('New automation'));
  let shown = '';
  const load = async () => {
    const data = await get('/v1/automations');
    const key = JSON.stringify(data.items) + Math.floor(Date.now() / 60000);
    if (key === shown) return;
    shown = key;
    newBtn.classList.toggle('hidden', !data.items.length);
    body.replaceChildren(data.items.length
      ? h('div', { class: 'rows autos' }, data.items.map((a) => automationRow(a, load)))
      : h('div', { class: 'empty' }, orb('md'), h('h3', {}, tr('No automations yet')),
        h('p', {}, tr('Recurring or delayed tasks: a morning report, a disk check, a reminder. Set one up here or ask the agent in a chat.')),
        h('a', { class: 'btn btn-primary', href: '#/automations/new' }, icon('plus'), tr('New automation'))));
  };
  page(shell, tr('Automations'), tr('Tasks the agent runs on a schedule. Each run is logged under its automation.'), newBtn, body);
  await load();
  const iv = setInterval(() => load().catch(() => {}), 5000);
  viewCleanups.push(() => clearInterval(iv));
}

function runRow(r) {
  const waiting = r.status === 'running' && r.task_status === 'WAITING_APPROVAL';
  const [label, cls] = waiting ? [tr('Waiting for approval'), 'warn'] : RUN_STATUS[r.status] || [r.status, ''];
  const line = String(r.result || r.error || '').split('\n').find((x) => x.trim());
  const desc = waiting ? tr('Open the transcript to approve the action.') : line || (r.status === 'running' ? null : tr('No reply'));
  return h('div', { class: 'row' },
    h('div', { class: 'row-text' },
      h('div', { class: 'row-title' }, h('span', { title: new Date(r.started_at).toLocaleString(locale) }, relTime(r.started_at)),
        h('span', { class: `pill ${cls}` }, r.status === 'running' && !waiting ? h('span', { class: 'dot accent live' }) : null, label)),
      desc ? h('div', { class: 'row-desc' }, desc) : null),
    h('div', { class: 'row-value' },
      r.duration_ms != null ? h('span', { class: 'mono' }, mmss(Math.round(r.duration_ms / 1000))) : null,
      r.task_id ? h('a', { class: 'btn btn-sm', href: `#/chat/${r.task_id}` }, tr('Transcript')) : null));
}

async function viewAutomationEditor(id) {
  const shell = ensureAppShell();
  shell.setActive(null);
  let data;
  let a = null;
  try { [data, a] = await Promise.all([get('/v1/automations'), id ? get(`/v1/automations/${id}`) : null]); } catch (err) { fail(err); go('#/automations'); return; }
  const f = formFromSchedule(a?.schedule);

  const name = h('input', { type: 'text', value: a?.name || '', maxlength: 120, placeholder: tr('Morning report'), 'aria-label': tr('Name') });
  const prompt = h('textarea', { class: 'auto-prompt', rows: 5, placeholder: tr('Check free disk space and warn me if it is below 10%.'), 'aria-label': tr('Prompt') });
  prompt.value = a?.prompt || '';

  const kind = h('select', { 'aria-label': tr('Repeat') }, Object.entries(SCHEDULE_KINDS).map(([k, label]) => h('option', { value: k, selected: k === f.kind }, label)));
  const every = h('input', { type: 'number', min: 1, step: 1, value: f.n, 'aria-label': tr('Interval') });
  const unit = h('select', { 'aria-label': tr('Unit') },
    h('option', { value: 's', selected: f.unit === 's' }, tr('seconds')),
    h('option', { value: 'm', selected: f.unit === 'm' }, tr('minutes')),
    h('option', { value: 'h', selected: f.unit === 'h' }, tr('hours')));
  const time = h('input', { type: 'time', value: f.time, 'aria-label': tr('Time') });
  const days = WEEK.map((d) => h('label', { class: 'day-chip' }, h('input', { type: 'checkbox', value: d, checked: f.days.includes(d) }), dayName(d)));
  const at = h('input', { type: 'datetime-local', value: f.at, 'aria-label': tr('Date and time') });
  const expr = h('input', { type: 'text', class: 'mono', value: f.expr, placeholder: '0 9 * * 1-5', spellcheck: 'false', 'aria-label': tr('Cron expression') });
  const tz = tzSelect(f.tz);
  const fields = {
    every: field(tr('Interval'), h('div', { class: 'auto-inline' }, every, unit)),
    weekly: h('div', { class: 'plugin-field auto-days' }, h('div', { class: 'plugin-field-head' }, h('span', {}, tr('Days'))), h('div', { class: 'day-chips' }, days)),
    time: field(tr('Time'), time),
    once: field(tr('Date and time'), at),
    cron: field(tr('Cron expression'), expr, tr('Five fields: minute, hour, day of month, month, day of week.')),
    tz: field(tr('Time zone'), tz),
  };
  const read = () => ({ kind: kind.value, n: every.value, unit: unit.value, time: time.value, days: days.map((l) => l.firstChild).filter((b) => b.checked).map((b) => Number(b.value)), at: at.value, expr: expr.value, tz: tz.value });

  const previewEl = h('div', { class: 'auto-preview' });
  let previewTimer = 0;
  let previewSeq = 0;
  viewCleanups.push(() => clearTimeout(previewTimer));
  const preview = async () => {
    const seq = ++previewSeq;
    const note = (text) => previewEl.replaceChildren(h('p', { class: 'market-note' }, text));
    let s;
    try { s = scheduleFromForm(read()); } catch (err) { note(err.message); return; }
    try {
      const { next } = await post('/v1/automations/preview', s);
      if (seq !== previewSeq) return;
      if (!next.length) { note(s.kind === 'at' ? tr('This time has already passed') : tr('The schedule never fires')); return; }
      previewEl.replaceChildren(h('p', { class: 'row-desc' }, tr('Next runs: {0}', next.map((x) => fmtTime(x, s.tz)).join(' · '))));
    } catch (err) {
      if (err instanceof AuthError) fail(err);
      else if (seq === previewSeq) note(err.message);
    }
  };

  const devs = data.devices;
  const fallback = devs.find((d) => d.id === state.gateway?.target_id && d.online) || devs.find((d) => d.online) || devs[0];
  const device = h('select', { 'aria-label': tr('Device') },
    a && !devs.some((d) => d.id === a.target_id) ? h('option', { value: a.target_id, selected: true, disabled: true }, a.target_name || a.target_id) : null,
    devs.map((d) => h('option', { value: d.id, selected: d.id === (a?.target_id || fallback?.id) }, d.online ? d.name : `${d.name} · ${tr('offline')}`)));
  const modeSel = h('select', { 'aria-label': tr('Access mode') }, Object.entries(MODES).map(([k, m]) => h('option', { value: k, selected: k === (a?.mode || 'ask') }, m.label)));
  const modeHint = h('span', {});
  const syncMode = () => {
    const full = modeSel.querySelector('[value="full"]');
    full.disabled = !devs.find((d) => d.id === device.value)?.full_access;
    if (full.disabled && modeSel.value === 'full') modeSel.value = 'ask';
    modeHint.textContent = [MODES[modeSel.value].desc, full.disabled ? tr('Full access is off on this device.') : null].filter(Boolean).join(' ');
  };
  device.addEventListener('change', syncMode);
  modeSel.addEventListener('change', syncMode);
  syncMode();

  const modelSel = h('select', { 'aria-label': tr('Model') }, h('option', { value: '' }, defaultModel() ? tr('{0} (default)', defaultModel()) : tr('default')));
  // An option value is "provider\nmodel"; the empty one follows the default model.
  const saved = a?.model ? `${a.provider || defaultProvider()}\n${a.model}` : '';
  loadModels().then((groups) => {
    for (const g of groups) {
      const ids = g.models.map((m) => m.id);
      if (saved.startsWith(`${g.provider_id}\n`) && !ids.includes(a.model)) ids.unshift(a.model);
      if (ids.length) modelSel.append(h('optgroup', { label: g.provider_id !== g.kind ? `${g.title} (${g.provider_id})` : g.title }, ids.map((x) => h('option', { value: `${g.provider_id}\n${x}` }, modelLabel(x)))));
    }
    modelSel.value = saved;
  }).catch(() => {});
  const timeout = h('input', { type: 'number', min: 1, max: 1440, step: 1, value: Math.round((a?.timeout_s || 3600) / 60), 'aria-label': tr('Time limit, min') });
  let notify = a ? a.notify : true;
  let dropAfter = a?.delete_after_run || false;
  const dropLabel = h('label', { class: 'switch-label' }, toggleSwitch(dropAfter, { label: tr('Delete after the run'), onChange: async (v) => { dropAfter = v; } }), tr('Delete after the run'));

  const sync = () => {
    const k = kind.value;
    fields.every.classList.toggle('hidden', k !== 'every');
    fields.weekly.classList.toggle('hidden', k !== 'weekly');
    fields.time.classList.toggle('hidden', k !== 'daily' && k !== 'weekly');
    fields.once.classList.toggle('hidden', k !== 'once');
    fields.cron.classList.toggle('hidden', k !== 'cron');
    fields.tz.classList.toggle('hidden', k === 'every');
    dropLabel.classList.toggle('hidden', k !== 'once');
    clearTimeout(previewTimer);
    previewTimer = setTimeout(preview, 300);
  };
  const scheduleForm = h('div', { class: 'plugin-form' },
    h('div', { class: 'plugin-grid' }, field(tr('Repeat'), kind), fields.tz),
    h('div', { class: 'plugin-grid' }, fields.every, fields.weekly, fields.time, fields.once, fields.cron),
    previewEl);
  scheduleForm.addEventListener('input', sync);
  scheduleForm.addEventListener('change', sync);
  sync();

  const save = h('button', { class: 'btn btn-primary', onclick: async () => {
    if (!name.value.trim()) { name.focus(); return; }
    if (!prompt.value.trim()) { prompt.focus(); return; }
    save.disabled = true;
    try {
      const payload = {
        name: name.value.trim(),
        prompt: prompt.value.trim(),
        schedule: scheduleFromForm(read()),
        target_id: device.value,
        mode: modeSel.value,
        provider: modelSel.value ? modelSel.value.split('\n')[0] : null,
        model: modelSel.value ? modelSel.value.split('\n')[1] : null,
        timeout_s: Math.min(1440, Math.max(1, Math.round(Number(timeout.value) || 60))) * 60,
        notify,
        delete_after_run: kind.value === 'once' && dropAfter,
      };
      if (a) await api(`/v1/automations/${a.id}`, { method: 'PUT', body: JSON.stringify(payload) });
      else await post('/v1/automations', payload);
      toast(tr('Saved'));
      go('#/automations');
    } catch (err) { fail(autoError(err)); } finally { save.disabled = false; }
  } }, a ? tr('Save') : tr('Create'));
  const remove = a ? h('button', { class: 'btn btn-danger', onclick: async () => {
    if (!await confirmDialog({ title: tr('Delete “{0}”?', a.name), text: tr('The schedule and its run log are deleted. A run in progress is stopped.'), action: tr('Delete'), danger: true })) return;
    try { await del(`/v1/automations/${a.id}`); toast(tr('Automation deleted')); go('#/automations'); } catch (err) { fail(err); }
  } }, icon('trash'), tr('Delete')) : null;

  let runsHost = null;
  let runBtn = null;
  if (a) {
    runsHost = h('div', {});
    let running = a.running;
    let starting = false;
    let shown = '';
    const renderRuns = (runs) => {
      running = runs.some((r) => r.status === 'running');
      runBtn.disabled = starting || running;
      const key = JSON.stringify(runs) + Math.floor(Date.now() / 60000);
      if (key === shown) return;
      shown = key;
      runsHost.replaceChildren(runs.length ? h('div', { class: 'rows runs' }, runs.map(runRow)) : h('div', { class: 'empty rows' }, tr('No runs yet.')));
    };
    const loadRuns = async () => renderRuns(await get(`/v1/automations/${a.id}/runs`));
    runBtn = h('button', { class: 'btn', disabled: running, onclick: async () => {
      starting = true;
      runBtn.disabled = true;
      await runAutomation(a.id);
      starting = false;
      await loadRuns().catch(() => {});
    } }, icon('play'), tr('Run now'));
    renderRuns(a.runs);
    const iv = setInterval(() => loadRuns().catch(() => {}), 5000);
    viewCleanups.push(() => clearInterval(iv));
  }

  const desc = a
    ? [a.enabled && a.next_run_at ? tr('Next run {0}', inTime(a.next_run_at)) : nextText(a), createdBy(a)].filter(Boolean).join(' · ')
    : tr('The agent runs the prompt on schedule, each run in its own chat.');
  page(shell, a ? a.name : tr('New automation'), desc, runBtn,
    section(tr('Task'), null, h('div', { class: 'plugin-form' },
      field(tr('Name'), name),
      field(tr('Prompt'), prompt, tr('Each run starts from this text alone, with no memory of earlier runs or chats, so put everything the agent needs here.')))),
    section(tr('Schedule'), null, scheduleForm),
    section(tr('Where and how'), null, h('div', { class: 'plugin-form' },
      h('div', { class: 'plugin-grid' }, field(tr('Device'), device), field(tr('Access mode'), modeSel, modeHint)),
      h('div', { class: 'plugin-grid' }, field(tr('Model'), modelSel), field(tr('Time limit, min'), timeout, tr('A run that takes longer is stopped.'))),
      data.telegram_ready ? h('label', { class: 'switch-label' }, toggleSwitch(notify, { label: tr('Send the result to Telegram'), onChange: async (v) => { notify = v; } }), tr('Send the result to Telegram')) : null,
      dropLabel)),
    h('div', { class: 'auto-actions' }, remove, h('span', { class: 'spacer' }), h('a', { class: 'btn', href: '#/automations' }, tr('Cancel')), save),
    a ? section(tr('Runs'), null, runsHost) : null,
  );
  if (!a) name.focus();
}

// ---------- projects ----------

// A base worth naming: a branch, not the device state or the not-yet-resolved main branch.
const baseName = (ref) => (ref && !['snapshot', 'default'].includes(ref) ? ref : null);

const diffStat = (s) => (s?.files
  ? h('span', { class: 'change-stat', title: tp('{0} file|{0} files', s.files) }, h('span', { class: 'add' }, `+${s.added}`), h('span', { class: 'del' }, `−${s.deleted}`))
  : null);

// The files a project chat changed since it started, in a side panel behind a topbar button; each opens its diff.
function changesPanel(taskId) {
  // On a phone the panel covers the chat, so it opens only by hand there.
  let open = localStorageGet('changesOpen') === '1' && matchMedia('(min-width: 861px)').matches;
  let data = null;
  let error = '';
  let busy = false;
  let again = false;
  let timer = 0;
  viewCleanups.push(() => clearTimeout(timer));
  const count = h('span', { class: 'change-stat hidden' });
  const btn = h('button', { class: 'icon-btn changes-btn', title: tr('Changes'), 'aria-label': tr('Changes'), onclick: () => toggle() }, icon('panelRight'), count);
  const sum = h('div', { class: 'changes-sum' });
  const list = h('div', { class: 'changes-list' });
  const el = h('aside', { class: 'changes', 'aria-label': tr('Changes') },
    h('div', { class: 'changes-head' }, h('h2', {}, tr('Changes')),
      h('button', { class: 'icon-btn', title: tr('Refresh'), 'aria-label': tr('Refresh'), onclick: () => load() }, icon('refresh')),
      h('button', { class: 'icon-btn', title: tr('Close'), 'aria-label': tr('Close'), onclick: () => toggle(false) }, icon('x'))),
    sum, list);

  const toggle = (value = !open) => {
    open = value;
    localStorageSet('changesOpen', open ? '1' : '0');
    el.classList.toggle('hidden', !open);
    btn.classList.toggle('active', open);
    btn.setAttribute('aria-expanded', String(open));
    if (open) load();
  };
  const stat = (f) => (f.binary ? [h('span', { class: 'change-bin' }, tr('binary'))] : [h('span', { class: 'add' }, `+${f.added}`), h('span', { class: 'del' }, `−${f.deleted}`)]);
  const render = () => {
    const files = data?.files || [];
    const added = files.reduce((n, f) => n + f.added, 0);
    const deleted = files.reduce((n, f) => n + f.deleted, 0);
    count.replaceChildren(h('span', { class: 'add' }, `+${added}`), h('span', { class: 'del' }, `−${deleted}`));
    count.classList.toggle('hidden', !files.length);
    btn.title = files.length ? `${tr('Changes')} · ${tp('{0} file|{0} files', files.length)}` : tr('Changes');
    sum.replaceChildren(...(files.length ? [tp('{0} file|{0} files', files.length), h('span', { class: 'add' }, `+${added}`), h('span', { class: 'del' }, `−${deleted}`)] : []));
    if (error) { list.replaceChildren(h('div', { class: 'changes-empty' }, error)); return; }
    if (!data) { list.replaceChildren(h('div', { class: 'changes-empty' }, tr('Loading...'))); return; }
    if (!data.ready) { list.replaceChildren(h('div', { class: 'changes-empty' }, tr('The working copy is not ready yet.'))); return; }
    list.replaceChildren(...(files.length
      ? files.map((f) => {
        const cut = f.path.lastIndexOf('/');
        return h('button', { class: 'change-row', title: f.path, onclick: () => openDiff(taskId, f, stat, load) },
          h('span', { class: `change-st st-${f.status}` }, f.status),
          h('span', { class: 'change-path' }, cut >= 0 ? h('span', { class: 'change-dir' }, f.path.slice(0, cut + 1)) : null, h('span', { class: 'change-name' }, f.path.slice(cut + 1))),
          h('span', { class: 'change-stat' }, ...stat(f)));
      })
      : [h('div', { class: 'changes-empty' }, tr('No changes yet.'))]),
    data.truncated ? h('div', { class: 'changes-empty' }, tr('Only the first {0} files are shown.', files.length)) : '');
  };
  async function load() {
    if (busy) { again = true; return; }
    busy = true;
    try { data = await get(`/v1/tasks/${taskId}/changes`); error = ''; } catch (err) {
      if (err instanceof AuthError) { fail(err); return; }
      error = err.message;
    } finally { busy = false; }
    render();
    if (again) { again = false; load(); }
  }
  // Tool results refresh an open panel; the end-of-turn commit also refreshes the counter on the button.
  const later = (always = false) => {
    if (!open && !always) return;
    clearTimeout(timer);
    timer = setTimeout(load, 1200);
  };
  toggle(open);
  if (!open) load();
  return { el, btn, later };
}

async function openDiff(taskId, f, stat, onChange) {
  const body = h('div', { class: 'diff-body' }, h('div', { class: 'changes-empty' }, tr('Loading...')));
  const cut = f.path.lastIndexOf('/');
  let patch = '';
  const copyDiff = h('button', { class: 'icon-btn', title: tr('Copy the diff'), 'aria-label': tr('Copy the diff'), disabled: true, onclick: (e) => copy(patch, e.currentTarget) }, icon('copy'));
  const revert = h('button', { class: 'btn btn-sm btn-danger', onclick: async () => {
    const yes = await confirmDialog({
      title: tr('Revert the changes to {0}?', f.path.slice(cut + 1)),
      text: f.status === 'A' ? tr('The file was created in this chat and will be deleted.') : tr('The file goes back to how it was when the chat started.'),
      action: tr('Revert'),
      danger: true,
    });
    if (!yes) return;
    try {
      await post(`/v1/tasks/${taskId}/changes/revert`, { path: f.path });
      toast(tr('Changes reverted'));
      onChange();
    } catch (err) { fail(err); }
  } }, icon('refresh'), tr('Revert'));
  openModal(
    h('div', { class: 'modal-head diff-head' },
      h('h2', { title: f.path }, cut >= 0 ? h('span', { class: 'change-dir' }, f.path.slice(0, cut + 1)) : null, f.path.slice(cut + 1)),
      h('span', { class: 'change-stat' }, ...stat(f)),
      copyDiff, revert,
      h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
    body,
  ).classList.add('modal-diff');
  try {
    const r = await get(`/v1/tasks/${taskId}/changes?path=${encodeURIComponent(f.path)}`);
    patch = r.patch || '';
    copyDiff.disabled = !patch;
    body.replaceChildren(...diffLines(r.patch || ''), r.truncated ? h('div', { class: 'changes-empty' }, tr('The diff is too long; only its beginning is shown.')) : '');
  } catch (err) {
    if (err instanceof AuthError) { fail(err); return; }
    body.replaceChildren(h('div', { class: 'changes-empty' }, err.message));
  }
}

// A unified diff as rows with old and new line numbers; the git header lines above the first hunk are dropped.
function diffLines(patch) {
  if (!patch.includes('\n@@')) {
    return [h('div', { class: 'changes-empty' }, /^Binary files /m.test(patch) ? tr('A binary file: its contents are not shown.') : tr('No changes in this file.'))];
  }
  const rows = [];
  let a = 0;
  let b = 0;
  let started = false;
  for (const line of patch.replace(/\n$/, '').split('\n')) {
    const m = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (m) {
      started = true;
      a = Number(m[1]);
      b = Number(m[2]);
      rows.push(h('div', { class: 'dl hunk' }, h('span', { class: 'ln' }), h('span', { class: 'ln' }), h('span', { class: 'dt' }, line)));
    } else if (!started) {
      continue;
    } else if (line.startsWith('\\')) {
      rows.push(h('div', { class: 'dl meta' }, h('span', { class: 'ln' }), h('span', { class: 'ln' }), h('span', { class: 'dt' }, line)));
    } else {
      const ch = line[0];
      const cls = ch === '+' ? 'add' : ch === '-' ? 'del' : 'same';
      rows.push(h('div', { class: `dl ${cls}` },
        h('span', { class: 'ln' }, ch === '+' ? '' : String(a++)),
        h('span', { class: 'ln' }, ch === '-' ? '' : String(b++)),
        h('span', { class: 'dt' }, line || ' ')));
    }
  }
  return [h('div', { class: 'diff' }, rows)];
}

// Same rule as BRANCH_RE on the Core: a conservative subset of git check-ref-format.
const BRANCH_OK = /^(?![-/.])(?!.*\.\.)(?!.*\/\/)(?!.*\/\.)(?!.*@\{)(?!.*\.lock(\/|$))[A-Za-z0-9._/+-]+(?<![./])$/;

// The branch a new repo chat starts from: empty starts a new branch from the project's default one, a listed branch
// is the start of a new chat branch, any other name becomes a new branch from the default one.
function branchField(data, { onEnter, onChange }) {
  const { branches, main, repoMain, current } = data;
  const known = (name) => branches.some((b) => b.name === name);
  const input = h('input', { type: 'text', maxlength: 200, spellcheck: 'false', autocapitalize: 'off', placeholder: tr('Branch or new branch name'), 'aria-label': tr('Branch') });
  const status = h('div', { class: 'ws-status' });
  const list = h('div', { class: 'ws-list', role: 'listbox' });
  const describe = (name) => (!name
    ? tr('The chat gets its own new branch from {0}.', main)
    : known(name) ? tr('The chat gets its own new branch from {0}.', name)
      : BRANCH_OK.test(name) ? tr('A new branch {0} is created from {1}.', name, main)
        : tr('This is not a valid branch name.'));
  const valid = () => { const q = input.value.trim(); return !q || known(q) || BRANCH_OK.test(q); };
  const tags = (b) => [
    b.name === repoMain ? h('span', { class: 'pill tag-kind' }, tr('main')) : null,
    b.name === main && main !== repoMain ? h('span', { class: 'pill tag-kind' }, tr('default')) : null,
    !b.remote && b.name === current ? h('span', { class: 'pill tag-kind' }, tr('on the device')) : null,
  ];
  const refresh = () => {
    const q = input.value.trim();
    const isNew = Boolean(q && !known(q));
    status.replaceChildren(isNew && valid() ? h('span', { class: 'pill accent' }, tr('new branch')) : '', h('span', {}, describe(q)));
    status.classList.toggle('bad', !valid());
    const shown = branches.filter((b) => !q || b.name.toLowerCase().includes(q.toLowerCase())).slice(0, 100);
    list.replaceChildren(...(shown.length
      ? shown.map((b) => h('button', { class: `ws-item${b.name === q ? ' selected' : ''}`, type: 'button', role: 'option', onclick: () => { input.value = b.name; refresh(); onChange(); } },
        icon('git'), h('span', { class: `ws-name${b.remote ? ' remote' : ''}` }, b.name), ...tags(b).filter(Boolean)))
      : [h('div', { class: 'empty' }, tr('No branches match.'))]));
  };
  input.addEventListener('input', () => { refresh(); onChange(); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); if (valid()) onEnter(); } });
  refresh();
  return {
    el: h('div', { class: 'ws-field' }, input, status, list),
    input,
    valid,
    value: () => { const q = input.value.trim(); return !q ? {} : known(q) ? { base: q } : { branch: q }; },
  };
}

// A new chat in a repo project: whether it gets its own workspace and from which branch; the chat is created
// empty and opened, the task is written there.
function openProjectChat(project) {
  const source = devices().find((t) => t.id === project.source_target_id);
  let workspace = true;
  let field = null;
  const hint = h('p', { class: 'row-desc ws-hint' });
  const branchBox = h('div', { class: 'ws-field' }, h('div', { class: 'changes-empty' }, tr('Loading...')));
  const problem = h('p', { class: 'browser-error', role: 'alert' });
  const create = h('button', { class: 'btn btn-primary' }, tr('Create chat'));
  const sync = () => {
    hint.textContent = workspace
      ? tr('The chat works in its own copy of the repository on a new branch, so your checkout stays as it is.')
      : tr('The agent works right in the project folder {0}: its edits land in your files at once, with no branch of its own.', project.source_path);
    (field?.el || branchBox).classList.toggle('hidden', !workspace);
    create.disabled = source?.status !== 'online' || (workspace && field && !field.valid());
  };
  const wsSwitch = toggleSwitch(true, { label: tr('Create a workspace'), onChange: async (v) => { workspace = v; sync(); } });
  const wsRow = h('label', { class: 'switch-label ws-toggle' }, wsSwitch, tr('Create a workspace'));
  create.addEventListener('click', async () => {
    create.disabled = true;
    const full = localStorageGet('mode') === 'full' && fullAccessOf(source) === 'allowed';
    try {
      const task = await post('/v1/tasks', {
        target_id: project.source_target_id, input: '', project_id: project.id, mode: full ? 'full' : 'ask',
        workspace, ...(workspace ? field?.value() : {}),
      });
      state.tasks.unshift(task);
      go(`#/chat/${task.id}`);
    } catch (err) { fail(err); sync(); }
  });
  const modal = openModal(
    h('div', { class: 'modal-head' }, h('h2', {}, tr('New chat in “{0}”', project.name)), h('button', { class: 'icon-btn', onclick: clearLayer, 'aria-label': tr('Close') }, icon('x'))),
    wsRow, hint, branchBox, problem,
    h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: clearLayer }, tr('Cancel')), create),
  );
  modal.classList.add('modal-wide');
  if (source?.status !== 'online') problem.textContent = tr('“{0}” is offline. Turn it on to start a chat in this project.', project.source_name || project.source_target_id);
  sync();
  get(`/v1/projects/${project.id}/branches`).then((r) => {
    if (!modal.isConnected) return;
    field = branchField({ branches: r.branches || [], main: r.default, repoMain: r.main || r.default, current: r.current }, { onEnter: () => create.click(), onChange: sync });
    branchBox.replaceWith(field.el);
    sync();
    field.input.focus();
  }, (err) => {
    if (!modal.isConnected) return;
    // An older client can neither list branches nor work in the folder: the chat gets a workspace from the main branch.
    branchBox.remove();
    wsRow.remove();
    if (source?.status === 'online') problem.textContent = /outdated/.test(err.message) ? tr('Update the Mensarium client on “{0}” to pick a branch or work without a workspace; until then the chat starts from the main branch.', project.source_name || '') : err.message;
  });
}

// Keeps the sidebar's copy of a project in step with a fresher detail view (the list carries a chat count, not the chats).
function rememberProject(view) {
  const entry = { ...view, chats: Array.isArray(view.chats) ? view.chats.length : view.chats };
  state.projects = state.projects.some((x) => x.id === view.id) ? state.projects.map((x) => (x.id === view.id ? entry : x)) : [...state.projects, entry];
  return entry;
}

async function viewProjectNew() {
  const shell = ensureAppShell();
  shell.setActive(null);
  const data = await get('/v1/projects');
  state.projects = data.items;
  const title = tr('New project');
  const desc = tr('A folder on one of your devices, or a git repository cloned on the Core host. Every chat in the project works in its own copy, so chats never disturb each other or your files.');
  const usable = data.devices.filter((d) => d.online && d.projects);
  const coreDevice = data.devices.find((d) => state.targets.some((t) => t.id === d.id && t.core_host)) || null;
  if (!usable.length && !coreDevice) {
    page(shell, title, desc, null, h('div', { class: 'empty rows' }, tr('No online device supports projects yet. Update the Mensarium client on the device you need.')));
    return;
  }
  const preferred = usable.find((d) => d.id === state.gateway?.target_id) || usable[0] || coreDevice;
  const device = h('select', { 'aria-label': tr('Device') }, data.devices.map((d) => h('option', { value: d.id, disabled: !d.online || !d.projects, selected: d.id === preferred.id },
    !d.online ? `${d.name} · ${tr('offline')}` : !d.projects ? `${d.name} · ${tr('update the client')}` : d.name)));

  const pathEl = h('code', { class: 'browser-path' });
  const errorEl = h('p', { class: 'browser-error', role: 'alert' });
  const list = h('div', { class: 'rows browser-list' });
  const up = h('button', { class: 'btn btn-sm', disabled: true, onclick: () => browse(cur.parent) }, icon('arrowUp'), tr('Up'));
  const use = h('button', { class: 'btn btn-sm', disabled: true, onclick: () => choose() }, icon('check'), tr('Use this folder'));
  const chosenBox = h('div', { class: 'browser-chosen' });
  const name = h('input', { type: 'text', maxlength: 120, 'aria-label': tr('Name') });
  const url = h('input', { type: 'text', maxlength: 1000, placeholder: 'https://github.com/user/repo.git', spellcheck: 'false', autocapitalize: 'off', 'aria-label': tr('Repository address') });
  let cur = null;
  let chosen = null;
  let autoName = '';
  let seq = 0;
  let mode = usable.length ? 'folder' : 'git';

  // A failed listing keeps the last good folder on screen, so the user can go up or pick it.
  const browse = async (path) => {
    const n = ++seq;
    up.disabled = true;
    use.disabled = true;
    errorEl.textContent = '';
    if (cur) list.classList.add('loading');
    else list.replaceChildren(h('div', { class: 'empty rows' }, tr('Loading...')));
    try {
      const r = await post('/v1/projects/browse', { target_id: device.value, path });
      if (n !== seq) return;
      cur = r;
      pathEl.textContent = r.path;
      up.disabled = !r.parent;
      use.disabled = false;
      list.classList.remove('loading');
      list.replaceChildren(...(r.entries.length
        ? r.entries.map((e) => h('button', { class: 'browser-item', onclick: () => browse(e.path) },
          icon(e.git ? 'git' : 'folder'), h('span', { class: 'browser-name' }, e.name), e.git ? h('span', { class: 'pill tag-kind' }, 'git') : null))
        : [h('div', { class: 'empty rows' }, tr('No subfolders here.'))]));
    } catch (err) {
      if (n !== seq) return;
      if (err instanceof AuthError) { fail(err); return; }
      // The home folder may be outside the device's allowed folders: start from the first allowed one.
      const root = state.targets.find((t) => t.id === device.value)?.capabilities?.roots?.[0];
      if (err.status === 409 && path === '~' && root) { browse(root); return; }
      errorEl.textContent = err.message;
      up.disabled = !cur?.parent;
      use.disabled = !cur;
      list.classList.remove('loading');
      if (!cur) list.replaceChildren(h('div', { class: 'empty rows' }, h('button', { class: 'btn btn-sm', onclick: () => browse(path) }, icon('refresh'), tr('Retry'))));
    }
  };

  const choose = () => {
    if (!cur) return;
    chosen = { target_id: device.value, path: cur.path, kind: cur.git ? 'repo' : 'folder' };
    if (!name.value.trim() || name.value === autoName) {
      autoName = cur.path.split(/[\\/]/).filter(Boolean).pop() || cur.path;
      name.value = autoName;
    }
    chosenBox.replaceChildren(
      h('div', { class: 'browser-chosen-head' }, icon(KIND_ICON[chosen.kind]), h('code', {}, chosen.path), h('span', { class: 'pill tag-kind' }, kindLabel(chosen))),
      h('div', { class: 'row-desc' }, chosen.kind === 'repo'
        ? tr('Secret files such as .env and keys are left out of chat copies, but anything already committed to the repository history stays visible to the agent.')
        : tr('Secret files such as .env and keys are left out, and so are files over {0} MB. To leave out more, list them in a .mensariumignore file in the folder.', DEFAULT_FILE_LIMIT_MB)));
    syncCreate();
    name.focus();
  };

  // Same rule as ProjectCreate on the Core: network transports only.
  const gitOk = () => /^(https?:\/\/|ssh:\/\/|git:\/\/)\S+$|^[\w.-]+@[\w.-]+:\S+$/.test(url.value.trim()) && !url.value.trim().startsWith('-');
  const gitReady = () => Boolean(coreDevice?.online && coreDevice?.projects);
  const syncCreate = () => { create.disabled = mode === 'git' ? !(gitReady() && gitOk()) : !chosen; };
  url.addEventListener('input', () => {
    const repo = url.value.trim().replace(/\/+$/, '').split(/[/:]/).pop()?.replace(/\.git$/, '') || '';
    if (repo && (!name.value.trim() || name.value === autoName)) { autoName = repo; name.value = repo; }
    syncCreate();
  });

  const create = h('button', { class: 'btn btn-primary', disabled: true, onclick: async () => {
    if (!name.value.trim()) { name.focus(); return; }
    const body = mode === 'git'
      ? { name: name.value.trim(), git_url: url.value.trim() }
      : chosen ? { name: name.value.trim(), source_target_id: chosen.target_id, source_path: chosen.path } : null;
    if (!body) return;
    create.disabled = true;
    create.textContent = mode === 'git' ? tr('Cloning…') : tr('Reading the folder…');
    try {
      const p = await post('/v1/projects', body);
      state.projects = await get('/v1/projects').then((r) => r.items, () => [...state.projects, p]);
      go(`#/projects/${p.id}`);
    } catch (err) {
      fail(err);
      syncCreate();
      create.textContent = tr('Create');
    }
  } }, tr('Create'));

  device.addEventListener('change', () => {
    cur = null;
    pathEl.textContent = '';
    chosen = null;
    chosenBox.replaceChildren();
    syncCreate();
    browse('~');
  });

  const folderForm = h('div', { class: 'plugin-form' },
    field(tr('Device'), device),
    h('div', { class: 'plugin-field' }, h('div', { class: 'plugin-field-head' }, h('span', {}, tr('Folder'))),
      h('div', { class: 'browser' }, h('div', { class: 'browser-bar' }, up, pathEl, use), errorEl, list)),
    chosenBox);
  const gitNote = coreDevice && gitReady()
    ? h('div', { class: 'row-desc' }, tr('Cloned on the Core host ({0}) with the git access set up there: a private repository needs its ssh address (git@github.com:user/repo.git) and an ssh key on that machine. Secret files are left out of chat copies, but anything committed to the history stays visible to the agent.', coreDevice.name))
    : h('p', { class: 'browser-error', role: 'alert' }, coreDevice ? tr('The Core device is offline or its git is missing; install git on the Core host.') : tr('The Core has no device of its own; enable it in the Core config.'));
  const gitForm = h('div', { class: 'plugin-form' }, field(tr('Repository address'), url), gitNote);
  const modeBox = h('div', {});
  const tile = (key, ic, label, hint, enabled) => h('button', { class: 'source-tile', type: 'button', disabled: !enabled, title: enabled ? null : hint, onclick: () => { mode = key; render(); } }, icon(ic), h('span', { class: 'source-tile-label' }, label), h('span', { class: 'source-tile-hint' }, hint));
  const tiles = h('div', { class: 'source-tiles' });
  const render = () => {
    tiles.replaceChildren(
      tile('folder', 'folder', tr('Choose a folder'), tr('on one of your devices'), usable.length > 0),
      tile('git', 'git', tr('Git repository'), tr('cloned on the Core host'), Boolean(coreDevice)));
    tiles.children[mode === 'git' ? 1 : 0].classList.add('active');
    modeBox.replaceChildren(mode === 'git' ? gitForm : folderForm);
    syncCreate();
    if (mode === 'git') url.focus();
    else if (!cur) browse('~');
  };

  page(shell, title, desc, null,
    h('div', { class: 'plugin-form' }, tiles, modeBox, field(tr('Name'), name)),
    h('div', { class: 'auto-actions' }, h('span', { class: 'spacer' }), h('a', { class: 'btn', href: '#/' }, tr('Cancel')), create));
  render();
}

async function viewProject(id) {
  const shell = ensureAppShell();
  shell.setActive(null);
  let p;
  try { p = await get(`/v1/projects/${id}`); } catch (err) { fail(err); go('#/'); return; }
  const body = h('div', {});
  // The name turns into a field on click; Enter or leaving the field saves it, Escape keeps the old one.
  const titleEl = h('span', { class: 'title-edit', role: 'button', tabindex: '0', title: tr('Rename') });
  let editing = false;
  const rename = () => {
    if (editing) return;
    editing = true;
    const input = h('input', { type: 'text', class: 'title-input', maxlength: 120, value: p.name, 'aria-label': tr('Name') });
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      const name = input.value.trim();
      if (save && name && name !== p.name) {
        try { show({ ...(await api(`/v1/projects/${id}`, { method: 'PUT', body: JSON.stringify({ name }) })), chats: p.chats }); } catch (err) { fail(err); }
      }
      editing = false;
      titleEl.textContent = p.name;
      input.replaceWith(titleEl);
    };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false); }
    });
    input.addEventListener('blur', () => finish(true));
    titleEl.replaceWith(input);
    input.focus();
    input.select();
  };
  titleEl.addEventListener('click', rename);
  titleEl.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); rename(); } });
  // A repo chat starts in a modal over this page; a folder chat has its own page.
  const startChat = (e) => { if (p.kind === 'repo') { e.preventDefault(); openProjectChat(p); } };
  const newChatBtn = h('a', { class: 'btn btn-primary', href: `#/projects/${id}/new`, onclick: startChat }, icon('plus'), tr('New chat'));
  // Cleared on leaving the page and right after a delete, so a late poll cannot bring the project back.
  let alive = true;
  viewCleanups.push(() => { alive = false; });
  const deleteBtn = h('button', { class: 'btn btn-danger', onclick: () => deleteProject(p, () => { alive = false; }) }, icon('trash'), tr('Delete'));
  // Source details live in a modal behind the small exclamation-mark button in the page actions.
  const infoBody = h('div', { class: 'rows' });
  const fillInfo = (...rows) => { infoBody.replaceChildren(...rows.flat().filter(Boolean)); return null; };
  const infoBtn = h('button', { class: 'icon-btn', title: tr('About the project'), 'aria-label': tr('About the project'), onclick: () => openInfo() }, icon('exclaim'));
  const openInfo = () => {
    const limit = 20000;
    const text = h('textarea', { class: 'market-yaml project-instructions', rows: 7, maxlength: limit, spellcheck: 'false', 'aria-label': tr('Project instructions'),
      placeholder: tr('For example: run the tests with make test before finishing; do not change the migrations.') });
    text.value = p.instructions || '';
    const count = h('span', { class: 'row-desc' });
    const save = h('button', { class: 'btn btn-sm btn-primary', disabled: true }, tr('Save'));
    const sync = () => {
      count.textContent = tr('{0} / {1} characters', text.value.length.toLocaleString(locale), limit.toLocaleString(locale));
      save.disabled = text.value.trim() === (p.instructions || '');
    };
    text.addEventListener('input', sync);
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        show({ ...(await api(`/v1/projects/${id}`, { method: 'PUT', body: JSON.stringify({ instructions: text.value }) })), chats: p.chats });
        text.value = p.instructions || '';
        toast(tr('Saved'));
      } catch (err) { fail(err); }
      sync();
    });
    sync();
    const docs = h('div', { class: 'rows' }, h('div', { class: 'empty rows' }, tr('Loading...')));
    const docRow = (f) => {
      const body = h('pre', { class: 'project-doc hidden' }, f.text, f.truncated ? '\n…' : '');
      const toggle = h('button', { class: 'btn btn-sm', onclick: () => {
        body.classList.toggle('hidden');
        toggle.textContent = body.classList.contains('hidden') ? tr('Show') : tr('Hide');
      } }, tr('Show'));
      return h('div', { class: 'project-doc-row' },
        h('div', { class: 'row' }, h('div', { class: 'row-text' }, h('div', { class: 'row-title' }, h('code', {}, f.name)), h('div', { class: 'row-desc' }, fmtBytes(f.size))), h('div', { class: 'row-value' }, toggle)),
        body);
    };
    const baseBox = h('div', {}, h('div', { class: 'row-desc' }, tr('Loading...')));
    if (p.kind === 'repo') {
      get(`/v1/projects/${id}/branches`).then((r) => {
        const chosen = p.default_base && !['snapshot', 'default'].includes(p.default_base) ? p.default_base : 'default';
        const names = (r.branches || []).map((b) => b.name);
        if (chosen !== 'default' && !names.includes(chosen)) names.unshift(chosen);
        const select = h('select', { class: 'base-select', 'aria-label': tr('Branch for new chats') },
          h('option', { value: 'default', selected: chosen === 'default' }, tr('Main branch ({0})', r.main || r.default || '—')),
          names.map((n) => h('option', { value: n, selected: n === chosen }, n)));
        select.addEventListener('change', async () => {
          select.disabled = true;
          try {
            show({ ...(await api(`/v1/projects/${id}`, { method: 'PUT', body: JSON.stringify({ default_base: select.value }) })), chats: p.chats });
            toast(tr('Saved'));
          } catch (err) { fail(err); }
          select.disabled = false;
        });
        baseBox.replaceChildren(select);
      }, (err) => baseBox.replaceChildren(h('div', { class: 'row-desc' }, err.message)));
    }
    get(`/v1/projects/${id}/docs`).then(
      (r) => docs.replaceChildren(...(r.files.length ? r.files.map(docRow) : [h('div', { class: 'empty rows' }, tr('No AGENTS.md or CLAUDE.md in the project folder.'))])),
      (err) => docs.replaceChildren(h('div', { class: 'empty rows' }, err.message)));
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, tr('About the project')), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': tr('Close') }, icon('x'))),
      infoBody,
      p.kind === 'repo' ? h('div', { class: 'info-section' },
        h('h3', {}, tr('Branch for new chats')),
        h('p', { class: 'row-desc' }, tr('A new chat gets its own branch from this one unless you pick another when you start it.')),
        baseBox) : null,
      h('div', { class: 'info-section' },
        h('h3', {}, tr('Project instructions')),
        h('p', { class: 'row-desc' }, tr('Added to the system prompt of every chat in this project.')),
        text,
        h('div', { class: 'info-foot' }, count, save)),
      h('div', { class: 'info-section' },
        h('h3', {}, tr('Instruction files in the project')),
        h('p', { class: 'row-desc' }, tr('The agent reads them from its working copy on its own; they are shown here for reference.')),
        docs),
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: closeLayer }, tr('Close'))),
    ).classList.add('modal-wide');
  };
  let shown = '';

  const sync = async (btn) => {
    btn.disabled = true;
    try { await post(`/v1/projects/${id}/sync`); await load(); } catch (err) { fail(err); btn.disabled = false; }
  };

  const chatRow = (t) => {
    const [label, cls, live] = statusOf(t.status);
    return h('div', { class: 'row' },
      h('a', { class: 'row-text', href: `#/chat/${t.id}`, title: t.input },
        h('div', { class: 'row-title' }, h('span', { class: `dot ${cls}${live ? ' live' : ''}`, title: label }), taskTitle(t)),
        p.kind !== 'repo' ? null : t.branch ? h('div', { class: 'row-desc mono' }, [t.branch, baseName(t.base_ref) ? tr('from {0}', t.base_ref) : null].filter(Boolean).join(' · '))
          : h('div', { class: 'row-desc' }, tr('project folder, no workspace'))),
      h('div', { class: 'row-value' }, diffStat(t.diff_stat), relTime(t.updated_at)));
  };

  const render = () => {
    const ready = p.status === 'ready';
    const busy = p.status === 'creating' || p.syncing;
    const chats = Array.isArray(p.chats) ? p.chats : [];
    const skipped = p.skipped || [];
    if (!editing) titleEl.textContent = p.name;
    newChatBtn.classList.toggle('hidden', !ready);
    const reread = busy || !p.source_online ? null
      : h('button', { class: 'icon-btn', title: p.git_url ? tr('Pull from origin and read again') : tr('Read the folder again'), 'aria-label': p.git_url ? tr('Pull from origin and read again') : tr('Read the folder again'), onclick: (e) => sync(e.currentTarget) }, icon('refresh'));
    fillInfo(
      row(tr('Device'), null, [h('span', { class: `dot${p.source_online ? ' ok' : ''}`, title: p.source_online ? null : tr('offline') }), p.source_name || p.source_target_id,
        p.source_online ? null : h('span', { class: 'market-meta' }, tr('offline'))]),
      p.git_url ? row(tr('Repository'), null, p.git_url, true) : null,
      row(p.git_url ? tr('Clone') : tr('Folder'), null, p.source_path, true),
      row(tr('Last read'), null, [relTime(p.last_sync_at), reread]),
      ready && p.kind === 'repo' ? row(tr('Branch on the device'), null, p.default_branch || '—', true) : null,
      skipped.length ? row(tr('Skipped large files'), `${tp('{0} file|{0} files', skipped.length)} · ${tr('over {0} MB each', p.file_limit_mb || DEFAULT_FILE_LIMIT_MB)}`, h('div', { class: 'skipped' }, [...skipped.slice(0, 20), skipped.length > 20 ? '…' : null].filter(Boolean).join('\n')), true) : null);
    body.replaceChildren(...[
      busy ? h('div', { class: 'note-banner busy', role: 'status' }, h('span', { class: 'spinner' }), h('span', {}, p.git_url && !p.snapshot_sha ? tr('Cloning the repository…') : tr('Reading the folder…'))) : null,
      !busy && p.status === 'error'
        ? h('div', { class: 'note-banner', role: 'alert' }, icon('alert'), h('span', {}, p.error || tr('Could not read the folder')),
          p.source_online ? h('button', { class: 'btn btn-sm', onclick: (e) => sync(e.currentTarget) }, icon('refresh'), tr('Retry')) : null)
        : null,
      ready || chats.length
        ? section(tr('Chats'), null, chats.length
          ? h('div', { class: 'rows' }, chats.map(chatRow))
          : h('div', { class: 'empty rows' }, h('p', {}, tr('No chats yet. Start one and the agent will work in its own copy of the project.')),
            h('a', { class: 'btn btn-primary', href: `#/projects/${id}/new`, onclick: startChat }, icon('plus'), tr('New chat'))))
        : null,
    ].filter(Boolean));
  };

  const show = (next) => {
    p = next;
    rememberProject(next);
    const key = JSON.stringify(next) + Math.floor(Date.now() / 60000);
    if (key === shown) return;
    shown = key;
    render();
    shell.renderSessions();
  };
  const load = async () => {
    const next = await get(`/v1/projects/${id}`);
    if (alive) show(next);
  };

  page(shell, titleEl, null, [infoBtn, newChatBtn, deleteBtn], body);
  show(p);
  const iv = setInterval(() => load().catch(() => {}), 3000);
  viewCleanups.push(() => clearInterval(iv));
}

async function deleteProject(p, onDeleted = null) {
  // The hidden history exists only for a folder project that has been read at least once.
  const shadow = p.kind === 'folder' && p.snapshot_sha ? h('input', { type: 'checkbox' }) : null;
  const yes = await confirmDialog({
    title: tr('Delete project “{0}”?', p.name),
    text: p.git_url ? tr('Its chats and the clone on the Core host are deleted. The remote repository is not touched.') : tr('Its chats are deleted too. Files in the source folder are not touched.'),
    action: tr('Delete'),
    danger: true,
    extra: shadow ? h('label', { class: 'check-label modal-check' }, shadow, tr('Also delete the hidden version history of this folder')) : null,
  });
  if (!yes) return;
  try {
    await del(`/v1/projects/${p.id}${shadow?.checked ? '?remove_shadow=1' : ''}`);
    onDeleted?.();
    state.projects = state.projects.filter((x) => x.id !== p.id);
    state.tasks = state.tasks.filter((t) => t.project_id !== p.id);
    toast(tr('Project deleted'));
    go('#/');
  } catch (err) { fail(err); }
}

// ---------- router ----------

function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

async function route() {
  viewCleanups.forEach((fn) => { try { fn(); } catch { /* noop */ } });
  viewCleanups = [];
  clearLayer();
  const hash = location.hash || '#/';
  try {
    let m;
    if ((m = hash.match(/^#\/chat\/([^/]+)$/)) || (m = hash.match(/^#\/tasks\/([^/]+)$/))) await viewChat(m[1]);
    else if (hash === '#/automations') await viewAutomations();
    else if ((m = hash.match(/^#\/automations\/([^/]+)$/))) await viewAutomationEditor(m[1] === 'new' ? null : m[1]);
    else if (hash === '#/projects/new') await viewProjectNew();
    else if ((m = hash.match(/^#\/projects\/([^/]+)\/new$/))) await viewNewChat(m[1]);
    else if ((m = hash.match(/^#\/projects\/([^/]+)$/))) await viewProject(m[1]);
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

let limitsTimer = null;
async function boot() {
  if (!limitsTimer) limitsTimer = setInterval(() => loadLimits(), 60000);
  if (state.gateway === null) await loadGateway();
  if (state.gateway && !state.gateway.online) { setCoreOffline(true); }
  try {
    state.system = await get('/v1/system');
    setCoreOffline(false);
    loadLimits();
    await refreshData();
  } catch (err) {
    if (err instanceof AuthError) { showLogin(); return; }
    if (err?.code !== 'core-offline') toast(err.message, true);
  }
  state.shell = null;
  window.removeEventListener('hashchange', route);
  window.addEventListener('hashchange', route);
  route();
}

boot();
