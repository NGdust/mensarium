// Mensarium web UI. Vanilla ES module, no build step, no dependencies.

import { createOrb } from './orb.js';

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
  const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inlineMd(i)}</li>`).join('')}</${list.tag}>`); list = null; };
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
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const heading = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (bullet || numbered) {
      flushPara();
      const tag = bullet ? 'ul' : 'ol';
      if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
      list.items.push((bullet || numbered)[1]);
    } else if (heading) {
      flushPara(); flushList();
      out.push(`<h3>${inlineMd(heading[1])}</h3>`);
    } else if (!line.trim()) {
      flushPara(); flushList();
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
const TOOL_ICON = { 'files.list': 'folder', 'files.read': 'file', 'files.search': 'search', 'git.status': 'git', 'git.diff': 'git', 'shell.exec': 'terminal' };
const RESUMABLE = ['PAUSED', 'FAILED_RECOVERABLE'];

const POLICY_REASONS = [
  [/^access to secret files is not allowed$/, () => 'чтение секретных файлов запрещено'],
  [/^unknown tool '(.+)'$/, (m) => `неизвестный инструмент ${m[1]}`],
  [/^tool '(.+)' is not allowed by the active profile$/, (m) => `инструмент ${m[1]} не разрешён профилем`],
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
      h('pre', { class: 'approval-cmd' }, tc.tool === 'shell.exec' ? `$ ${args.command}` : short(tc.display)),
      h('dl', { class: 'approval-meta' },
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
  const views = { overview: settingsOverview, model: settingsModel, devices: settingsDevices, profiles: settingsProfiles, audit: settingsAudit };
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

async function settingsDevices(shell) {
  const s = state.system || await get('/v1/system');
  const listHost = h('div', {});
  const render = () => {
    const targets = devices();
    if (!targets.length) {
      listHost.replaceChildren(h('div', { class: 'rows' }, h('div', { class: 'empty' },
        h('h3', {}, 'Устройств пока нет'), h('p', {}, 'Сопрягите машину, на которой агент будет работать.'),
        h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), 'Сопрячь устройство'))));
      return;
    }
    listHost.replaceChildren(h('div', { class: 'rows' }, targets.map((t) => {
      const caps = t.capabilities || {};
      const outdated = t.agent_version && s.version && t.agent_version !== s.version;
      const programs = caps.command_allowlist || [];
      const revoke = h('button', { class: 'btn btn-sm btn-danger', onclick: async () => {
        if (!await confirmDialog({ title: `Отозвать «${t.name}»?`, text: 'Устройство сразу потеряет доступ. Чтобы вернуть его, понадобится новое сопряжение по коду.', action: 'Отозвать', danger: true })) return;
        try { await post(`/v1/targets/${t.id}/revoke`); toast('Доступ отозван'); await refreshData(); render(); } catch (err) { fail(err); }
      } }, 'Отозвать');
      return [
        h('div', { class: 'row' },
          h('div', { class: 'row-text' },
            h('div', { class: 'row-title' }, t.name,
              isLocal(t) ? h('span', { class: 'pill accent', title: 'Машина, на которой установлен Core. Подключена всегда.' }, 'Core') : null,
              outdated ? h('span', { class: 'pill warn', title: 'Выполните на устройстве: mensarium update' }, `v${t.agent_version}, есть обновление`) : null),
            h('div', { class: 'row-desc' }, t.status === 'online' ? t.platform : `${t.platform} · был в сети ${relTime(t.last_seen_at)}`)),
          h('div', { class: 'row-value' }, h('span', { class: 'status' }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), t.status === 'online' ? 'В сети' : 'Не в сети'), revoke)),
        h('div', { class: 'row-extra' },
          (caps.roots || []).map((r) => h('span', { class: 'pill tag', title: `Папка, доступная агенту: ${r}` }, r)),
          h('span', { class: 'pill', title: programs.join(', ') }, programs.includes('*') ? 'любые программы' : `${programs.length} программ`),
          caps.full_access === 'outdated' ? h('span', { class: 'pill warn', title: fullAccessBlock(t) }, 'полный доступ: обновите агент')
            : caps.full_access === 'allowed' ? null : h('span', { class: 'pill', title: fullAccessBlock(t) }, 'без полного доступа')),
      ];
    })));
  };
  const refresh = async () => { try { await refreshData(); render(); } catch (err) { fail(err); } };
  page(shell, 'Устройства', 'Машины, на которых агент читает проекты и выполняет команды.',
    h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), 'Сопрячь устройство'),
    listHost,
  );
  render();
  const iv = setInterval(refresh, 5000);
  viewCleanups.push(() => clearInterval(iv));
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
  };
  const ACTORS = { core: 'Core', target: 'устройство', user: 'вы' };
  const describe = (p) => {
    const title = p.task_id ? state.tasks.find((t) => t.id === p.task_id) : null;
    return [
      p.display || p.tool,
      p.name,
      p.status && (EXEC_STATUS[p.status] || statusOf(p.status)[0]),
      p.exit_code != null && `код ${p.exit_code}`,
      p.mode && (MODES[p.mode]?.label || p.mode),
      p.model,
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
