// Mensarium web UI. Vanilla ES module, no build step, no dependencies.

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
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  laptop: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
  sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  chevronRight: '<path d="m9 6 6 6-6 6"/>',
  arrowLeft: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
  arrowUp: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  shield: '<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6z"/><path d="m9 12 2 2 4-4"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  play: '<path d="M7 5v14l12-7z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h11"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
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
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
};

function icon(name) {
  const span = document.createElement('span');
  span.innerHTML = `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  return span.firstChild;
}

const AGENT_FACE = '<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="4" y="10" width="24" height="12" rx="6" fill="#17161f"/><circle cx="11.5" cy="16" r="2.6" fill="#e8c35a"/><circle cx="20.5" cy="16" r="2.6" fill="#e8c35a"/></svg>';
const agentAvatar = (cls = '') => h('div', { class: `avatar agent ${cls}`, html: AGENT_FACE });
const userAvatar = (cls = '') => h('div', { class: `avatar ${cls}` }, 'А');

function toast(message, isError = false) {
  const t = h('div', { class: `toast${isError ? ' error' : ''}` }, message);
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

// ---------- domain vocab ----------

const STATUS = {
  NEW: ['Запуск', 'accent', true],
  VALIDATING: ['Запуск', 'accent', true],
  PLANNING: ['Думает', 'accent', true],
  WAITING_APPROVAL: ['Ждёт подтверждения', 'warn', true],
  EXECUTING: ['Выполняет', 'accent', true],
  OBSERVING: ['Разбирает результат', 'accent', true],
  SUCCEEDED: ['Готово', 'ok', false],
  FAILED: ['Ошибка', 'danger', false],
  FAILED_RECOVERABLE: ['Прервано, можно продолжить', 'danger', false],
  CANCELED: ['Отменено', '', false],
  PAUSED: ['Пауза', 'warn', false],
};
const RISK = {
  read: ['чтение', ''],
  write: ['изменение файлов', 'warn'],
  execute: ['запуск программы', 'orange'],
  network: ['доступ в сеть', 'accent'],
  destructive: ['необратимое действие', 'danger'],
};
const TOOL_ICON = { 'files.list': 'folder', 'files.read': 'file', 'files.search': 'search', 'git.status': 'git', 'git.diff': 'git', 'shell.exec': 'terminal' };

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
const reasonText = (r) => REASONS[r] || r;
const statusOf = (s) => STATUS[s] || [s, '', false];
const isRunning = (s) => statusOf(s)[2];
const RESUMABLE = ['PAUSED', 'FAILED_RECOVERABLE'];

function statusPill(status) {
  const [label, kind, live] = statusOf(status);
  return h('span', { class: `pill ${kind}` }, h('span', { class: `dot ${kind}${live ? ' live' : ''}` }), label);
}
const taskTitle = (t) => ((t.input || '').split('\n')[0] || 'Без названия').slice(0, 80);

// ---------- theme ----------

function currentTheme() {
  const saved = document.documentElement.dataset.theme;
  if (saved) return saved;
  return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}
function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch { /* storage unavailable */ }
}
try { const t = localStorage.getItem('theme'); if (t) document.documentElement.dataset.theme = t; } catch { /* ignore */ }

// ---------- overlays ----------

function closeLayer() { $layer.replaceChildren(); }

function openPopover(anchor, items) {
  closeLayer();
  const pop = h('div', { class: 'popover', role: 'menu' }, items);
  const catcher = h('div', { style: 'position:fixed;inset:0;z-index:49', onclick: closeLayer });
  $layer.append(catcher, pop);
  const r = anchor.getBoundingClientRect();
  const ph = pop.offsetHeight;
  const top = r.top - ph - 8 > 8 ? r.top - ph - 8 : r.bottom + 8;
  pop.style.top = `${top}px`;
  pop.style.left = `${Math.min(r.left, innerWidth - pop.offsetWidth - 8)}px`;
}

function openModal(...content) {
  closeLayer();
  const modal = h('div', { class: 'modal', role: 'dialog' }, content);
  const backdrop = h('div', { class: 'backdrop', onclick: (e) => { if (e.target === backdrop) closeLayer(); } }, modal);
  $layer.append(backdrop);
  return modal;
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
  const input = h('input', { type: 'password', placeholder: 'Токен администратора', autocomplete: 'off' });
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
    agentAvatar(),
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

// ---------- app shell (chat) ----------

function ensureAppShell() {
  if (state.shell && state.shell.kind === 'app') return state.shell;
  cleanupAll();
  const sessions = h('div', { class: 'sessions' });
  const main = h('main', { class: 'main' });
  const shell = h('div', { class: 'shell' });
  const meBtn = h('button', { class: 'me', onclick: () => toggleUserMenu() }, userAvatar('sm'), 'Администратор');
  const sidebar = h('aside', { class: 'sidebar' },
    h('div', { class: 'brand' },
      agentAvatar('sm'),
      h('span', { class: 'brand-name' }, 'Mensarium'),
      h('button', { class: 'icon-btn', title: 'Новый чат', 'aria-label': 'Новый чат', onclick: () => go('#/') }, icon('plus')),
    ),
    h('nav', { class: 'nav' },
      h('a', { class: 'nav-item', href: '#/', 'data-nav': 'new' }, icon('home'), 'Новый чат'),
      h('a', { class: 'nav-item', href: '#/settings/devices', 'data-nav': 'devices' }, icon('laptop'), 'Устройства'),
    ),
    h('div', { class: 'sessions-head' }, h('span', { class: 'section-label' }, 'Сеансы')),
    sessions,
    h('div', { class: 'sidebar-foot' }, meBtn,
      h('button', { class: 'icon-btn', title: 'Настройки', 'aria-label': 'Настройки', onclick: () => go('#/settings/overview') }, icon('sliders'))),
  );
  shell.append(sidebar, main);
  $app.replaceChildren(shell);

  const menuHost = h('div', {});
  sidebar.append(menuHost);
  function toggleUserMenu() {
    if (menuHost.firstChild) { menuHost.replaceChildren(); return; }
    const item = (ic, label, fn, kbd) => h('button', { class: 'menu-item', onclick: () => { menuHost.replaceChildren(); fn(); } }, icon(ic), label, kbd ? h('span', { class: 'kbd' }, kbd) : null);
    menuHost.append(h('div', { class: 'menu' },
      h('div', { class: 'menu-head' }, userAvatar('sm'), 'Администратор'),
      item('sliders', 'Настройки', () => go('#/settings/overview'), '⌘,'),
      item('link', 'Сопрячь устройство', openPairing),
      item('laptop', 'Устройства', () => go('#/settings/devices')),
      item('list', 'Журнал действий', () => go('#/settings/audit')),
      h('div', { class: 'menu-sep' }),
      item(currentTheme() === 'dark' ? 'sun' : 'moon', currentTheme() === 'dark' ? 'Светлая тема' : 'Тёмная тема', toggleTheme),
      item('logout', 'Выйти', async () => { try { await post('/v1/auth/logout'); } catch { /* noop */ } showLogin(); }),
    ));
  }

  const collapsed = new Set(JSON.parse(localStorageGet('collapsed') || '[]'));
  function renderSessions() {
    const byTarget = new Map();
    state.tasks.forEach((t) => {
      const key = t.target_name || 'Другие';
      if (!byTarget.has(key)) byTarget.set(key, []);
      byTarget.get(key).push(t);
    });
    const activeId = (location.hash.match(/^#\/chat\/(.+)$/) || [])[1];
    if (!state.tasks.length) {
      sessions.replaceChildren(h('div', { class: 'sessions-empty' }, 'Здесь появятся ваши чаты с агентом.'));
      return;
    }
    sessions.replaceChildren(...[...byTarget.entries()].map(([name, tasks]) => {
      const group = h('div', { class: `group${collapsed.has(name) ? ' collapsed' : ''}` });
      const head = h('button', { class: 'group-head', onclick: () => {
        group.classList.toggle('collapsed');
        if (group.classList.contains('collapsed')) collapsed.add(name); else collapsed.delete(name);
        localStorageSet('collapsed', JSON.stringify([...collapsed]));
      } }, icon('chevron'), name);
      const items = h('div', { class: 'group-items' }, tasks.map((t) => {
        const [, kind, live] = statusOf(t.status);
        return h('a', { class: `session${t.id === activeId ? ' active' : ''}`, href: `#/chat/${t.id}`, title: t.input },
          h('span', { class: `dot ${kind}${live ? ' live' : ''}` }),
          h('span', { class: 'session-title' }, taskTitle(t)));
      }));
      group.append(head, items);
      return group;
    }));
  }

  const poll = async () => {
    try { await refreshData(); renderSessions(); } catch (err) { if (err instanceof AuthError) showLogin(); }
  };
  const iv = setInterval(poll, 4000);
  shellCleanups.push(() => clearInterval(iv));

  state.shell = {
    kind: 'app', main, renderSessions,
    setActive(navKey) {
      sidebar.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === navKey));
      shell.classList.remove('nav-open');
      renderSessions();
    },
    toggleNav: () => shell.classList.toggle('nav-open'),
  };
  renderSessions();
  return state.shell;
}

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }

