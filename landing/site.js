// mensarium.com: the hero replays a recorded session in the product's own markup; everything else is static.
import { createOrb } from './vendor/orb.js';

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c);
  return el;
}
function icon(name) {
  const span = document.createElement('span');
  span.innerHTML = `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  return span.firstChild;
}

// ---------- orbs: every [data-orb] placeholder becomes the product's particle sphere ----------
const liveOrbs = {};
for (const ph of document.querySelectorAll('[data-orb]')) {
  const size = Number(ph.dataset.orb);
  const still = ph.hasAttribute('data-still');
  const orb = createOrb(size, { animate: !still && size >= 22, className: ph.className });
  if (ph.dataset.liveId) liveOrbs[ph.dataset.liveId] = orb;
  ph.replaceWith(orb);
}

// ---------- header, copy buttons, tabs, version ----------
const top = $('.top');
const onScroll = () => top.classList.toggle('scrolled', window.scrollY > 8);
addEventListener('scroll', onScroll, { passive: true });
onScroll();

for (const line of document.querySelectorAll('.install-line')) {
  const btn = $('.copy-btn', line);
  btn.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(line.dataset.copy); } catch { return; }
    btn.classList.add('copied');
    btn.replaceChildren(icon('check'));
    btn.setAttribute('aria-label', 'Copied');
    setTimeout(() => { btn.classList.remove('copied'); btn.replaceChildren(icon('copy')); btn.setAttribute('aria-label', 'Copy the install command'); }, 1400);
  });
}

for (const list of document.querySelectorAll('[role="tablist"]')) {
  const tabs = [...list.querySelectorAll('[role="tab"]')];
  const select = (tab) => {
    for (const t of tabs) {
      const on = t === tab;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    }
    tab.focus();
  };
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => select(t));
    t.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight') select(tabs[(i + 1) % tabs.length]);
      if (e.key === 'ArrowLeft') select(tabs[(i - 1 + tabs.length) % tabs.length]);
    });
  });
}

fetch('version.json').then((r) => (r.ok ? r.json() : null)).then((v) => {
  if (!v?.version) return;
  const el = $('#version');
  el.textContent = `v${v.version}`;
  el.hidden = false;
  $('#foot-version').textContent = `v${v.version}`;
}).catch(() => {});


// ---------- the intro screen: one real chat, three moments of the same task ----------
{
  const intro = $('.intro');
  const coreOrb = liveOrbs['core-orb'];
  const show = (state) => {
    for (const img of document.querySelectorAll('#hero-shot img')) img.classList.toggle('on', img.dataset.state === state);
  };
  // new chat -> the agent worked and waits for a decision -> approved, done
  const timeline = [
    [0, () => { show('new'); coreOrb.setLive(false); }],
    [2400, () => coreOrb.setLive(true)],
    [4200, () => show('approval')],
    [9600, () => { show('done'); coreOrb.setLive(false); }],
  ];
  const LOOP_AT = 15000;
  let timers = [];
  let paused = false;
  const clear = () => { timers.forEach(clearTimeout); timers = []; };
  function play() {
    clear();
    for (const [at, fn] of timeline) timers.push(setTimeout(fn, at));
    timers.push(setTimeout(play, LOOP_AT));
  }
  function still() { clear(); show('approval'); coreOrb.setLive(false); }
  const start = () => (reduceMotion.matches ? still() : play());
  start();
  reduceMotion.addEventListener('change', start);
  $('#hero-shot').addEventListener('click', () => {
    if (reduceMotion.matches) return;
    paused = !paused;
    intro.classList.toggle('paused', paused);
    if (paused) clear(); else play();
  });
  document.addEventListener('visibilitychange', () => {
    if (paused || reduceMotion.matches) return;
    if (document.hidden) clear(); else play();
  });
}

// ---------- diagrams: orthogonal lanes between real boxes, one label and one arrow per direction, a signal per step ----------
const SVG_NS = 'http://www.w3.org/2000/svg';
const COLORS = { violet: '#a47bff', amber: '#f2b867', blue: '#96aaff', magenta: '#d66cf0', pink: '#ff86c4', green: '#5ad49a' };
const svgEl = (tag, attrs = {}) => {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};

// a polyline with rounded corners, as the references draw their connectors
function rounded(points, r = 16) {
  const pts = points.filter((p, i) => i === 0 || Math.hypot(p.x - points[i - 1].x, p.y - points[i - 1].y) > 0.5);
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [a, p, b] = [pts[i - 1], pts[i], pts[i + 1]];
    const d0 = Math.hypot(p.x - a.x, p.y - a.y);
    const d1 = Math.hypot(b.x - p.x, b.y - p.y);
    const rr = Math.min(r, d0 / 2, d1 / 2);
    const s = { x: p.x - ((p.x - a.x) / d0) * rr, y: p.y - ((p.y - a.y) / d0) * rr };
    const e = { x: p.x + ((b.x - p.x) / d1) * rr, y: p.y + ((b.y - p.y) / d1) * rr };
    d += ` L ${s.x} ${s.y} Q ${p.x} ${p.y} ${e.x} ${e.y}`;
  }
  const last = pts[pts.length - 1];
  return `${d} L ${last.x} ${last.y}`;
}

function travel(stage, path, { label, color, reverse = false, dur = 1150 }, alive) {
  if (reduceMotion.matches) return Promise.resolve();
  return new Promise((resolve) => {
    const el = h('div', { class: 'dg-packet', style: `--c:${color}` }, h('span', { class: 'dg-dot' }), label ? h('span', { class: 'dg-tag' }, label) : null);
    stage.append(el);
    const t0 = performance.now();
    const frame = (now) => {
      if (!alive()) { el.remove(); resolve(); return; }
      const t = Math.min(1, (now - t0) / dur);
      const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
      const len = path.getTotalLength();
      const p = path.getPointAtLength(len * (reverse ? 1 - e : e));
      el.style.transform = `translate(${p.x}px, ${p.y}px)`;
      if (t < 1) { requestAnimationFrame(frame); return; }
      el.classList.add('out');
      setTimeout(() => { el.remove(); resolve(); }, 180);
    };
    requestAnimationFrame(frame);
  });
}

// geometry(g, narrow) returns { lanes: {id: {pts, color, label, t}}, branches: {id: {pts, off}}, routes: {id: {pts, color}}, rings, hub }
function makeDiagram(root, { geometry, steps }) {
  const stage = $('.dg-stage', root);
  const svg = $('.dg-lines', stage);
  const buttons = [...root.querySelectorAll('.dg-step')];
  const caption = $('.dg-caption', root);
  const playBtn = $('.dg-play', root);
  const narrow = matchMedia('(max-width: 860px)');
  const node = (id) => stage.querySelector(`[data-node="${id}"]`);
  const g = {
    rect(target) {
      const el = typeof target === 'string' ? stage.querySelector(target) : target;
      const s = stage.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      const x = r.left - s.left;
      const y = r.top - s.top;
      return { x, y, w: r.width, h: r.height, r: x + r.width, b: y + r.height, cx: x + r.width / 2, cy: y + r.height / 2 };
    },
    tile(id) { const n = node(id); return g.rect(n.querySelector('.dg-tile') || n); },
  };
  const defs = svgEl('defs');
  for (const [name, color] of Object.entries(COLORS)) {
    const m = svgEl('marker', { id: `${root.id}-${name}`, viewBox: '0 0 10 10', refX: '8', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse', markerUnits: 'userSpaceOnUse' });
    m.append(svgEl('path', { d: 'M 1 1.5 L 8.5 5 L 1 8.5 z', fill: color }));
    defs.append(m);
  }
  const ringsG = svgEl('g');
  const branchG = svgEl('g');
  const laneG = svgEl('g');
  const routeG = svgEl('g');
  svg.append(defs, ringsG, branchG, laneG, routeG);
  const els = { lanes: {}, ends: {}, chips: {}, branches: {}, routes: {} };
  let geo = null;

  function layout() {
    const s = stage.getBoundingClientRect();
    svg.setAttribute('width', s.width);
    svg.setAttribute('height', s.height);
    geo = geometry(g, narrow.matches);
    ringsG.replaceChildren(...(geo.rings ? geo.rings.r.map((r) => svgEl('circle', { class: 'dg-ring', cx: geo.rings.cx, cy: geo.rings.cy, r })) : []));
    for (const [id, b] of Object.entries(geo.branches || {})) {
      const el = els.branches[id] ||= branchG.appendChild(svgEl('path', { class: 'dg-branch' }));
      el.setAttribute('d', rounded(b.pts, 20));
      el.classList.toggle('off', !!b.off);
    }
    for (const [id, l] of Object.entries(geo.lanes)) {
      const name = l.color;
      const el = els.lanes[id] ||= laneG.appendChild(svgEl('path', { class: 'dg-lane', 'marker-end': `url(#${root.id}-${name})` }));
      el.style.setProperty('--c', COLORS[name]);
      el.setAttribute('d', rounded(l.pts, 14));
      const end = els.ends[id] ||= laneG.appendChild(svgEl('circle', { class: 'dg-end', r: '3.5' }));
      end.style.setProperty('--c', COLORS[name]);
      end.setAttribute('cx', l.pts[0].x);
      end.setAttribute('cy', l.pts[0].y);
      if (l.label) {
        const chip = els.chips[id] ||= stage.appendChild(h('span', { class: 'dg-chip', style: `--c:${COLORS[name]}` }, l.label));
        const len = el.getTotalLength();
        const p = el.getPointAtLength(len * (l.t ?? 0.5));
        chip.style.transform = `translate(${p.x}px, ${p.y}px) translate(-50%, -50%)`;
      }
    }
    for (const [id, r] of Object.entries(geo.routes || {})) {
      const el = els.routes[id] ||= routeG.appendChild(svgEl('path', { class: 'dg-route' }));
      el.setAttribute('d', rounded(r.pts, 18));
    }
  }
  new ResizeObserver(layout).observe(stage);
  document.fonts?.ready.then(layout);
  narrow.addEventListener('change', layout);
  layout();

  let current = 0;
  let token = 0;
  let timer = 0;
  let visible = false;
  let auto = !reduceMotion.matches;
  const stop = () => { token += 1; clearTimeout(timer); stage.querySelectorAll('.dg-packet, .dg-ripple').forEach((p) => p.remove()); };
  const syncPlay = () => { playBtn.setAttribute('aria-label', auto ? 'Pause' : 'Play'); playBtn.replaceChildren(icon(auto ? 'pause' : 'play')); };

  async function go(i) {
    stop();
    const my = token;
    const alive = () => my === token;
    current = i;
    buttons.forEach((b, k) => (k === i ? b.setAttribute('aria-current', 'step') : b.removeAttribute('aria-current')));
    caption.textContent = buttons[i].dataset.caption;
    layout();
    stage.classList.add('is-live');
    const c = {
      alive,
      node,
      wait: (ms) => (reduceMotion.matches ? Promise.resolve() : new Promise((r) => setTimeout(r, ms))),
      // light: lanes to keep bright, nodes and branches to colour, by lane colour name
      light({ lanes = [], nodes = {}, branches = {} } = {}) {
        for (const [id, el] of Object.entries(els.lanes)) {
          const on = lanes.includes(id);
          el.classList.toggle('dim', !on);
          els.ends[id].classList.toggle('dim', !on);
          els.chips[id]?.classList.toggle('dim', !on);
        }
        stage.querySelectorAll('.dg-node.is-active').forEach((n) => n.classList.remove('is-active'));
        for (const [id, color] of Object.entries(nodes)) { const n = node(id); n.classList.add('is-active'); n.style.setProperty('--c', COLORS[color]); }
        for (const [id, el] of Object.entries(els.branches)) {
          const color = branches[id];
          el.classList.toggle('on', !!color);
          if (color) el.style.setProperty('--c', COLORS[color]);
        }
      },
      lane(id) { return els.lanes[id]; },
      async send(id, label, { reverse = false, dur, color } = {}) {
        const path = els.routes[id] || els.lanes[id];
        const name = color || geo.routes?.[id]?.color || geo.lanes[id]?.color;
        await travel(stage, path, { label, color: COLORS[name], reverse, dur }, alive);
      },
      ripple(color) {
        if (reduceMotion.matches || !geo.hub) return;
        const hb = geo.hub;
        const el = h('span', { class: 'dg-ripple', style: `--c:${COLORS[color]}; left:${hb.x}px; top:${hb.y}px; width:${hb.w}px; height:${hb.h}px; border-radius:${hb.radius}px` });
        stage.append(el);
        setTimeout(() => el.remove(), 900);
      },
    };
    await steps[i](c);
    if (!alive()) return;
    if (auto && visible && !document.hidden) timer = setTimeout(() => go((i + 1) % steps.length), i === steps.length - 1 ? 3800 : 2600);
  }

  buttons.forEach((b, k) => b.addEventListener('click', () => { auto = false; syncPlay(); go(k); }));
  playBtn.addEventListener('click', () => { auto = !auto; syncPlay(); if (auto) go((current + 1) % steps.length); else stop(); });
  new IntersectionObserver(([e]) => {
    const was = visible;
    visible = e.isIntersecting;
    if (visible && !was) go(current);
    if (!visible && was && auto) stop();
  }, { threshold: 0.35 }).observe(stage);
  document.addEventListener('visibilitychange', () => {
    if (!auto || !visible) return;
    if (document.hidden) stop(); else go(current);
  });
  reduceMotion.addEventListener('change', () => { auto = !reduceMotion.matches; syncPlay(); go(current); });
  syncPlay();
}

