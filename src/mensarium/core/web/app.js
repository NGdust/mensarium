// Mensarium web UI. Vanilla ES module, no build step, no dependencies.

import { createOrb } from './orb.js';
import { createGraph, graphColor } from './graph.js';

const $app = document.getElementById('app');
const $toasts = document.getElementById('toasts');
const $layer = document.getElementById('layer');

const state = { system: null, targets: [], tasks: [], shell: null, lastChat: '#/' };
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
  if (!res.ok) throw new Error((data && data.detail) || `Ошибка запроса (${res.status})`);
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
  sparkle: '<path d="M12 3c.6 4.2 2.8 6.4 7 7-4.2.6-6.4 2.8-7 7-.6-4.2-2.8-6.4-7-7 4.2-.6 6.4-2.8 7-7z"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  play: '<path d="M7 5v14l12-7z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
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
const ORB_KINDS = { sm: [22, true], md: [72, true], lg: [184, true], '': [28, false], live: [28, true] };
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
  if (!iso) return 'никогда';
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 10) return 'только что';
  if (s < 60) return `${s} с назад`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} мин назад`;
  const hr = Math.round(m / 60);
  if (hr < 24) return `${hr} ч назад`;
  return `${Math.round(hr / 24)} д назад`;
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
  NEW: ['Запуск', 'accent', true],
  VALIDATING: ['Запуск', 'accent', true],
  PLANNING: ['Думает', 'accent', true],
  WAITING_APPROVAL: ['Ждёт решения', 'warn', true],
  EXECUTING: ['Выполняет', 'accent', true],
  OBSERVING: ['Разбирает результат', 'accent', true],
  SUCCEEDED: ['Готово', 'ok', false],
  FAILED: ['Ошибка', 'danger', false],
  FAILED_RECOVERABLE: ['Прервано, можно продолжить', 'danger', false],
  CANCELED: ['Остановлено', '', false],
  PAUSED: ['Пауза', 'warn', false],
};
const REASONS = {
  'paused by user': 'поставлено на паузу',
  'canceled by user': 'остановлено вами',
  'core restarted': 'Core перезапускался, продолжите вручную',
  'target offline': 'устройство не в сети',
  'target revoked': 'доступ устройства отозван',
  'step budget exhausted': 'закончился лимит шагов',
  'tool call budget exhausted': 'закончился лимит действий',
  'wall time budget exhausted': 'закончилось время на задачу',
};
const RISK = {
  read: ['чтение', ''],
  write: ['изменение файлов', 'warn'],
  execute: ['запуск программы', 'orange'],
  network: ['доступ в сеть', 'accent'],
  destructive: ['необратимое действие', 'danger'],
};
const MODES = {
  ask: { label: 'С запросом действий', icon: 'shield', cls: 'accent', desc: 'Чтение сразу. Запуск программ, изменения файлов и сеть ждут вашего подтверждения.' },
  full: { label: 'Полный доступ', icon: 'bolt', cls: 'full', desc: 'Агент выполняет всё без вопросов. Запрещены только sudo и системные настройки.' },
};
const TEMPLATES = [
  ['terminal', 'Почему падают тесты', 'Запусти тесты проекта, найди причину падения и объясни её. Файлы пока не меняй.'],
  ['git', 'Что изменилось', 'Покажи, что изменилось в репозитории с последнего коммита, и кратко опиши изменения.'],
  ['folder', 'Как устроен проект', 'Изучи структуру проекта и расскажи, как он устроен: точки входа, основные модули, как запускать.'],
  ['search', 'Исправить ошибку', 'Найди причину ошибки и предложи минимальное исправление: '],
];
const TOOL_ICON = { 'files.list': 'folder', 'files.read': 'file', 'files.search': 'search', 'git.status': 'git', 'git.diff': 'git', 'shell.exec': 'terminal', 'skills.read': 'book', 'memory.search': 'graph', 'memory.read': 'graph', 'memory.save': 'graph' };
// Marketplace texts are either plain strings or {en, ru} maps.
const txt = (v) => (typeof v === 'string' ? v : (v?.ru || v?.en || ''));
const RESUMABLE = ['PAUSED', 'FAILED_RECOVERABLE'];

const POLICY_REASONS = [
  [/^access to secret files is not allowed$/, () => 'чтение секретных файлов запрещено'],
  [/^unknown tool '(.+)'$/, (m) => `неизвестный инструмент ${m[1]}`],
  [/^tool '(.+)' is not allowed by the active profile$/, (m) => `инструмент ${m[1]} не разрешён профилем`],
  [/^tool '(.+)' is disabled for this device$/, (m) => `инструмент ${m[1]} выключен для этого устройства`],
  [/^target does not support tool '(.+)'$/, (m) => `устройство не поддерживает ${m[1]}`],
  [/^path '(.+)' is outside allowed roots/, (m) => `путь ${m[1]} вне разрешённых папок`],
  [/^program '(.+)' is not in the target command allowlist$/, (m) => `программа ${m[1]} не разрешена на устройстве`],
  [/^shell operators .* are not supported/, () => 'операторы оболочки (|, &&, >) не поддерживаются, команда запускается без shell'],
  [/^`cd` is not supported/, () => 'cd не поддерживается, папка задаётся отдельно'],
  [/^run programs by name, not by path$/, () => 'программу нужно указывать по имени, а не по пути'],
  [/^privileged actions are denied$/, () => 'привилегированные действия запрещены'],
  [/^invalid arguments/, () => 'неверные аргументы'],
];
const EXEC_STATUS = { succeeded: 'успешно', failed: 'ошибка', timeout: 'таймаут', canceled: 'отменено', rejected: 'отклонено устройством' };
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
  ? `Агент на устройстве устарел (v${t.agent_version}). Обновите его командой mensarium update на устройстве.`
  : 'Выключен на устройстве: allow_full_access в его конфиге.');
const devices = () => state.targets.filter((t) => t.status !== 'revoked').sort((a, b) => isLocal(b) - isLocal(a));
const taskTitle = (t) => ((t.input || '').split('\n')[0] || 'Без названия').slice(0, 80);

function statusPill(status) {
  const [label, kind, live] = statusOf(status);
  return h('span', { class: `pill ${kind}` }, h('span', { class: `dot ${kind}${live ? ' live' : ''}` }), label);
}

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
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: () => done(false) }, 'Отмена'), ok),
    );
    $layer.querySelector('.backdrop').addEventListener('click', (e) => { if (e.target === e.currentTarget) resolve(false); });
    ok.focus();
  });
}

async function deleteChat(task) {
  const yes = await confirmDialog({
    title: 'Удалить чат?',
    text: `«${taskTitle(task)}» исчезнет вместе с сообщениями и выводом команд. Если агент ещё работает, задача остановится. Записи в журнале действий сохранятся.`,
    action: 'Удалить',
    danger: true,
  });
  if (!yes) return;
  try {
    await del(`/v1/tasks/${task.id}`);
    state.tasks = state.tasks.filter((t) => t.id !== task.id);
    toast('Чат удалён');
    if (location.hash === `#/chat/${task.id}`) go('#/');
    else state.shell?.renderSessions?.();
  } catch (err) { fail(err); }
}

async function openPairing() {
  const body = h('div', {}, h('p', {}, 'Создаём код...'));
  openModal(
    h('div', { class: 'modal-head' }, h('h2', {}, 'Сопрячь устройство'), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': 'Закрыть' }, icon('x'))),
    body,
  );
  let data;
  try { data = await post('/v1/targets/pairing-codes'); } catch (err) { closeLayer(); fail(err); return; }
  const timer = h('span', {});
  const line = (cmd) => h('div', { class: 'code-line' }, h('code', {}, cmd), h('button', { class: 'icon-btn', 'aria-label': 'Скопировать', onclick: (e) => copy(cmd, e.currentTarget) }, icon('copy')));
  body.replaceChildren(
    h('p', {}, 'Выполните команду на машине, которую хотите подключить. Код одноразовый.'),
    h('div', { class: 'pair-code' }, data.code),
    h('div', { class: 'pair-timer' }, 'Действует ещё ', timer),
    h('div', { class: 'field-label' }, 'Установить и подключить'),
    line(data.install_command),
    h('div', { class: 'field-label' }, 'Если Mensarium уже установлен'),
    line(`${data.pair_command} --root ~/Projects`),
  );
  const expires = new Date(data.expires_at).getTime();
  const tick = () => {
    const left = Math.round((expires - Date.now()) / 1000);
    timer.textContent = left > 0 ? mmss(left) : 'истёк';
    if (left <= 0 || !document.body.contains(timer)) clearInterval(iv);
  };
  const iv = setInterval(tick, 1000);
  tick();
}

// ---------- login ----------

function showLogin() {
  cleanupAll();
  state.shell = null;
  const input = h('input', { type: 'password', placeholder: 'Токен администратора', autocomplete: 'current-password', 'aria-label': 'Токен администратора' });
  const btn = h('button', { class: 'btn btn-primary' }, 'Войти');
  const submit = async () => {
    const token = input.value.trim();
    if (!token) return;
    btn.disabled = true;
    try {
      await post('/v1/auth/login', { token });
      await boot();
    } catch (err) {
      toast(err instanceof AuthError ? 'Неверный токен' : err.message, true);
    } finally { btn.disabled = false; }
  };
  btn.addEventListener('click', submit);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  $app.replaceChildren(h('div', { class: 'login' }, h('div', { class: 'login-card' },
    orb('md'),
    h('h1', {}, 'Mensarium'),
    h('p', {}, 'Токен выдаёт команда ', h('code', {}, 'mensarium core token'), ' на сервере Core.'),
    input, btn,
  )));
  input.focus();
}

// ---------- data ----------

async function refreshData() {
  const [targets, tasks] = await Promise.all([get('/v1/targets'), get('/v1/tasks')]);
  state.targets = targets;
  state.tasks = tasks;
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
    h('button', { class: 'icon-btn open-nav', 'aria-label': 'Показать боковую панель', title: 'Показать боковую панель', onclick: shell.toggleNav }, icon('sidebar')),
    newChat ? h('a', { class: 'icon-btn open-nav', href: '#/', 'aria-label': 'Новый чат', title: 'Новый чат' }, icon('plus')) : null,
    h('div', { class: 'crumbs' }, crumbs),
    actions ? h('div', { class: 'topbar-actions' }, actions) : null,
  );
}