function topbar(shell, crumbs, actions) {
  return h('header', { class: 'topbar' },
    h('button', { class: 'icon-btn menu-toggle', 'aria-label': 'Меню', onclick: shell.toggleNav }, icon('menu')),
    h('div', { class: 'crumbs' }, crumbs),
    h('div', { class: 'topbar-actions' }, actions),
  );
}

// ---------- composer ----------

function composer({ placeholder, chips, onSend }) {
  const ta = h('textarea', { rows: 1, placeholder });
  const send = h('button', { class: 'send', 'aria-label': 'Отправить', disabled: true }, icon('arrowUp'));
  const model = state.system?.provider?.model;
  const box = h('div', { class: 'composer' }, ta, h('div', { class: 'composer-bar' },
    chips,
    h('span', { class: 'spacer' }),
    model ? h('span', { class: 'chip chip-compact', title: 'Модель задаётся в настройках Core' }, icon('sparkle'), h('span', { class: 'chip-label' }, model)) : null,
    send,
  ));
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
    setLocked(value, hint) { locked = value; ta.disabled = value; ta.placeholder = value ? hint : placeholder; sync(); },
  };
}

const modeChip = () => h('span', { class: 'chip accent chip-compact', title: 'Чтение выполняется сразу. Запуск программ, изменения и сеть требуют вашего подтверждения.' },
  icon('shield'), h('span', { class: 'chip-label' }, 'С подтверждением действий'));