// lanes leaving a box on one side towards a group, split into two directions, then a branch to every member
function sideLinks(g, hub, side, ids, { out, back, L = 14 }) {
  const lanes = {};
  const branches = {};
  const routes = {};
  const tiles = ids.map((id) => g.tile(id));
  if (side === 'left' || side === 'right') {
    const dir = side === 'right' ? 1 : -1;
    const x0 = dir > 0 ? hub.r : hub.x;
    const edge = dir > 0 ? Math.min(...tiles.map((t) => t.x)) : Math.max(...tiles.map((t) => t.r));
    const jx = x0 + (edge - x0) * 0.62;
    lanes[out.id] = { pts: [{ x: x0, y: hub.cy - L }, { x: jx, y: hub.cy - L }], color: out.color, label: out.label, t: 0.5 };
    lanes[back.id] = { pts: [{ x: jx, y: hub.cy + L }, { x: x0 + dir * 4, y: hub.cy + L }], color: back.color, label: back.label, t: 0.5 };
    ids.forEach((id, i) => {
      const t = tiles[i];
      const tx = dir > 0 ? t.x : t.r;
      branches[`b-${id}`] = { pts: [{ x: jx, y: hub.cy }, { x: jx, y: t.cy }, { x: tx, y: t.cy }] };
      routes[`${out.id}-${id}`] = { pts: [{ x: x0, y: hub.cy - L }, { x: jx, y: hub.cy - L }, { x: jx, y: t.cy }, { x: tx, y: t.cy }], color: out.color };
      routes[`${back.id}-${id}`] = { pts: [{ x: tx, y: t.cy }, { x: jx, y: t.cy }, { x: jx, y: hub.cy + L }, { x: x0, y: hub.cy + L }], color: back.color };
    });
  } else {
    const y0 = hub.b;
    const edge = Math.min(...tiles.map((t) => t.y));
    const jy = y0 + (edge - y0) * 0.55;
    lanes[out.id] = { pts: [{ x: hub.cx - L, y: y0 }, { x: hub.cx - L, y: jy }], color: out.color, label: out.label, t: 0.5 };
    lanes[back.id] = { pts: [{ x: hub.cx + L, y: jy }, { x: hub.cx + L, y: y0 + 4 }], color: back.color, label: back.label, t: 0.5 };
    ids.forEach((id, i) => {
      const t = tiles[i];
      branches[`b-${id}`] = { pts: [{ x: hub.cx, y: jy }, { x: t.cx, y: jy }, { x: t.cx, y: t.y }] };
      routes[`${out.id}-${id}`] = { pts: [{ x: hub.cx - L, y: y0 }, { x: hub.cx - L, y: jy }, { x: t.cx, y: jy }, { x: t.cx, y: t.y }], color: out.color };
      routes[`${back.id}-${id}`] = { pts: [{ x: t.cx, y: t.y }, { x: t.cx, y: jy }, { x: hub.cx + L, y: jy }, { x: hub.cx + L, y: y0 }], color: back.color };
    });
  }
  return { lanes, branches, routes };
}