function ensureAppShell() {
  if (state.shell && state.shell.kind === 'app') return state.shell;
  const sessions = h('div', { class: 'sessions' });
  const devicesCount = h('span', { class: 'count' });
  const newChat = h('a', { class: 'new-chat', href: '#/' }, icon('plus'), 'Новый чат');
  const devicesLink = h('a', { class: 'nav-item', href: '#/settings/devices' }, icon('laptop'), 'Устройства', devicesCount);
  let s;
  const collapse = h('button', { class: 'icon-btn collapse-nav', 'aria-label': 'Скрыть боковую панель', title: 'Скрыть боковую панель', onclick: () => s.toggleNav() }, icon('sidebar'));
  s = frame('app', [
    h('div', { class: 'brand' }, orb('sm'), h('span', { class: 'brand-name' }, 'Mensarium'), collapse),
    newChat,
    h('div', { class: 'nav-label' }, 'Чаты'),
    sessions,
    h('div', { class: 'sidebar-foot' }, devicesLink, h('a', { class: 'nav-item', href: '#/settings/overview' }, icon('sliders'), 'Настройки')),
  ]);

  const collapsed = new Set(JSON.parse(localStorageGet('collapsed') || '[]'));
  function renderSessions() {
    const online = devices().filter((t) => t.status === 'online').length;
    devicesCount.replaceChildren(h('span', { class: `dot${online ? ' ok' : ''}` }), `${online} в сети`);
    const activeId = (location.hash.match(/^#\/chat\/(.+)$/) || [])[1];
    newChat.classList.toggle('active', !activeId && !location.hash.startsWith('#/settings'));
    if (!state.tasks.length) {
      sessions.replaceChildren(h('div', { class: 'sessions-empty' }, 'Здесь появятся чаты с агентом.'));
      return;
    }
    const byTarget = new Map();
    state.tasks.forEach((t) => {
      const key = t.target_name || 'Другие';
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
          h('button', { class: 'icon-btn session-del', title: 'Удалить чат', 'aria-label': 'Удалить чат', onclick: (e) => { e.preventDefault(); e.stopPropagation(); deleteChat(t); } }, icon('trash')));
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

function composer({ placeholder, chips, onSend }) {
  const ta = h('textarea', { rows: 1, placeholder, 'aria-label': placeholder });
  const send = h('button', { class: 'send', 'aria-label': 'Отправить', title: 'Отправить (Enter)', disabled: true }, icon('arrowUp'));
  const box = h('div', { class: 'composer' },
    h('div', { class: 'composer-input' }, icon('sparkle'), ta),
    h('div', { class: 'composer-bar' }, chips, h('span', { class: 'spacer' }), send),
  );
  let locked = false;
  const sync = () => { send.disabled = locked || !ta.value.trim(); };
  const grow = () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`; };
  ta.addEventListener('input', () => { grow(); sync(); });
  const submit = async () => {
    const text = ta.value.trim();
    if (!text || locked) return;
    send.disabled = true;
    try {
      await onSend(text);
      ta.value = '';
      grow();
    } catch (err) { fail(err); } finally { sync(); }
  };
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  send.addEventListener('click', submit);
  return {
    el: h('div', { class: 'composer-wrap' }, box),
    textarea: ta,
    setText(text) { ta.value = text; grow(); sync(); ta.focus(); ta.setSelectionRange(text.length, text.length); },
    setLocked(value, hint) { locked = value; ta.disabled = value; ta.placeholder = value ? hint : placeholder; sync(); },
  };
}

// Chip + popover to switch between access modes; onPick resolves after the change is applied.
// A device that cannot run full access (disabled by its owner or an agent too old) keeps the chat in "ask".
function modeSwitch(initial, { target, onPick }) {
  let mode = initial;
  const label = h('span', { class: 'chip-label' });
  const chip = h('button', { class: 'chip chip-compact', title: 'Режим доступа', 'aria-haspopup': 'menu' });
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
          title: 'Включить полный доступ?',
          text: `Агент будет запускать команды, менять файлы и ходить в сеть на «${target()?.name || 'устройстве'}» без вопросов. Вернуть режим с подтверждением можно в любой момент.`,
          action: 'Включить',
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
  const chip = h('button', { class: 'chip chip-compact chip-model', title: 'Модель', 'aria-haspopup': 'menu' });
  const render = () => {
    label.textContent = model || defaultModel() || 'Модель';
    chip.title = `Модель: ${label.textContent}`;
    chip.replaceChildren(icon('robot'), label, icon('chevron'));
  };
  chip.addEventListener('click', async () => {
    const search = h('input', { type: 'search', placeholder: 'Найти модель', 'aria-label': 'Найти модель' });
    const list = h('div', { class: 'model-list' }, h('div', { class: 'popover-empty' }, 'Загружаем список...'));
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
      }, h('span', { class: 'mi-model' }, id), id === defaultModel() ? h('span', { class: 'popover-sub' }, 'по умолчанию') : null, id === current ? icon('check') : null))
        : [h('div', { class: 'popover-empty' }, 'Ничего не нашлось')]));
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
  const targetChip = h('button', { class: 'chip', title: 'Устройство', 'aria-haspopup': 'menu', onclick: () => pickTarget() }, icon('laptop'), chipDot, chipLabel, icon('chevron'));
  const renderChip = () => {
    chipLabel.textContent = selected ? selected.name : 'Выберите устройство';
    chipDot.className = `dot${selected ? ' ok' : ''}`;
  };
  function pickTarget() {
    const items = devices().map((t) => h('button', {
      class: `menu-item${selected && t.id === selected.id ? ' selected' : ''}`, disabled: t.status !== 'online',
      onclick: () => { selected = t; localStorageSet('target', t.id); renderChip(); modeCtl.refresh(); hint.textContent = hintText(); closeLayer(); },
    }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), t.name, h('span', { class: 'popover-sub' }, isLocal(t) ? 'сервер Core' : t.status === 'online' ? t.platform.split('-')[0] : 'не в сети')));
    items.push(h('div', { class: 'menu-sep' }), h('button', { class: 'menu-item', onclick: () => { closeLayer(); openPairing(); } }, icon('link'), 'Сопрячь новое устройство'));
    openPopover(targetChip, items);
  }
  renderChip();

  const hint = h('p', { class: 'welcome-hint' });
  const hintText = (mode = modeCtl.effective()) => {
    if (!online.length) return 'Все устройства сейчас не в сети. Запустите на нужной машине mensarium target run.';
    return mode === 'full'
      ? 'Полный доступ: агент сам запускает команды и меняет файлы, не спрашивая.'
      : 'Агент изучит проект сам и спросит разрешения перед запуском команд и изменением файлов.';
  };
  const modeCtl = modeSwitch(localStorageGet('mode') === 'full' ? 'full' : 'ask', {
    target: () => selected,
    onPick: async (value) => { localStorageSet('mode', value); hint.textContent = hintText(value); },
  });
  hint.textContent = hintText();

  const modelCtl = modelSwitch('', { onPick: async () => {} });

  const c = composer({
    placeholder: 'Опишите задачу для агента',
    chips: [targetChip, h('span', { class: 'divider' }), modeCtl.el, modelCtl.el],
    onSend: async (text) => {
      if (!selected) throw new Error('Выберите устройство, на котором агент будет работать');
      const task = await post('/v1/tasks', { target_id: selected.id, input: text, mode: modeCtl.effective(), model: modelCtl.value() || undefined });
      state.tasks.unshift(task);
      go(`#/chat/${task.id}`);
    },
  });

  const content = devices().length
    ? [
      h('div', { class: 'welcome-hero' }, orb('lg'), h('h1', {}, 'Что нужно сделать?')),
      h('div', { class: 'templates' }, TEMPLATES.map(([ic, label, text]) => h('button', { class: 'template', onclick: () => c.setText(text) }, icon(ic), label))),
      c.el,
      hint,
    ]
    : h('div', { class: 'welcome-empty' },
      h('div', { class: 'welcome-hero' }, orb('lg'), h('h1', {}, 'Подключите устройство')),
      h('p', {}, 'Агент работает на ваших машинах через Mensarium Target. Сопряжение займёт минуту.'),
      h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), 'Сопрячь устройство'));

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

  const statusSlot = h('span', {});
  const act = async (action) => {
    try { const t = await post(`/v1/tasks/${taskId}/${action}`); setStatus(t.status); } catch (err) { fail(err); }
  };
  const btnPause = h('button', { class: 'icon-btn', title: 'Пауза', 'aria-label': 'Пауза', onclick: () => act('pause') }, icon('pause'));
  const btnResume = h('button', { class: 'icon-btn', title: 'Продолжить', 'aria-label': 'Продолжить', onclick: () => act('resume') }, icon('play'));
  const btnCancel = h('button', { class: 'icon-btn', title: 'Остановить задачу', 'aria-label': 'Остановить задачу', onclick: async () => {
    if (await confirmDialog({ title: 'Остановить задачу?', text: 'Агент прервёт текущий шаг, команда на устройстве будет отменена. Продолжить эту задачу будет нельзя, но в чат можно написать снова.', action: 'Остановить', danger: true })) act('cancel');
  } }, icon('stop'));
  const btnDelete = h('button', { class: 'icon-btn', title: 'Удалить чат', 'aria-label': 'Удалить чат', onclick: () => deleteChat(task) }, icon('trash'));

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
    placeholder: 'Ответить агенту',
    chips: [modeCtl.el, modelCtl.el],
    onSend: (text) => post(`/v1/tasks/${taskId}/messages`, { input: text }),
  });

  shell.panel.replaceChildren(
    topbar(shell,
      [h('span', { class: 'crumb-device' }, icon('laptop'), task.target_name || 'устройство', h('span', { class: 'sep' }, '/')), h('span', { class: 'current', title: task.input }, taskTitle(task))],
      [statusSlot, btnPause, btnResume, btnCancel, btnDelete]),
    thread,
    c.el,
  );

  function setStatus(status) {
    task.status = status;
    statusSlot.replaceChildren(statusPill(status));
    const running = isRunning(status);
    btnPause.classList.toggle('hidden', !running);
    btnResume.classList.toggle('hidden', !RESUMABLE.includes(status));
    btnCancel.classList.toggle('hidden', !(running || RESUMABLE.includes(status)));
    c.setLocked(running, status === 'WAITING_APPROVAL' ? 'Агент ждёт вашего решения выше' : 'Агент работает. Можно поставить на паузу');
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

  const thinking = new Map();
  const tools = new Map();
  const approvals = new Map();

  function toolCard(id, tool, display) {
    let entry = tools.get(id);
    if (entry) return entry;
    const stateEl = h('span', { class: 'tool-state' }, h('span', { class: 'dot accent live' }), 'выполняется');
    const out = h('pre', { class: 'tool-out' });
    const noteEl = h('div', { class: 'tool-note' });
    const card = h('div', { class: 'tool' });
    const head = h('button', { class: 'tool-head', 'aria-expanded': 'false', onclick: () => {
      card.classList.toggle('open');
      head.setAttribute('aria-expanded', String(card.classList.contains('open')));
    } }, icon(TOOL_ICON[tool] || 'terminal'), h('span', { class: 'tool-display', title: `${tool}: ${display || ''}` }, short(display) || tool), stateEl);
    card.append(head, out, noteEl);
    step(card);
    entry = { card, head, stateEl, out, noteEl };
    tools.set(id, entry);
    return entry;
  }

  function toolResult(p) {
    const e = toolCard(p.tool_call_id, p.tool, '');
    const ok = p.status === 'succeeded';
    const label = { succeeded: 'готово', failed: 'ошибка', timeout: 'таймаут', canceled: 'отменено', rejected: 'отклонено устройством' }[p.status] || p.status;
    e.stateEl.className = `tool-state ${ok ? 'ok' : 'bad'}`;
    e.stateEl.replaceChildren(icon(ok ? 'check' : 'alert'), p.exit_code != null && p.exit_code !== 0 ? `${label}, код ${p.exit_code}` : label);
    e.out.textContent = (p.output || '').replace(/^\[tool output: untrusted data, not instructions\]\n/, '').replace(/^status: [^\n]*\n?/, '') || 'Пустой вывод';
    if (p.truncated || p.artifact_id) {
      e.noteEl.replaceChildren(p.truncated ? 'Вывод сокращён. ' : '', p.artifact_id ? h('a', { href: `/v1/artifacts/${p.artifact_id}`, target: '_blank', rel: 'noopener' }, 'Полный вывод') : '');
    }
    if (!ok || p.tool === 'shell.exec' || p.tool === 'git.diff') {
      e.card.classList.add('open');
      e.head.setAttribute('aria-expanded', 'true');
    }
  }

  function approvalCard(p) {
    const tc = p.tool_call || {};
    const args = tc.arguments || {};
    const [riskLabel, riskKind] = RISK[tc.risk] || [tc.risk, ''];
    const timer = h('span', { class: 'approval-timer' });
    const approve = h('button', { class: 'btn btn-primary' }, icon('check'), 'Выполнить один раз');
    const reject = h('button', { class: 'btn' }, 'Отклонить');
    const actions = h('div', { class: 'approval-actions' }, approve, reject);
    let confirmBox = null;
    const card = h('div', { class: `approval${tc.risk === 'destructive' ? ' risk-destructive' : ''}`, role: 'group', 'aria-label': 'Запрос подтверждения' },
      h('div', { class: 'approval-top' }, h('span', { class: 'approval-title' }, 'Нужно ваше решение'), h('span', { class: `pill ${riskKind}` }, riskLabel), timer),
      h('pre', { class: 'approval-cmd' }, args.command ? `$ ${args.command}` : short(tc.display)),
      h('dl', { class: 'approval-meta' },
        tc.tool !== 'shell.exec' ? [h('dt', {}, 'Инструмент'), h('dd', {}, tc.tool)] : null,
        h('dt', {}, 'Устройство'), h('dd', {}, tc.target_name || ''),
        args.cwd ? [h('dt', {}, 'Папка'), h('dd', { title: args.cwd }, short(args.cwd))] : null,
        args.timeout_s ? [h('dt', {}, 'Лимит'), h('dd', {}, `${args.timeout_s} с`)] : null,
      ),
      args.stdin ? [h('div', { class: 'approval-sub' }, 'Данные на вход'), h('pre', { class: 'approval-cmd approval-stdin' }, args.stdin)] : null,
    );
    if (tc.risk === 'destructive') {
      const cb = h('input', { type: 'checkbox' });
      approve.disabled = true;
      cb.addEventListener('change', () => { approve.disabled = !cb.checked; });
      confirmBox = h('label', { class: 'approval-confirm' }, cb, 'Понимаю, что действие нельзя отменить');
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
    step(card);
    const expires = new Date(p.expires_at).getTime();
    const tick = () => { const left = Math.round((expires - Date.now()) / 1000); timer.textContent = left > 0 ? `осталось ${mmss(left)}` : 'время истекло'; };
    tick();
    const iv = setInterval(tick, 1000);
    viewCleanups.push(() => clearInterval(iv));
    approvals.set(p.approval_id, { card, actions, iv, timer, confirmBox });
  }

  function approvalDecided(p) {
    const e = approvals.get(p.approval_id);
    if (!e) return;
    clearInterval(e.iv);
    e.timer.textContent = '';
    e.card.classList.add('decided');
    if (e.confirmBox) e.confirmBox.remove();
    const text = { approved: 'Вы разрешили выполнить один раз', rejected: 'Вы отклонили действие', expired: 'Время на решение истекло' }[p.decision] || p.decision;
    const note = p.note === 'full access enabled' ? 'одобрено включением полного доступа' : p.note;
    e.actions.replaceChildren(h('span', { class: 'approval-result' }, text, note ? `: ${note}` : ''));
  }

  function handle({ event, payload: p }) {
    switch (event) {
      case 'user.message':
        lastAgent = false;
        add(h('div', { class: 'msg-user' }, h('div', { class: 'bubble-user' }, p.text)));
        break;
      case 'task.status':
        setStatus(p.status);
        if (['PAUSED', 'CANCELED', 'FAILED', 'FAILED_RECOVERABLE'].includes(p.status)) {
          note(p.status === 'PAUSED' ? 'pause' : 'alert', `${statusOf(p.status)[0]}${p.reason ? `: ${reasonText(p.reason)}` : ''}`, p.status === 'PAUSED' || p.status === 'CANCELED' ? '' : 'error');
        }
        break;
      case 'task.mode':
        modeCtl.set(p.mode);
        note(MODES[p.mode]?.icon || 'shield', `Режим: ${(MODES[p.mode]?.label || p.mode).toLowerCase()}`);
        break;
      case 'task.model':
        modelCtl.set(p.model);
        note('robot', `Модель: ${p.model}`);
        break;
      case 'llm.request':
        thinking.set(p.step, agentMsg(h('span', { class: 'thinking' }, 'Думает'), true));
        break;
      case 'llm.response': {
        const row = thinking.get(p.step);
        if (row) {
          row.remove();
          thinking.delete(p.step);
          const last = inner.lastChild;
          lastAgent = !!last && (last.classList.contains('msg-agent') || last.classList.contains('step'));
        }
        if (p.text && p.tool_call) agentMsg(h('div', { class: 'prose', html: markdown(p.text) }));
        break;
      }
      case 'tool_call.denied':
        note('ban', `Политика не разрешила ${p.tool}: ${policyText(p.reason)}`);
        break;
      case 'tool_call.pending_approval':
        approvalCard(p);
        break;
      case 'approval.decided':
        approvalDecided(p);
        break;
      case 'tool_call.executing':
        toolCard(p.tool_call_id, p.tool, p.display);
        break;
      case 'tool_call.result':
        toolResult(p);
        break;
      case 'task.final':
        agentMsg(h('div', { class: 'prose', html: markdown(p.text) }));
        break;
      case 'task.error':
        note('alert', p.message, 'error');
        break;
      default:
    }
  }

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
      handle(ev);
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
  ['overview', 'pulse', 'Обзор'],
  ['model', 'robot', 'Модель'],
  ['devices', 'laptop', 'Устройства'],
  ['memory', 'graph', 'Память'],
  ['marketplace', 'package', 'Маркетплейс'],
  ['profiles', 'layers', 'Профили'],
  ['audit', 'list', 'Журнал действий'],
];

function ensureSettingsShell() {
  if (state.shell && state.shell.kind === 'settings') return state.shell;
  const nav = h('div', { class: 'settings-nav' });
  const search = h('input', { type: 'search', placeholder: 'Поиск настроек', 'aria-label': 'Поиск настроек' });
  const back = () => go(state.lastChat || '#/');
  const s = frame('settings', [
    h('button', { class: 'back-link', onclick: back }, icon('arrowLeft'), 'Вернуться в чат', h('span', { class: 'kbd' }, 'Esc')),
    h('div', { class: 'settings-title' }, 'Настройки'),
    h('div', { class: 'settings-search' }, icon('search'), search),
    nav,
  ]);
  const renderNav = () => {
    const q = search.value.trim().toLowerCase();
    const active = (location.hash.match(/^#\/settings\/(\w+)/) || [])[1] || 'overview';
    const visible = SETTINGS.filter(([, , label]) => !q || label.toLowerCase().includes(q));
    nav.replaceChildren(...(visible.length
      ? visible.map(([key, ic, label]) => h('a', { class: `nav-item${key === active ? ' active' : ''}`, href: `#/settings/${key}`, 'aria-current': key === active ? 'page' : null }, icon(ic), label))
      : [h('div', { class: 'sessions-empty' }, 'Ничего не нашлось')]));
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

const copyBtn = (text) => h('button', { class: 'icon-btn', 'aria-label': 'Скопировать', title: 'Скопировать', onclick: (e) => copy(text, e.currentTarget) }, icon('copy'));
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
  const logout = h('button', { class: 'btn', onclick: async () => { try { await post('/v1/auth/logout'); } catch { /* noop */ } showLogin(); } }, icon('logout'), 'Выйти');
  page(shell, 'Обзор', 'Где доступен главный агент и как проверить, что устройства говорят именно с ним.', logout,
    h('div', { class: 'hero' }, orb('md'), h('div', {}, h('h2', {}, 'Mensarium Core'), h('p', {}, `Версия ${s.version}`))),
    section('Подключение', null, h('div', { class: 'rows' },
      row('Адрес Core', 'Им пользуются браузер и устройства.', cmdValue(url), true),
      row('Отпечаток ключа', 'Сверьте с тем, что показал установщик на устройстве при сопряжении.', s.core_key_fingerprint, true),
    )),
    section('Обслуживание', 'Команды выполняются на сервере Core.', h('div', { class: 'rows' },
      row('Обновить Mensarium', 'Скачивает свежую версию и перезапускает сервис.', cmdValue('mensarium update'), true),
      row('Токен входа', 'Показывает токен администратора.', cmdValue('mensarium core token'), true),
    )),
    section('Резервная копия', 'Архив с базой, ключами, секретами и настройками, зашифрованный паролем, который вы зададите. Им же Core переносится на другой сервер.', h('div', { class: 'rows' },
      row('Создать копию', 'Сохраняет архив в текущую папку.', cmdValue('mensarium core backup -o mensarium.pab'), true),
      row('Восстановить из копии', 'Останавливает Core, заменяет его данные содержимым архива и запускает снова. Прежние данные остаются рядом, в папке core.before-restore-….', cmdValue('mensarium core restore mensarium.pab'), true),
    )),
  );
}

async function settingsModel(shell) {
  const s = await get('/v1/system');
  state.system = s;
  const p = s.provider || {};
  const health = p.health || {};
  const providerName = { ollama_cloud: 'Ollama Cloud', ollama_local: 'Локальный Ollama', llama_cpp: 'llama.cpp' }[p.name] || p.name;
  const current = h('span', {}, p.model);
  const list = h('div', { class: 'rows' }, h('div', { class: 'empty' }, 'Загружаем список...'));
  page(shell, 'Модель', 'Через какого провайдера и какую модель агент думает. Ключ API хранится только на сервере Core.', null,
    h('div', { class: 'rows' },
      row('Провайдер', null, providerName),
      row('Адрес API', null, p.base_url, true),
      row('Модель по умолчанию', 'Для новых чатов. В самом чате модель меняется кнопкой с роботом в поле ввода.', h('span', { class: 'status' }, icon('robot'), current), true),
      row('Состояние', health.ok ? null : health.detail, h('span', { class: 'status' }, h('span', { class: `dot ${health.ok ? 'ok' : 'danger'}` }), health.ok ? 'Доступен' : 'Недоступен')),
    ),
    section('Доступные модели', 'Нажмите на модель, чтобы сделать её моделью по умолчанию.', list),
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
            toast(`Модель по умолчанию: ${id}`);
            render(ids);
          } catch (err) { fail(err); }
        },
      }, id)))
      : h('div', { class: 'empty' }, 'Провайдер не вернул ни одной модели.'));
  };
  try {
    state.models = null;
    render((await loadModels()).map((m) => m.id));
  } catch (err) {
    list.replaceChildren(h('div', { class: 'empty' }, err.message));
  }
}