// ---------- new chat ----------

async function viewNewChat() {
  const shell = ensureAppShell();
  shell.setActive('new');
  const online = state.targets.filter((t) => t.status === 'online');
  let selected = online.find((t) => t.id === localStorageGet('target')) || online[0] || null;

  const chipLabel = h('span', { class: 'chip-label' });
  const chipDot = h('span', { class: 'dot' });
  const targetChip = h('button', { class: 'chip', onclick: () => pickTarget() }, icon('laptop'), chipDot, chipLabel, icon('chevron'));
  const renderChip = () => {
    chipLabel.textContent = selected ? selected.name : 'Выберите устройство';
    chipDot.className = `dot${selected ? ' ok' : ''}`;
  };
  function pickTarget() {
    const items = state.targets.filter((t) => t.status !== 'revoked').map((t) => h('button', {
      class: 'menu-item', disabled: t.status !== 'online',
      onclick: () => { selected = t; localStorageSet('target', t.id); renderChip(); closeLayer(); },
    }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), t.name, h('span', { class: 'popover-sub' }, t.status === 'online' ? t.platform : 'не в сети')));
    items.push(h('div', { class: 'menu-sep' }), h('button', { class: 'menu-item', onclick: () => { closeLayer(); openPairing(); } }, icon('plus'), 'Сопрячь новое устройство'));
    openPopover(targetChip, items);
  }
  renderChip();

  const c = composer({
    placeholder: 'Сообщение для Mensarium',
    chips: [targetChip, modeChip()],
    onSend: async (text) => {
      if (!selected) throw new Error('Выберите устройство, на котором агент будет работать');
      const task = await post('/v1/tasks', { target_id: selected.id, input: text });
      state.tasks.unshift(task);
      go(`#/chat/${task.id}`);
    },
  });

  const hasDevices = state.targets.some((t) => t.status !== 'revoked');
  const content = hasDevices
    ? h('div', { class: 'welcome-inner' },
      h('div', { class: 'welcome-head' }, agentAvatar(), h('h1', {}, 'Что нужно сделать?')),
      c.el,
      h('p', { class: 'welcome-hint' }, online.length
        ? 'Агент изучит проект сам. Перед запуском команд и изменением файлов он спросит разрешения.'
        : 'Все устройства сейчас не в сети. Запустите на нужной машине mensarium target run.'))
    : h('div', { class: 'welcome-inner' }, h('div', { class: 'rows' }, h('div', { class: 'empty' },
      h('h3', {}, 'Подключите первое устройство'),
      h('p', {}, 'Агент работает на ваших машинах через Mensarium Target. Сопряжение займёт минуту.'),
      h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), 'Сопрячь устройство'))));

  shell.main.replaceChildren(
    topbar(shell, [icon('home'), h('span', { class: 'current' }, 'Новый чат')]),
    h('div', { class: 'welcome' }, content),
  );
  if (hasDevices) c.textarea.focus();
}