// how it works: one task from the browser to a machine and back
{
  const root = $('#dg-system');
  const orb = liveOrbs['sys-orb'];
  const parts = (...on) => root.querySelectorAll('[data-part]').forEach((p) => p.classList.toggle('on', on.includes(p.dataset.part)));
  const machines = ['atlas', 'studio', 'forge', 'pi'];
  const models = ['claude', 'codex', 'ollama', 'openai'];
  makeDiagram(root, {
    geometry(g, narrow) {
      const hub = g.rect('.sys-hub');
      const core = g.rect('.sys-core');
      const br = g.tile('browser');
      const tg = g.tile('telegram');
      const my = hub.y - (hub.y - Math.max(br.b, tg.b)) * 0.5;
      const lanes = {
        task: { pts: [{ x: br.cx, y: br.b }, { x: br.cx, y: my }, { x: hub.cx - 30, y: my }, { x: hub.cx - 30, y: hub.y - 3 }], color: 'violet', label: 'task', t: 0.3 },
        approve: { pts: [{ x: tg.cx, y: tg.b }, { x: tg.cx, y: my }, { x: hub.cx + 30, y: my }, { x: hub.cx + 30, y: hub.y - 3 }], color: 'amber', label: 'approve', t: 0.3 },
      };
      const model = sideLinks(g, hub, 'right', models, { out: { id: 'context', color: 'blue', label: 'context' }, back: { id: 'toolcall', color: 'magenta', label: 'tool_call' } });
      const dev = sideLinks(g, narrow ? core : hub, narrow ? 'bottom' : 'left', machines, { out: { id: 'signed', color: 'pink', label: 'signed request' }, back: { id: 'result', color: 'green', label: 'result' } });
      dev.branches['b-pi'].off = true;
      return {
        lanes: { ...lanes, ...model.lanes, ...dev.lanes },
        branches: { ...model.branches, ...dev.branches },
        routes: { ...model.routes, ...dev.routes },
        rings: { cx: hub.cx, cy: hub.cy, r: [hub.w * 0.82, hub.w * 1.3, hub.w * 1.9] },
        hub: { ...hub, radius: narrow ? 28 : 34 },
      };
    },
    steps: [
      async (c) => {
        orb.setLive(false); parts();
        c.light({ lanes: ['task'], nodes: { browser: 'violet' } });
        await c.send('task', 'task');
        c.ripple('violet');
      },
      async (c) => {
        orb.setLive(true); parts('memory');
        c.light({ lanes: ['context', 'toolcall'], nodes: { claude: 'blue' }, branches: { 'b-claude': 'blue' } });
        await c.send('context-claude', 'task + context');
        await c.wait(350);
        await c.send('toolcall-claude', 'tool_call');
        c.ripple('magenta');
      },
      async (c) => {
        orb.setLive(true); parts('policy', 'approvals');
        c.light({ lanes: ['approve'], nodes: { telegram: 'amber' } });
        await c.wait(400);
        await c.send('approve', 'Run once?', { reverse: true });
        await c.wait(700);
        await c.send('approve', 'approved');
        c.ripple('amber');
      },
      async (c) => {
        orb.setLive(true); parts('signing');
        c.light({ lanes: ['signed'], nodes: { forge: 'pink' }, branches: { 'b-forge': 'pink' } });
        await c.send('signed-forge', 'signed request', { dur: 1400 });
        await c.wait(600);
      },
      async (c) => {
        orb.setLive(true); parts('log');
        c.light({ lanes: ['result', 'task'], nodes: { forge: 'green', browser: 'violet' }, branches: { 'b-forge': 'green' } });
        await c.send('result-forge', 'result');
        c.ripple('green');
        await c.send('task', 'answer', { reverse: true });
        orb.setLive(false);
      },
    ],
  });
}