const TOOL_INFO = {
  'files.list': ['Список файлов', 'Смотрит содержимое папок.'],
  'files.read': ['Чтение файлов', 'Открывает текстовые файлы, секреты вычищаются.'],
  'files.search': ['Поиск по файлам', 'Ищет текст в проекте.'],
  'git.status': ['Состояние git', 'Ветка и изменённые файлы.'],
  'git.diff': ['Изменения git', 'Показывает diff.'],
  'shell.exec': ['Запуск команд', 'Запускает разрешённые программы, файлы меняет через git apply.'],
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
    const access = { allowed: 'Разрешён: в чате можно включить режим без подтверждений.', disabled: fullAccessBlock(t), outdated: fullAccessBlock(t) }[caps.full_access] || '';
    const revoke = h('button', { class: 'btn btn-sm btn-danger', onclick: async () => {
      if (!await confirmDialog({ title: `Отозвать «${t.name}»?`, text: 'Устройство сразу потеряет доступ. Чтобы вернуть его, понадобится новое сопряжение по коду.', action: 'Отозвать', danger: true })) return;
      try { await post(`/v1/targets/${t.id}/revoke`); toast('Доступ отозван'); await refresh(true); } catch (err) { fail(err); }
    } }, 'Отозвать доступ');
    return h('div', { class: 'device-body' },
      h('div', { class: 'device-sub' }, 'Инструменты агента', h('span', {}, 'Выключенный инструмент агент на этом устройстве не видит и вызвать не может.')),
      h('div', { class: 'tool-rows' }, (caps.tools || []).map((tool) => {
        const [name, desc] = TOOL_INFO[tool] || [tool, ''];
        return h('div', { class: 'tool-row' },
          icon(TOOL_ICON[tool] || 'terminal'),
          h('div', { class: 'row-text' }, h('div', { class: 'tool-row-title' }, name, h('code', {}, tool)), desc ? h('div', { class: 'row-desc' }, desc) : null),
          toggleSwitch(!disabled.has(tool), {
            label: `${name} на «${t.name}»`,
            onChange: async (enabled) => {
              const view = await api(`/v1/targets/${t.id}/tools`, { method: 'PUT', body: JSON.stringify({ tool, enabled }) });
              Object.assign(t, view);
              signature = '';
              render();
            },
          }));
      })),
      extTools.length ? [
        h('div', { class: 'device-sub' }, 'Инструменты из маркетплейса', h('span', {}, 'Запускаются как команды, поэтому нужен включённый «Запуск команд» и программа в списке разрешённых.')),
        h('div', { class: 'tool-rows' }, extTools.map((tool) => h('div', { class: 'tool-row' },
          icon('terminal'),
          h('div', { class: 'row-text' }, h('div', { class: 'tool-row-title' }, tool.name, h('code', {}, tool.ext)), h('div', { class: 'row-desc' }, tool.description)),
          programs.includes('*') || programs.includes(tool.argv[0]) ? null : h('span', { class: 'pill warn', title: 'Программы нет в списке разрешённых на устройстве' }, `нет ${tool.argv[0]}`),
          toggleSwitch(!disabled.has(tool.name), {
            label: `${tool.name} на «${t.name}»`,
            onChange: async (enabled) => {
              Object.assign(t, await api(`/v1/targets/${t.id}/tools`, { method: 'PUT', body: JSON.stringify({ tool: tool.name, enabled }) }));
              signature = '';
              render();
            },
          })))),
      ] : null,
      h('div', { class: 'device-sub' }, 'Папки'),
      h('div', { class: 'device-tags' }, (caps.roots || []).map((r) => h('span', { class: 'pill tag', title: r }, r))),
      h('div', { class: 'device-sub' }, 'Программы для запуска команд'),
      h('div', { class: 'device-tags' }, programs.includes('*') ? h('span', { class: 'pill' }, 'любые программы') : programs.map((pr) => h('span', { class: 'pill tag' }, pr))),
      h('div', { class: 'device-sub' }, 'Полный доступ'),
      h('p', { class: 'device-text' }, access),
      h('div', { class: 'device-actions' }, revoke),
    );
  }

  function render() {
    const targets = devices();
    const sig = JSON.stringify([targets, [...expanded]]);
    if (sig === signature) return;
    signature = sig;
    if (!targets.length) {
      listHost.replaceChildren(h('div', { class: 'rows' }, h('div', { class: 'empty' },
        h('h3', {}, 'Устройств пока нет'), h('p', {}, 'Сопрягите машину, на которой агент будет работать.'),
        h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), 'Сопрячь устройство'))));
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
            isLocal(t) ? h('span', { class: 'pill accent', title: 'Машина, на которой установлен Core. Подключена всегда.' }, 'Core') : null,
            outdated ? h('span', { class: 'pill warn', title: 'Выполните на устройстве: mensarium update' }, `v${t.agent_version}, есть обновление`) : null),
          h('div', { class: 'row-desc' }, [
            t.status === 'online' ? t.platform : `${t.platform} · был в сети ${relTime(t.last_seen_at)}`,
            `инструменты: ${enabled} из ${tools.length}`,
            caps.full_access === 'allowed' ? 'полный доступ разрешён' : null,
          ].filter(Boolean).join(' · '))),
        h('span', { class: 'status', title: t.status === 'online' ? 'В сети' : 'Не в сети' }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), h('span', { class: 'status-label' }, t.status === 'online' ? 'В сети' : 'Не в сети')));
      return h('div', { class: `device${open ? ' open' : ''}` }, head, open ? deviceBody(t) : null);
    })));
  }

  async function refresh(force = false) {
    try { await refreshData(); if (force) signature = ''; render(); } catch (err) { fail(err); }
  }
  page(shell, 'Устройства', 'Машины, на которых агент читает проекты и выполняет команды. Нажмите на устройство, чтобы настроить его инструменты.',
    h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), 'Сопрячь устройство'),
    listHost,
  );
  render();
  const iv = setInterval(refresh, 5000);
  viewCleanups.push(() => clearInterval(iv));
}