// ---------- chat ----------

async function viewChat(taskId) {
  const shell = ensureAppShell();
  shell.setActive(null);
  let task;
  try { task = await get(`/v1/tasks/${taskId}`); } catch (err) { fail(err); go('#/'); return; }
  state.lastChat = `#/chat/${taskId}`;

  const statusSlot = h('span', {});
  const btnPause = h('button', { class: 'icon-btn', title: 'Пауза', 'aria-label': 'Пауза', onclick: () => act('pause') }, icon('pause'));
  const btnResume = h('button', { class: 'icon-btn', title: 'Продолжить', 'aria-label': 'Продолжить', onclick: () => act('resume') }, icon('play'));
  const btnCancel = h('button', { class: 'icon-btn', title: 'Остановить задачу', 'aria-label': 'Остановить', onclick: () => { if (confirm('Остановить задачу? Продолжить её будет нельзя.')) act('cancel'); } }, icon('stop'));
  const thread = h('div', { class: 'thread' });
  const inner = h('div', { class: 'thread-inner' });
  thread.append(inner);

  const roots = (state.targets.find((t) => t.id === task.target_id)?.capabilities?.roots || []).slice().sort((a, b) => b.length - a.length);
  const short = (text) => roots.reduce((acc, r) => acc.split(r).join(r.split('/').pop() || r), String(text || ''));
  const deviceChip = h('span', { class: 'chip', title: 'Устройство задачи' }, icon('laptop'), h('span', { class: 'chip-label' }, task.target_name || task.target_id));
  const c = composer({
    placeholder: 'Ответить Mensarium',
    chips: [deviceChip, modeChip()],
    onSend: (text) => post(`/v1/tasks/${taskId}/messages`, { input: text }),
  });

  shell.main.replaceChildren(
    topbar(shell, [icon('folder'), h('span', {}, task.target_name || 'устройство'), h('span', { class: 'sep' }, '/'), h('span', { class: 'current', title: task.input }, taskTitle(task))],
      [statusSlot, btnPause, btnResume, btnCancel]),
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
  async function act(action) {
    try { const t = await post(`/v1/tasks/${taskId}/${action}`); setStatus(t.status); } catch (err) { fail(err); }
  }
  setStatus(task.status);

  // --- rendering ---
  const nearBottom = () => thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
  let stick = true;
  thread.addEventListener('scroll', () => { stick = nearBottom(); });
  const add = (node) => { inner.append(node); if (stick) thread.scrollTop = thread.scrollHeight; return node; };
  let lastAgent = false;

  const agentMsg = (bodyNode) => {
    const node = h('div', { class: `msg msg-agent${lastAgent ? ' cont' : ''}` }, agentAvatar(), h('div', { class: 'msg-body' }, bodyNode));
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
    const head = h('button', { class: 'tool-head', onclick: () => card.classList.toggle('open') },
      icon(TOOL_ICON[tool] || 'terminal'), h('span', { class: 'tool-name' }, tool), h('span', { class: 'tool-display', title: display || '' }, short(display)), stateEl);
    card.append(head, out, noteEl);
    step(card);
    entry = { card, stateEl, out, noteEl };
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
    if (!ok || p.tool === 'shell.exec' || p.tool === 'git.diff') e.card.classList.add('open');
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
    const card = h('div', { class: `approval${tc.risk === 'destructive' ? ' risk-destructive' : ''}` },
      h('div', { class: 'approval-top' }, h('span', { class: 'approval-title' }, 'Нужно ваше решение'), h('span', { class: `pill ${riskKind}` }, riskLabel), timer),
      h('pre', { class: 'approval-cmd' }, tc.tool === 'shell.exec' ? `$ ${args.command}` : short(tc.display)),
      h('dl', { class: 'approval-meta' },
        h('dt', {}, 'Устройство'), h('dd', {}, tc.target_name || ''),
        args.cwd ? [h('dt', {}, 'Папка'), h('dd', { title: args.cwd }, short(args.cwd))] : null,
        tc.tool !== 'shell.exec' ? [h('dt', {}, 'Инструмент'), h('dd', {}, tc.tool)] : null,
        args.timeout_s ? [h('dt', {}, 'Лимит'), h('dd', {}, `${args.timeout_s} с`)] : null,
      ),
      args.stdin ? [h('div', { class: 'section-label', style: 'margin-bottom:6px' }, 'Данные на вход'), h('pre', { class: 'approval-cmd approval-stdin' }, args.stdin)] : null,
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
    e.actions.replaceChildren(h('span', { class: 'approval-result' }, text, p.note ? `: ${p.note}` : ''));
  }

  function handle({ event, payload: p }) {
    switch (event) {
      case 'user.message':
        lastAgent = false;
        add(h('div', { class: 'msg msg-user' }, userAvatar(), h('div', { class: 'msg-body' },
          h('div', { class: 'bubble-user' }, p.text), h('div', { class: 'msg-author' }, 'Администратор'))));
        break;
      case 'task.status':
        setStatus(p.status);
        if (['PAUSED', 'CANCELED', 'FAILED', 'FAILED_RECOVERABLE'].includes(p.status)) {
          note(p.status === 'PAUSED' ? 'pause' : 'alert', `${statusOf(p.status)[0]}${p.reason ? `: ${reasonText(p.reason)}` : ''}`, p.status === 'PAUSED' || p.status === 'CANCELED' ? '' : 'error');
        }
        break;
      case 'llm.request':
        thinking.set(p.step, agentMsg(h('span', { class: 'thinking' }, h('i'), h('i'), h('i'), 'Думает')));
        break;
      case 'llm.response': {
        const row = thinking.get(p.step);
        if (row) { row.remove(); thinking.delete(p.step); lastAgent = inner.lastChild?.classList?.contains('msg-agent') || inner.lastChild?.classList?.contains('step') || false; }
        if (p.text && p.tool_call) agentMsg(h('div', { class: 'prose', html: markdown(p.text) }));
        break;
      }
      case 'tool_call.denied':
        note('ban', `Политика не разрешила ${p.tool}: ${p.reason}`);
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
  { group: null, items: [['overview', 'pulse', 'Обзор'], ['model', 'cpu', 'Модель']] },
  { group: 'Подключения', items: [['devices', 'laptop', 'Устройства']] },
  { group: 'Агенты', items: [['profiles', 'layers', 'Профили']] },
  { group: 'Безопасность', items: [['audit', 'list', 'Журнал действий']] },
];

function ensureSettingsShell() {
  if (state.shell && state.shell.kind === 'settings') return state.shell;
  cleanupAll();
  const main = h('main', { class: 'main' });
  const nav = h('div', { class: 'settings-nav' });
  const search = h('input', { type: 'search', placeholder: 'Поиск настроек...' });
  const back = () => go(state.lastChat || '#/');
  const shell = h('div', { class: 'shell' });
  const sidebar = h('aside', { class: 'sidebar' },
    h('button', { class: 'back-link', onclick: back }, icon('arrowLeft'), 'Вернуться в чат', h('span', { class: 'kbd' }, 'ESC')),
    h('div', { class: 'settings-title' }, 'Настройки'),
    h('div', { class: 'settings-search' }, icon('search'), search),
    nav,
    h('div', { class: 'settings-foot' }, state.system?.version ? `v${state.system.version}` : ''),
  );
  shell.append(sidebar, main);
  $app.replaceChildren(shell);

  const renderNav = () => {
    const q = search.value.trim().toLowerCase();
    const active = (location.hash.match(/^#\/settings\/(\w+)/) || [])[1];
    nav.replaceChildren(...SETTINGS.map(({ group, items }) => {
      const visible = items.filter(([, , label]) => !q || label.toLowerCase().includes(q));
      if (!visible.length) return null;
      return h('div', {},
        group ? h('div', { class: 'settings-group section-label' }, group) : null,
        visible.map(([key, ic, label]) => h('a', { class: `nav-item${key === active ? ' active' : ''}`, href: `#/settings/${key}` }, icon(ic), label)));
    }).filter(Boolean));
  };
  search.addEventListener('input', renderNav);
  const onKey = (e) => { if (e.key === 'Escape' && !$layer.firstChild) back(); };
  document.addEventListener('keydown', onKey);
  shellCleanups.push(() => document.removeEventListener('keydown', onKey));

  state.shell = {
    kind: 'settings', main, toggleNav: () => shell.classList.toggle('nav-open'),
    setActive() { renderNav(); shell.classList.remove('nav-open'); },
  };
  return state.shell;
}

function page(shell, title, desc, actions, ...sections) {
  shell.main.replaceChildren(
    h('header', { class: 'topbar', style: 'height:auto;padding:10px 12px 0' }, h('button', { class: 'icon-btn menu-toggle', 'aria-label': 'Меню', onclick: shell.toggleNav }, icon('menu'))),
    h('div', { class: 'page' }, h('div', { class: 'page-inner' },
      h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, title), desc ? h('p', {}, desc) : null), actions ? h('div', { class: 'actions' }, actions) : null),
      sections,
    )),
  );
}

const section = (label, desc, actions, ...body) => h('section', { class: 'section' },
  h('div', { class: 'section-head' }, h('div', {}, h('div', { class: 'section-label' }, label), desc ? h('p', {}, desc) : null), actions ? h('div', { class: 'actions' }, actions) : null),
  body);

const row = (title, desc, value, mono = false) => h('div', { class: 'row' },
  h('div', { class: 'row-text' }, h('div', { class: 'row-title' }, title), desc ? h('div', { class: 'row-desc' }, desc) : null),
  value != null ? h('div', { class: `row-value${mono ? ' mono' : ''}` }, value) : null);

const copyBtn = (text) => h('button', { class: 'icon-btn', 'aria-label': 'Скопировать', onclick: (e) => copy(text, e.currentTarget) }, icon('copy'));
const refreshBtn = (fn) => h('button', { class: 'btn', onclick: fn }, icon('refresh'), 'Обновить');

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
  const online = state.targets.filter((t) => t.status === 'online').length;
  page(shell, 'Обзор', 'Главный агент Mensarium: где он доступен и как к нему подключать устройства.', refreshBtn(() => viewSettings('overview')),
    h('div', { class: 'hero' }, agentAvatar(), h('h2', {}, 'Mensarium Core'), h('span', { class: 'pill accent' }, `ВЕРСИЯ ${s.version}`)),
    section('Подключение', 'Эти данные нужны, чтобы устройства нашли Core и доверяли ему.', null, h('div', { class: 'rows' },
      row('Адрес Core', 'Используется браузером и устройствами.', [h('span', {}, url), copyBtn(url)], true),
      row('Отпечаток ключа', 'Сверьте с тем, что показал установщик на устройстве при сопряжении.', s.core_key_fingerprint, true),
      row('Устройства в сети', null, `${online} из ${state.targets.filter((t) => t.status !== 'revoked').length}`),
      row('Рабочее пространство', null, s.workspace_id, true),
    )),
    section('Обслуживание', 'Команды выполняются на сервере Core.', null, h('div', { class: 'rows' },
      row('Обновить Mensarium', 'Скачивает свежую версию и перезапускает сервис.', h('code', {}, 'mensarium update'), true),
      row('Резервная копия', 'Зашифрованный архив для переноса Core на другой сервер.', h('code', {}, 'mensarium core backup'), true),
      row('Токен входа', 'Показать токен администратора.', h('code', {}, 'mensarium core token'), true),
    )),
  );
}

async function settingsModel(shell) {
  const s = await get('/v1/system');
  const p = s.provider || {};
  const health = p.health || {};
  const providerName = { ollama_cloud: 'Ollama Cloud', ollama_local: 'Локальный Ollama', llama_cpp: 'llama.cpp' }[p.name] || p.name;
  const list = h('div', { class: 'rows' }, h('div', { class: 'empty' }, 'Загружаем список...'));
  page(shell, 'Модель', 'Через какого провайдера и какую модель агент думает. Ключ API хранится только на сервере Core.', refreshBtn(() => viewSettings('model')),
    h('div', { class: 'rows' },
      row('Провайдер', null, providerName),
      row('Адрес API', null, p.base_url, true),
      row('Модель по умолчанию', 'Меняется командой mensarium setup на сервере Core.', p.model, true),
      row('Состояние', health.detail || null, h('span', { class: 'status' }, h('span', { class: `dot ${health.ok ? 'ok' : 'danger'}` }), health.ok ? 'Доступен' : 'Недоступен')),
    ),
    section('Доступные модели', 'Список, который отдаёт провайдер.', null, list),
  );
  try {
    const models = await get('/v1/models');
    list.replaceChildren(models.length
      ? h('div', { class: 'row-extra', style: 'padding:16px 20px' }, models.map((m) => h('span', { class: `pill tag${m.id === p.model ? ' accent' : ''}` }, m.id)))
      : h('div', { class: 'empty' }, 'Провайдер не вернул ни одной модели.'));
  } catch (err) {
    list.replaceChildren(h('div', { class: 'empty' }, err.message));
  }
}

async function settingsDevices(shell) {
  const s = state.system || await get('/v1/system');
  const listHost = h('div', {});
  const render = () => {
    const targets = state.targets.filter((t) => t.status !== 'revoked');
    if (!targets.length) {
      listHost.replaceChildren(h('div', { class: 'rows' }, h('div', { class: 'empty' },
        h('h3', {}, 'Устройств пока нет'), h('p', {}, 'Сопрягите машину, на которой агент будет работать.'),
        h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), 'Сопрячь устройство'))));
      return;
    }
    listHost.replaceChildren(h('div', { class: 'rows' }, targets.map((t) => {
      const caps = t.capabilities || {};
      const outdated = t.agent_version && s.version && t.agent_version !== s.version;
      const revoke = h('button', { class: 'btn btn-sm btn-danger', onclick: async () => {
        if (!confirm(`Отозвать «${t.name}»? Устройство потеряет доступ, для возврата понадобится новое сопряжение.`)) return;
        try { await post(`/v1/targets/${t.id}/revoke`); toast('Доступ отозван'); await refreshData(); render(); } catch (err) { fail(err); }
      } }, 'Отозвать');
      return [
        h('div', { class: 'row' },
          h('div', { class: 'row-text' },
            h('div', { class: 'row-title' }, t.name, outdated ? h('span', { class: 'pill warn', title: 'Выполните на устройстве: mensarium update' }, `v${t.agent_version}, есть обновление`) : null),
            h('div', { class: 'row-desc' }, `${t.platform} · ${t.hostname} · ${t.status === 'online' ? 'в сети' : `был в сети ${relTime(t.last_seen_at)}`}`)),
          h('div', { class: 'row-value' }, h('span', { class: 'status' }, h('span', { class: `dot${t.status === 'online' ? ' ok' : ''}` }), t.status === 'online' ? 'В сети' : 'Не в сети'), revoke)),
        h('div', { class: 'row-extra' },
          (caps.roots || []).map((r) => h('span', { class: 'pill tag', title: r }, r)),
          h('span', { class: 'pill tag', title: (caps.command_allowlist || []).join(', ') }, (caps.command_allowlist || []).includes('*') ? 'любые программы' : `${(caps.command_allowlist || []).length} программ`)),
      ];
    })));
  };
  const refresh = async () => { try { await refreshData(); render(); } catch (err) { fail(err); } };
  page(shell, 'Устройства', 'Машины, на которых агент может читать проект и, с вашего разрешения, запускать команды.',
    [refreshBtn(refresh), h('button', { class: 'btn btn-primary', onclick: openPairing }, icon('link'), 'Сопрячь устройство')],
    listHost,
    section('Как подключить', 'Сопряжение по одноразовому коду. Код создаётся кнопкой выше или командой mensarium core pair-code на сервере.', null,
      h('div', { class: 'code-line' }, h('code', {}, `curl -fsSL ${(s.public_url || '').replace(/\/$/, '')}/install.sh | sh -s -- --code КОД`), copyBtn(`curl -fsSL ${(s.public_url || '').replace(/\/$/, '')}/install.sh | sh -s -- --code `))),
  );
  render();
  const iv = setInterval(refresh, 5000);
  viewCleanups.push(() => clearInterval(iv));
}