// projects: the laptop sleeps, Core keeps working, results come back as branches
{
  const root = $('#dg-projects');
  const orb = liveOrbs['pj-orb'];
  const laptop = $('[data-node="laptop"]', root);
  const chats = [...root.querySelectorAll('.pj-chat')];
  const branches = [...root.querySelectorAll('.pj-branch')];
  const arrivals = $('.pj-arrivals', root);
  const note = $('.pj-note', root);
  const statePill = $('.pj-state', root);
  const badgeDot = $('.pj-head .device-badge .dot', root);
  const lanes = () => root.querySelectorAll('.dg-lane, .dg-end');
  const commitText = (n) => (n === 1 ? '1 commit' : `${n} commits`);
  function set({ online = true, shown = 0, commits = [0, 0, 0], arrived = 0, done = false }) {
    laptop.classList.toggle('off', !online);
    statePill.className = `pill pj-state${online ? ' ok' : ''}`;
    statePill.firstElementChild.className = `dot${online ? ' ok' : ''}`;
    $('.pj-state-text', root).textContent = online ? 'Online' : 'Offline';
    badgeDot.className = `dot${online ? ' ok' : ''}`;
    lanes().forEach((l) => l.classList.toggle('off', !online));
    chats.forEach((ch, i) => {
      ch.classList.toggle('show', i < shown);
      const finished = done && i < arrived;
      ch.querySelector('.dot').className = `dot ${finished ? 'ok' : 'accent'}${!finished && i < shown && !done ? ' live' : ''}`;
      const el = ch.querySelector('.pj-commits');
      const text = commitText(commits[i]);
      if (el.textContent !== text) {
        el.textContent = text;
        el.classList.add('bump');
        setTimeout(() => el.classList.remove('bump'), 500);
      }
    });
    $('.pj-chats', root).classList.toggle('has', shown > 0);
    branches.forEach((b, i) => b.classList.toggle('show', i < arrived));
    arrivals.classList.toggle('has', arrived > 0);
    note.classList.toggle('show', done && arrived === branches.length);
  }
  makeDiagram(root, {
    geometry(g, narrow) {
      const a = g.rect('[data-node="laptop"]');
      const b = g.rect('.pj-core');
      const L = 15;
      if (narrow) {
        const x = a.cx;
        return {
          lanes: {
            snapshot: { pts: [{ x: x - L, y: a.b }, { x: x - L, y: b.y - 3 }], color: 'blue', label: 'snapshot' },
            results: { pts: [{ x: x + L, y: b.y }, { x: x + L, y: a.b + 3 }], color: 'green', label: 'branches' },
          },
        };
      }
      const y = a.y + Math.min(a.h, b.h) * 0.42;
      return {
        lanes: {
          snapshot: { pts: [{ x: a.r, y: y - L }, { x: b.x - 3, y: y - L }], color: 'blue', label: 'snapshot' },
          results: { pts: [{ x: b.x, y: y + L }, { x: a.r + 3, y: y + L }], color: 'green', label: 'branches' },
        },
        rings: { cx: b.cx, cy: b.cy, r: [b.w * 0.62, b.w * 0.95] },
      };
    },
    steps: [
      async (c) => {
        orb.setLive(false);
        set({});
        c.light({ lanes: ['snapshot'], nodes: {} });
        await c.send('snapshot', 'snapshot');
      },
      async (c) => {
        orb.setLive(true);
        c.light({ lanes: [] });
        set({ shown: 0 });
        for (let i = 1; i <= 3; i++) { await c.wait(320); if (!c.alive()) return; set({ shown: i, commits: [i > 1 ? 1 : 0, 0, 0] }); }
        await c.wait(500);
        set({ shown: 3, commits: [1, 1, 0] });
      },
      async (c) => {
        orb.setLive(true);
        c.light({ lanes: [] });
        set({ online: false, shown: 3, commits: [1, 1, 0] });
        const ticks = [[2, 1, 1], [2, 2, 1], [3, 2, 2], [3, 3, 2]];
        for (const t of ticks) { await c.wait(600); if (!c.alive()) return; set({ online: false, shown: 3, commits: t }); }
      },
      async (c) => {
        orb.setLive(true);
        const commits = [3, 3, 2];
        set({ online: true, shown: 3, commits });
        c.light({ lanes: ['results'] });
        await c.wait(400);
        for (let i = 0; i < 3; i++) {
          await c.send('results', 'branch', { dur: 900 });
          if (!c.alive()) return;
          set({ online: true, shown: 3, commits, arrived: i + 1, done: true });
        }
        orb.setLive(false);
      },
    ],
  });
}