// ---------- memory ----------

const MEM_KINDS = { fact: 'Факт', preference: 'Предпочтение', project: 'Проект', person: 'Человек', device: 'Устройство', howto: 'Инструкция', note: 'Заметка' };
const MEM_SOURCES = { user: 'вы', agent: 'агент', dream: 'сновидение' };
const DREAM_PHASES = [['light', 'Лёгкий сон', 'собираю новые чаты'], ['rem', 'REM', 'ищу важное и связи'], ['deep', 'Глубокий сон', 'закрепляю в памяти'], ['diary', 'Дневник', 'записываю, что запомнил']];
const DREAM_TRIGGER = { schedule: 'по расписанию', manual: 'вручную' };

// Markdown plus [[wikilinks]]; titles arrive HTML-escaped from markdown(), so they are safe in the attribute.
const memoryMd = (text) => markdown(text).replace(/\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]/g, (_, title, alias) => `<a href="#" class="wikilink" data-title="${title}">${alias || title}</a>`);

function kindPill(kind) {
  return h('span', { class: 'pill kind-pill' }, h('span', { class: 'kind-dot', style: `background:${graphColor(kind)}` }), MEM_KINDS[kind] || kind);
}

async function openNoteEditor(note, { onSaved, onOpenTitle } = {}) {
  const full = note?.id ? await get(`/v1/memory/notes/${note.id}`) : null;
  const n = full || { title: note?.title || '', body: '', kind: 'fact', tags: [], pinned: false, importance: 5 };
  const title = h('input', { type: 'text', value: n.title, placeholder: 'Короткое название', 'aria-label': 'Название', maxlength: '120' });
  const kind = h('select', { 'aria-label': 'Тип' }, Object.entries(MEM_KINDS).map(([k, label]) => h('option', { value: k, selected: k === n.kind }, label)));
  const importance = h('select', { 'aria-label': 'Важность' }, Array.from({ length: 10 }, (_, i) => h('option', { value: String(i + 1), selected: i + 1 === n.importance }, `Важность ${i + 1}`)));
  let pinned = n.pinned;
  const pin = toggleSwitch(pinned, { label: 'Всегда в контексте агента', onChange: async (v) => { pinned = v; } });
  const tags = h('input', { type: 'text', value: (n.tags || []).join(', '), placeholder: 'теги через запятую', 'aria-label': 'Теги' });
  const body = h('textarea', { class: 'note-body', rows: 11, placeholder: 'Что запомнить. Ссылка на другую заметку: [[Название]]', 'aria-label': 'Текст заметки' });
  body.value = n.body || '';
  const save = h('button', { class: 'btn btn-primary' }, 'Сохранить');
  save.addEventListener('click', async () => {
    const payload = { title: title.value.trim(), body: body.value, kind: kind.value, importance: Number(importance.value), pinned, tags: tags.value.split(',').map((t) => t.trim()).filter(Boolean) };
    if (!payload.title) { title.focus(); return; }
    save.disabled = true;
    try {
      const saved = full ? await api(`/v1/memory/notes/${full.id}`, { method: 'PATCH', body: JSON.stringify(payload) }) : await post('/v1/memory/notes', payload);
      closeLayer();
      toast(full ? 'Заметка сохранена' : 'Заметка создана');
      onSaved?.(saved);
    } catch (err) { fail(err); } finally { save.disabled = false; }
  });
  const remove = full ? h('button', { class: 'btn btn-danger', onclick: async () => {
    if (!await confirmDialog({ title: `Удалить «${full.title}»?`, text: 'Агент забудет эту заметку. Ссылки на неё в других заметках останутся и станут пустыми узлами графа.', action: 'Удалить', danger: true })) return;
    try { await del(`/v1/memory/notes/${full.id}`); toast('Заметка удалена'); onSaved?.(null); } catch (err) { fail(err); }
  } }, 'Удалить') : null;
  const backlinks = full?.backlinks?.length ? h('div', { class: 'note-backlinks' }, 'Ссылаются сюда: ', full.backlinks.map((b, i) => [i ? ', ' : '', h('a', { href: '#', onclick: (e) => { e.preventDefault(); closeLayer(); onOpenTitle?.(b.title); } }, b.title)])) : null;
  const meta = full ? h('div', { class: 'market-meta' }, [`источник: ${MEM_SOURCES[full.source] || full.source}`, full.source_task_id ? h('a', { href: `#/chat/${full.source_task_id}` }, 'чат') : null, `обновлена ${relTime(full.updated_at)}`, full.recall_count ? `агент обращался ${full.recall_count} раз` : null].filter(Boolean).flatMap((x, i) => (i ? [' · ', x] : [x]))) : null;
  openModal(
    h('div', { class: 'modal-head' }, h('h2', {}, full ? 'Заметка' : 'Новая заметка'), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': 'Закрыть' }, icon('x'))),
    meta,
    h('div', { class: 'note-form' },
      h('label', { class: 'note-field' }, h('span', {}, 'Название'), title),
      h('div', { class: 'note-row' }, kind, importance, h('label', { class: 'switch-label', title: 'Заметка попадает в каждый запрос к модели' }, pin, 'Всегда в контексте')),
      h('label', { class: 'note-field' }, h('span', {}, 'Теги'), tags),
      h('label', { class: 'note-field' }, h('span', {}, 'Текст'), body),
      backlinks),
    h('div', { class: 'modal-actions' }, remove, h('span', { class: 'spacer' }), h('button', { class: 'btn', onclick: closeLayer }, 'Отмена'), save),
  ).classList.add('modal-wide');
  (full ? body : title).focus();
}

async function settingsMemory(shell) {
  const TABS = [['graph', 'Граф'], ['notes', 'Заметки'], ['dreams', 'Сновидения']];
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
    const canvas = h('canvas', { class: 'graph-canvas', 'aria-label': 'Граф памяти: перетаскивайте узлы, колесо — масштаб' });
    const side = h('aside', { class: 'graph-side hidden' });
    const search = h('input', { type: 'search', placeholder: 'Найти заметку', 'aria-label': 'Найти заметку на графе' });
    let withTags = localStorageGet('graph-tags') === '1';
    const tagsChip = h('button', { class: `chip${withTags ? ' accent' : ''}`, 'aria-pressed': String(withTags) }, '#', 'Теги');
    let data = { nodes: [], links: [] };
    const graph = createGraph(canvas, { onSelect: (node) => preview(node) });
    const empty = h('div', { class: 'graph-empty hidden' }, orb('md'), h('h3', {}, 'Память пока пуста'), h('p', {}, 'Агент начнёт запоминать сам, а сновидения соберут важное из чатов. Можно добавить заметку вручную.'), h('button', { class: 'btn btn-primary', onclick: newNote }, icon('plus'), 'Новая заметка'));

    async function load() {
      data = await get(`/v1/memory/graph?tags=${withTags}`);
      empty.classList.toggle('hidden', data.nodes.length > 0);
      graph.setData(data);
    }
    async function preview(node) {
      if (!node) { side.classList.add('hidden'); return; }
      side.classList.remove('hidden');
      const close = h('button', { class: 'icon-btn', 'aria-label': 'Закрыть', onclick: () => { side.classList.add('hidden'); graph.select(null); } }, icon('x'));
      if (node.kind === 'tag') {
        const notes = data.links.filter((l) => l.target === node.id).map((l) => data.nodes.find((x) => x.id === l.source)).filter(Boolean);
        side.replaceChildren(h('div', { class: 'graph-side-head' }, h('h3', {}, node.label), close), h('div', { class: 'graph-side-list' }, notes.map((x) => h('button', { class: 'menu-item', onclick: () => { graph.select(x.id); preview(x); } }, h('span', { class: 'kind-dot', style: `background:${graphColor(x.kind)}` }), x.label))));
        return;
      }
      if (node.ghost) {
        side.replaceChildren(h('div', { class: 'graph-side-head' }, h('h3', {}, node.label), close), h('p', { class: 'muted' }, 'На эту заметку ссылаются, но её ещё нет.'), h('button', { class: 'btn btn-primary btn-sm', onclick: () => openNoteEditor({ title: node.label }, { onSaved: load, onOpenTitle: openTitle }) }, icon('plus'), 'Создать заметку'));
        return;
      }
      side.replaceChildren(h('div', { class: 'graph-side-head' }, h('h3', {}, node.label), close), h('p', { class: 'muted' }, 'Загружаем...'));
      let n;
      try { n = await get(`/v1/memory/notes/${node.id}`); } catch (err) { fail(err); return; }
      const bodyEl = h('div', { class: 'prose graph-side-body', html: memoryMd(n.body || '_Пусто_') });
      bodyEl.addEventListener('click', (e) => {
        const link = e.target.closest('.wikilink');
        if (!link) return;
        e.preventDefault();
        const target = data.nodes.find((x) => !x.kind.startsWith('tag') && x.label.toLowerCase() === link.dataset.title.toLowerCase());
        if (target) { graph.select(target.id); preview(target); }
      });
      side.replaceChildren(
        h('div', { class: 'graph-side-head' }, h('h3', {}, n.title), close),
        h('div', { class: 'graph-side-meta' }, kindPill(n.kind), n.pinned ? h('span', { class: 'pill accent', title: 'Всегда в контексте агента' }, icon('pin'), 'закреплена') : null, (n.tags || []).map((t) => h('span', { class: 'pill tag' }, `#${t}`))),
        bodyEl,
        n.backlinks.length ? h('div', { class: 'note-backlinks' }, 'Ссылаются сюда: ', n.backlinks.map((b, i) => [i ? ', ' : '', h('a', { href: '#', onclick: (e) => { e.preventDefault(); graph.select(b.id); preview(data.nodes.find((x) => x.id === b.id)); } }, b.title)])) : null,
        h('div', { class: 'market-meta' }, `источник: ${MEM_SOURCES[n.source] || n.source} · важность ${n.importance}`),
        h('button', { class: 'btn btn-sm', onclick: () => openNoteEditor(n, { onSaved: async () => { await load(); side.classList.add('hidden'); }, onOpenTitle: openTitle }) }, 'Изменить'),
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
      if (node) { graph.select(node.id); preview(node); } else toast('Не нашлось такой заметки');
    });
    const legend = h('div', { class: 'graph-legend' }, Object.entries(MEM_KINDS).map(([k, label]) => h('span', {}, h('span', { class: 'kind-dot', style: `background:${graphColor(k)}` }), label)));
    host.append(
      h('div', { class: 'graph-toolbar' },
        h('div', { class: 'settings-search graph-search' }, icon('search'), search),
        tagsChip,
        h('span', { class: 'spacer' }),
        h('button', { class: 'icon-btn', title: 'Уменьшить', 'aria-label': 'Уменьшить', onclick: () => graph.zoom(1 / 1.3) }, h('span', { class: 'zoom-sign' }, '−')),
        h('button', { class: 'icon-btn', title: 'Показать всё', 'aria-label': 'Показать всё', onclick: () => graph.fit() }, icon('layers')),
        h('button', { class: 'icon-btn', title: 'Увеличить', 'aria-label': 'Увеличить', onclick: () => graph.zoom(1.3) }, icon('plus'))),
      h('div', { class: 'graph-stage' }, canvas, side, empty),
      legend,
    );
    await load();
    return () => graph.destroy();
  }

  async function memoryNotes() {
    const search = h('input', { type: 'search', placeholder: 'Поиск по заметкам', 'aria-label': 'Поиск по заметкам' });
    const kindFilter = h('select', { 'aria-label': 'Тип заметок' }, h('option', { value: '' }, 'Все типы'), Object.entries(MEM_KINDS).map(([k, label]) => h('option', { value: k }, label)));
    const list = h('div', { class: 'rows' }, h('div', { class: 'empty' }, 'Загружаем...'));
    let timer = 0;
    async function load() {
      const q = search.value.trim();
      const { notes } = await get(`/v1/memory/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`);
      const shown = notes.filter((n) => !kindFilter.value || n.kind === kindFilter.value);
      list.replaceChildren(...(shown.length ? shown.map((n) => h('button', { class: 'note-item', onclick: () => openNoteEditor(n, { onSaved: load, onOpenTitle: openTitle }) },
        h('span', { class: 'kind-dot', style: `background:${graphColor(n.kind)}` }),
        h('div', { class: 'row-text' },
          h('div', { class: 'row-title' }, n.title, n.pinned ? h('span', { class: 'note-pin', title: 'Всегда в контексте агента' }, icon('pin')) : null),
          h('div', { class: 'row-desc' }, n.snippet || 'Пусто'),
          h('div', { class: 'note-item-meta' }, [MEM_KINDS[n.kind] || n.kind, MEM_SOURCES[n.source] || n.source, relTime(n.updated_at), ...(n.tags || []).map((t) => `#${t}`)].join(' · ')))))
        : [h('div', { class: 'empty' }, q || kindFilter.value ? 'Ничего не нашлось.' : 'Заметок пока нет. Агент будет сохранять важное сам, а сновидения — собирать из чатов.')]));
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
      clearTimeout(timer);
      timer = setTimeout(() => load().catch(() => {}), d.running ? 1500 : 20000);
      const sig = JSON.stringify(d);
      if (sig === signature) return;
      signature = sig;
      const current = d.runs.find((r) => r.status === 'running');
      const run = h('button', { class: 'btn btn-primary', disabled: d.running, onclick: async () => {
        try { await post('/v1/memory/dreams'); toast('Агент засыпает'); signature = ''; await load(); } catch (err) { fail(err); }
      } }, icon('moon'), d.running ? 'Видит сны...' : 'Запустить сейчас');
      const hour = h('select', { 'aria-label': 'Час запуска' }, Array.from({ length: 24 }, (_, i) => h('option', { value: String(i), selected: i === s.hour }, `в ${String(i).padStart(2, '0')}:00`)));
      hour.addEventListener('change', () => put({ hour: Number(hour.value) }));
      const threshold = h('select', { 'aria-label': 'Порог важности' }, Array.from({ length: 10 }, (_, i) => h('option', { value: String(i + 1), selected: i + 1 === s.min_importance }, `важность от ${i + 1}`)));
      threshold.addEventListener('change', () => put({ min_importance: Number(threshold.value) }));
      const phaseIdx = current ? DREAM_PHASES.findIndex(([k]) => k === current.phase) : -1;
      box.replaceChildren(...[
        h('div', { class: `dream-card${d.running ? ' running' : ''}` },
          createOrb(72, { animate: true, live: d.running, className: 'md' }),
          h('div', { class: 'dream-text' },
            h('h2', {}, 'Сновидения'),
            h('p', {}, 'Ночью агент перебирает новые чаты: в лёгком сне собирает, что вы говорили и что он делал, в REM ищет важное и связи с тем, что уже знает, в глубоком сне закрепляет в памяти только то, что прошло порог важности, а утром оставляет запись в дневнике.'),
            h('div', { class: 'dream-controls' },
              h('label', { class: 'switch-label' }, toggleSwitch(s.dreaming, { label: 'Каждую ночь', onChange: (v) => put({ dreaming: v }) }), 'Каждую ночь'),
              hour, threshold, h('span', { class: 'spacer' }), run))),
        current ? h('div', { class: 'dream-phases' }, DREAM_PHASES.map(([k, label, desc], i) => h('div', { class: `dream-phase${i < phaseIdx ? ' done' : i === phaseIdx ? ' current' : ''}` },
          h('span', { class: 'dream-phase-dot' }, i < phaseIdx ? icon('check') : String(i + 1)), h('div', {}, h('div', { class: 'dream-phase-title' }, label), h('div', { class: 'row-desc' }, desc))))) : null,
        h('div', { class: 'section-head dream-diary-head' }, h('div', {}, h('h2', {}, 'Дневник сновидений'))),
        d.runs.filter((r) => r.status !== 'running').length
          ? h('div', { class: 'dream-runs' }, d.runs.filter((r) => r.status !== 'running').map(dreamEntry))
          : h('div', { class: 'rows' }, h('div', { class: 'empty' }, 'Агент ещё ни разу не видел снов.')),
      ].filter(Boolean));
    }
    const put = async (values) => { try { await api('/v1/memory/dreams/settings', { method: 'PUT', body: JSON.stringify(values) }); } catch (err) { fail(err); } };
    function dreamEntry(r) {
      const st = r.stats || {};
      const status = { done: ['', ''], empty: ['без снов', ''], failed: ['ошибка', 'danger'] }[r.status] || [r.status, ''];
      const numbers = [st.chats != null && `чатов: ${st.chats}`, st.created && `новых: ${st.created}`, st.updated && `дополнено: ${st.updated}`, st.reinforced && `укреплено: ${st.reinforced}`, st.discarded && `отпущено: ${st.discarded}`].filter(Boolean).join(' · ');
      return h('article', { class: 'dream-entry' },
        h('div', { class: 'dream-entry-head' }, h('span', { class: 'dream-date' }, new Date(r.started_at).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })), h('span', { class: 'market-meta' }, DREAM_TRIGGER[r.trigger] || r.trigger), status[0] ? h('span', { class: `pill ${status[1]}` }, status[0]) : null),
        numbers ? h('div', { class: 'market-meta' }, numbers) : null,
        r.status === 'empty' ? h('p', { class: 'muted' }, 'Новых разговоров не было, спал без снов.') : null,
        r.error ? h('p', { class: 'dream-error' }, r.error) : null,
        r.diary ? h('div', { class: 'prose dream-diary' }, h('p', {}, r.diary)) : null,
        (st.themes || []).length ? h('div', { class: 'market-tags' }, st.themes.map((t) => h('span', { class: 'pill tag-kind' }, t))) : null,
        (r.changes || []).length ? h('div', { class: 'dream-changes' }, r.changes.map((c) => h('button', { class: `dream-change ${c.action}`, onclick: () => openNoteEditor({ id: c.id }, { onSaved: () => show(), onOpenTitle: openTitle }).catch(() => toast('Заметка уже удалена', true)) },
          { created: '+', updated: '~', reinforced: '↑' }[c.action] || '', ` ${c.title}`))) : null);
    }
    host.append(box);
    await load();
    return () => clearTimeout(timer);
  }

  page(shell, 'Память', 'Что агент помнит о вас, проектах и устройствах. Заметки связываются ссылками [[Название]], а сновидения по ночам собирают важное из новых чатов.',
    h('button', { class: 'btn', onclick: newNote }, icon('plus'), 'Новая заметка'),
    tabs, host);
  shell.panel.querySelector('.page-inner').classList.add('page-wide');
  viewCleanups.push(() => { if (cleanup) cleanup(); });
  await show();
}