async function settingsProfiles(shell) {
  const profiles = await get('/v1/agent-profiles');
  page(shell, 'Профили', 'Профиль задаёт, какие инструменты доступны агенту, его лимиты и какие действия требуют подтверждения.', null,
    profiles.map((p) => section(`${p.name} · v${p.version}`, p.id, null, h('div', { class: 'rows' },
      row('Модель', `Температура ${p.llm.temperature}`, p.llm.model, true),
      row('Инструменты', null, null),
      h('div', { class: 'row-extra' }, p.allowed_tools.map((t) => h('span', { class: 'pill tag' }, t))),
      row('Требуют подтверждения', 'Каждое такое действие вы одобряете отдельно.', h('span', {}, p.approval.required_risks.map((r) => (RISK[r] || [r])[0]).join(', '))),
      row('Лимиты', null, `${p.limits.max_steps} шагов, ${p.limits.max_tool_calls} действий, ${Math.round(p.limits.max_wall_time_s / 60)} мин`),
    ))),
  );
}

async function settingsAudit(shell) {
  const events = await get('/v1/audit?limit=200');
  const LABELS = {
    'task.created': 'Создана задача', 'task.succeeded': 'Задача завершена', 'task.stopped': 'Задача остановлена',
    'tool.execute': 'Отправлено на устройство', 'tool.result': 'Результат от устройства', 'tool.denied': 'Запрещено политикой',
    'approval.requested': 'Запрошено подтверждение', 'approval.approved': 'Подтверждено', 'approval.rejected': 'Отклонено',
    'target.paired': 'Устройство сопряжено', 'target.revoked': 'Доступ устройства отозван', 'pairing.code_created': 'Создан код сопряжения',
    'core.started': 'Core запущен', 'task.cancel': 'Отмена задачи', 'task.pause': 'Пауза задачи', 'task.resume': 'Задача продолжена',
  };
  page(shell, 'Журнал действий', 'Каждое событие связано с предыдущим хешем, поэтому запись нельзя незаметно изменить или удалить.', refreshBtn(() => viewSettings('audit')),
    events.length ? h('div', { class: 'rows' }, events.map((e) => h('div', { class: 'audit-item' },
      h('div', { class: 'audit-time' }, new Date(e.created_at).toLocaleString('ru-RU'), h('div', { class: 'mono', title: e.hash }, e.hash.slice(7, 17))),
      h('div', {}, h('div', { class: 'audit-type' }, LABELS[e.event_type] || e.event_type, h('span', { class: 'muted', style: 'font-weight:400' }, ` · ${e.actor}`)),
        h('div', { class: 'audit-payload' }, e.payload.display || JSON.stringify(e.payload)))))) : h('div', { class: 'rows' }, h('div', { class: 'empty' }, 'Событий пока нет.')),
  );
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
  if (e.key === 'Escape' && $layer.firstChild) closeLayer();
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