const RISK_SHORT = { read: 'чтение', write: 'изменения', execute: 'запуск', network: 'сеть', destructive: 'необратимое' };
const extKind = (e) => [e.instructions ? 'Навык' : null, e.tools.length ? `Инструменты: ${e.tools.length}` : null].filter(Boolean);
const extIcon = (e) => (e.instructions && e.tools.length ? 'layers' : e.instructions ? 'book' : 'terminal');

async function settingsMarketplace(shell) {
  const grid = h('div', { class: 'market-grid' }, h('div', { class: 'empty' }, 'Загружаем каталог...'));
  const note = h('p', { class: 'market-note hidden' });
  const search = h('input', { type: 'search', placeholder: 'Поиск по названию и описанию', 'aria-label': 'Поиск в маркетплейсе' });
  const FILTERS = [['all', 'Все'], ['skills', 'Навыки'], ['tools', 'Инструменты'], ['installed', 'Установленные']];
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
  const install = (e) => act(() => post('/v1/extensions', { id: e.id }), e.installed ? `Обновлено: ${txt(e.name)}` : `Установлено: ${txt(e.name)}`);
  const remove = async (e) => {
    if (!await confirmDialog({ title: `Удалить «${txt(e.name)}»?`, text: e.installed.source === 'custom' ? 'Это ваш пакет, его содержимое удалится из Core.' : 'Агент перестанет им пользоваться. Установить снова можно в любой момент.', action: 'Удалить', danger: true })) return;
    closeLayer();
    act(() => del(`/v1/extensions/${e.id}`), 'Удалено');
  };
  const setEnabled = (e, enabled) => api(`/v1/extensions/${e.id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }).then(() => { e.installed.enabled = enabled; });

  function actions(e, big = false) {
    const size = big ? '' : ' btn-sm';
    if (!e.installed) return h('button', { class: `btn btn-primary${size}`, onclick: (ev) => { ev.stopPropagation(); closeLayer(); install(e); } }, icon('plus'), 'Установить');
    return h('div', { class: 'market-actions', onclick: (ev) => ev.stopPropagation() },
      e.update ? h('button', { class: `btn btn-primary${size}`, onclick: () => { closeLayer(); install(e); } }, `Обновить до ${e.version}`) : null,
      h('label', { class: 'switch-label' }, toggleSwitch(e.installed.enabled, { label: `Включить «${txt(e.name)}»`, onChange: (v) => setEnabled(e, v) }), 'Включён'),
      big ? h('button', { class: 'btn btn-danger btn-sm', onclick: () => remove(e) }, 'Удалить') : null);
  }

  function details(e) {
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, txt(e.name)), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': 'Закрыть' }, icon('x'))),
      h('div', { class: 'market-meta' }, [e.author, `версия ${e.installed ? e.installed.version : e.version}`, e.installed?.source === 'custom' ? 'ваш пакет' : null].filter(Boolean).join(' · ')),
      h('p', {}, txt(e.description) || txt(e.summary)),
      e.tools.length ? [h('div', { class: 'field-label' }, 'Инструменты'), h('div', { class: 'market-tools' }, e.tools.map((t) => h('div', { class: 'market-tool' },
        h('div', { class: 'market-tool-head' }, h('code', {}, t.name), h('span', { class: 'pill' }, RISK_SHORT[t.risk] || t.risk)),
        h('div', { class: 'row-desc' }, t.description),
        h('pre', { class: 'market-argv' }, `$ ${t.argv.join(' ')}`))))] : null,
      e.instructions ? [h('div', { class: 'field-label' }, 'Инструкция для агента'), h('div', { class: 'prose market-instructions', html: markdown(e.instructions) })] : null,
      h('div', { class: 'modal-actions' }, actions(e, true)),
    ).classList.add('modal-wide');
  }

  function card(e) {
    return h('div', { class: `market-card${e.installed ? ' installed' : ''}`, role: 'button', tabindex: '0', onclick: () => details(e), onkeydown: (ev) => { if (ev.key === 'Enter') details(e); } },
      h('div', { class: 'market-card-head' }, h('span', { class: 'market-icon' }, icon(extIcon(e))), h('div', { class: 'market-title' }, h('div', {}, txt(e.name)), h('div', { class: 'market-meta' }, [e.author, e.installed?.source === 'custom' ? 'ваш пакет' : `v${e.version}`].filter(Boolean).join(' · ')))),
      h('p', { class: 'market-summary' }, txt(e.summary)),
      h('div', { class: 'market-tags' }, extKind(e).map((k) => h('span', { class: 'pill tag-kind' }, k))),
      h('div', { class: 'market-foot' }, actions(e)));
  }

  function render() {
    const q = search.value.trim().toLowerCase();
    const shown = items.filter((e) => ({ all: true, skills: !!e.instructions, tools: e.tools.length > 0, installed: !!e.installed }[filter]))
      .filter((e) => !q || [txt(e.name), txt(e.summary), txt(e.description), e.id, ...(e.tags || []), ...e.tools.map((t) => t.name)].join(' ').toLowerCase().includes(q));
    grid.replaceChildren(...(shown.length ? shown.map(card) : [h('div', { class: 'empty' }, filter === 'installed' && !q ? 'Пока ничего не установлено.' : 'Ничего не нашлось.')]));
  }

  async function load() {
    const data = await get('/v1/marketplace');
    items = data.items;
    note.textContent = data.error ? 'Каталог mensarium.com сейчас недоступен, показаны пакеты из этой версии Mensarium.' : '';
    note.classList.toggle('hidden', !data.error);
    renderFilters();
    render();
  }

  function addCustom() {
    const ta = h('textarea', { class: 'market-yaml', rows: 14, spellcheck: 'false', 'aria-label': 'Манифест пакета',
      placeholder: 'id: my-skill\nname: {en: My skill, ru: Мой навык}\nversion: 1.0.0\nsummary: Коротко, что делает\ninstructions: |\n  # Как работать\n  1. ...' });
    const save = h('button', { class: 'btn btn-primary' }, 'Установить');
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        await api('/v1/extensions/custom', { method: 'POST', body: ta.value, headers: { 'Content-Type': 'text/plain' } });
        closeLayer();
        toast('Пакет установлен');
        await load();
      } catch (err) { fail(err); } finally { save.disabled = false; }
    });
    openModal(
      h('div', { class: 'modal-head' }, h('h2', {}, 'Свой навык или инструмент'), h('button', { class: 'icon-btn', onclick: closeLayer, 'aria-label': 'Закрыть' }, icon('x'))),
      h('p', {}, 'Вставьте манифест в YAML. Навык — это поле instructions с инструкцией для агента, инструмент — список tools с командой в argv; можно и то и другое. Формат тот же, что у пакетов каталога.'),
      ta,
      h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: closeLayer }, 'Отмена'), save),
    ).classList.add('modal-wide');
    ta.focus();
  }

  search.addEventListener('input', render);
  page(shell, 'Маркетплейс', 'Навыки подсказывают агенту, как делать работу, инструменты дают ему готовые команды. Установленное агент видит со следующего шага; команды по-прежнему идут через подтверждение и списки разрешённых программ устройства.',
    h('button', { class: 'btn', onclick: addCustom }, icon('plus'), 'Добавить свой'),
    h('div', { class: 'market-bar' }, filterBar, h('div', { class: 'settings-search market-search' }, icon('search'), search)),
    note,
    grid,
  );
  await load();
}

async function settingsProfiles(shell) {
  const profiles = await get('/v1/agent-profiles');
  page(shell, 'Профили', 'Профиль задаёт инструменты агента, его лимиты и действия, которые в режиме с запросом ждут подтверждения.', null,
    profiles.map((p) => section(`${p.name}, версия ${p.version}`, p.id, h('div', { class: 'rows' },
      row('Модель', `Температура ${p.llm.temperature}`, p.llm.model, true),
      row('Инструменты', null, null),
      h('div', { class: 'row-extra' }, p.allowed_tools.map((t) => h('span', { class: 'pill tag' }, t))),
      row('Требуют подтверждения', 'В режиме «С запросом действий» каждое такое действие вы одобряете отдельно.', h('span', {}, p.approval.required_risks.map((r) => (RISK[r] || [r])[0]).join(', '))),
      row('Лимиты', null, `${p.limits.max_steps} шагов, ${p.limits.max_tool_calls} действий, ${Math.round(p.limits.max_wall_time_s / 60)} мин`),
    ))),
  );
}

async function settingsAudit(shell) {
  const LABELS = {
    'task.created': 'Создана задача', 'task.succeeded': 'Задача завершена', 'task.stopped': 'Задача остановлена',
    'tool.execute': 'Отправлено на устройство', 'tool.result': 'Результат от устройства', 'tool.denied': 'Запрещено политикой',
    'approval.requested': 'Запрошено подтверждение', 'approval.approved': 'Подтверждено', 'approval.rejected': 'Отклонено',
    'target.paired': 'Устройство сопряжено', 'target.revoked': 'Доступ устройства отозван', 'pairing.code_created': 'Создан код сопряжения',
    'core.started': 'Core запущен', 'task.cancel': 'Отмена задачи', 'task.pause': 'Пауза задачи', 'task.resume': 'Задача продолжена',
    'task.deleted': 'Чат удалён', 'task.mode': 'Смена режима доступа', 'profile.imported': 'Импортирован профиль',
    'task.model': 'Смена модели в чате', 'llm.default_model': 'Смена модели по умолчанию',
    'target.tool': 'Инструмент устройства переключён',
    'extension.installed': 'Установлен пакет', 'extension.toggled': 'Пакет включён или выключен', 'extension.removed': 'Удалён пакет',
    'tool.core': 'Инструмент Core',
    'memory.note_created': 'Создана заметка', 'memory.note_updated': 'Изменена заметка', 'memory.note_deleted': 'Удалена заметка',
    'memory.dreamed': 'Сновидение', 'memory.dream_started': 'Запущено сновидение', 'memory.dream_settings': 'Настройки сновидений',
  };
  const ACTORS = { core: 'Core', target: 'устройство', user: 'вы' };
  const describe = (p) => {
    const title = p.task_id ? state.tasks.find((t) => t.id === p.task_id) : null;
    return [
      p.display || p.tool,
      p.name,
      p.title,
      p.id && !p.task_id && p.id,
      p.created != null && `новых заметок: ${p.created}`,
      p.source === 'custom' && 'свой пакет',
      p.status && (EXEC_STATUS[p.status] || statusOf(p.status)[0]),
      p.exit_code != null && `код ${p.exit_code}`,
      p.mode && (MODES[p.mode]?.label || p.mode),
      p.model,
      p.enabled != null && `${p.tool}: ${p.enabled ? 'включён' : 'выключен'}`,
      p.reason && policyText(reasonText(p.reason)),
      p.version && `версия ${p.version}`,
      p.task_id && (title ? `«${taskTitle(title)}»` : 'удалённый чат'),
    ].filter(Boolean).join(' · ');
  };
  const list = h('div', {});
  const load = async () => {
    const events = await get('/v1/audit?limit=200');
    list.replaceChildren(events.length ? h('div', { class: 'rows' }, events.map((e) => h('div', { class: 'audit-item' },
      h('div', { class: 'audit-time' }, new Date(e.created_at).toLocaleString('ru-RU'), h('div', { class: 'mono', title: e.hash }, e.hash.slice(7, 17))),
      h('div', {}, h('div', { class: 'audit-type' }, LABELS[e.event_type] || e.event_type, h('span', { class: 'audit-actor' }, ` · ${ACTORS[e.actor] || e.actor}`)),
        h('div', { class: 'audit-payload', title: JSON.stringify(e.payload) }, describe(e.payload)))))) : h('div', { class: 'rows' }, h('div', { class: 'empty' }, 'Событий пока нет.')));
  };
  page(shell, 'Журнал действий', 'Каждое событие связано с предыдущим хешем, поэтому запись нельзя незаметно изменить или удалить.',
    h('button', { class: 'btn', onclick: () => load().catch(fail) }, icon('refresh'), 'Обновить'),
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
