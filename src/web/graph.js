// Memory map: the central note in the middle and every other note on rings by how many links away it is,
// drawn like the product's diagrams: a lit hub, tiles on a dotted field, lines in the colour of a note's type.
// Drag the background to pan, zoom with the wheel or a pinch; picking a note lights its path to the centre.

import { createOrb } from './orb.js';

const KIND_COLORS = {
  fact: '#a47bff',
  preference: '#ff86c4',
  project: '#96aaff',
  person: '#f2b867',
  device: '#5ad49a',
  howto: '#d66cf0',
  note: '#cbc6d6',
  tag: '#6fd3c9',
  ghost: '#6c6778',
};
const KIND_ICONS = { fact: 'book', preference: 'sliders', project: 'folder', person: 'user', device: 'laptop', howto: 'list', note: 'file' };
const KIND_ORDER = ['person', 'preference', 'project', 'device', 'howto', 'fact', 'note'];
export const graphColor = (kind) => KIND_COLORS[kind] || KIND_COLORS.note;
export const kindIcon = (kind) => KIND_ICONS[kind] || 'file';

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const SVG_NS = 'http://www.w3.org/2000/svg';
const HUB_R = 150;
const TILE_R = 23;

const el = (tag, cls) => { const e = document.createElement(tag); if (cls) e.className = cls; return e; };
const svgEl = (tag, attrs = {}) => {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};
const polar = (r, a) => ({ x: r * Math.cos(a), y: r * Math.sin(a) });

// A radial tree: breadth-first from the centre over links in both directions; a note nothing leads to is hung
// on the centre with a dashed line. Every leaf gets the same slice of the circle, first-ring notes are grouped by type.
export function layoutMemory(nodes, links, centerId) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const adj = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const l of links) {
    if (l.source !== l.target && adj.has(l.source) && adj.has(l.target)) { adj.get(l.source).add(l.target); adj.get(l.target).add(l.source); }
  }
  const weight = (id) => (byId.get(id).pinned ? 50 : 0) + (byId.get(id).weight || 0) + adj.get(id).size;
  const kindRank = (id) => { const i = KIND_ORDER.indexOf(byId.get(id).kind); return i < 0 ? KIND_ORDER.length : i; };
  const depth = new Map([[centerId, 0]]);
  const parent = new Map();
  const children = new Map(nodes.map((n) => [n.id, []]));
  const implicit = new Set();
  const order = [centerId];
  for (let i = 0; i < order.length; i++) {
    const cur = order[i];
    const next = [...adj.get(cur)].filter((x) => !depth.has(x));
    next.sort((a, b) => (cur === centerId ? kindRank(a) - kindRank(b) : 0) || weight(b) - weight(a));
    for (const x of next) { depth.set(x, depth.get(cur) + 1); parent.set(x, cur); children.get(cur).push(x); order.push(x); }
    if (i === order.length - 1) {
      const rest = nodes.map((n) => n.id).filter((x) => !depth.has(x)).sort((a, b) => weight(b) - weight(a));
      if (rest.length) {
        const root = rest[0];
        depth.set(root, 1); parent.set(root, centerId); implicit.add(root); order.push(root);
        const siblings = children.get(centerId);
        const at = siblings.findIndex((s) => kindRank(s) > kindRank(root));
        siblings.splice(at < 0 ? siblings.length : at, 0, root);
      }
    }
  }
  const leaves = new Map();
  for (let i = order.length - 1; i >= 0; i--) {
    const id = order[i];
    const kids = children.get(id);
    leaves.set(id, kids.length ? kids.reduce((s, k) => s + leaves.get(k), 0) : 1);
  }
  const perDepth = [];
  for (const [id, d] of depth) if (id !== centerId) perDepth[d] = (perDepth[d] || 0) + 1;
  const rings = [0];
  for (let d = 1; d < perDepth.length; d++) rings[d] = Math.max(d === 1 ? 310 : rings[d - 1] + 170, (perDepth[d] * 112) / (2 * Math.PI));
  const pos = new Map([[centerId, { x: 0, y: 0, a: 0, r: 0, depth: 0 }]]);
  const span = new Map([[centerId, [-Math.PI / 2, (3 * Math.PI) / 2]]]);
  for (const id of order) {
    const [a0, a1] = span.get(id);
    let a = a0;
    for (const k of children.get(id)) {
      const share = ((a1 - a0) * leaves.get(k)) / leaves.get(id);
      span.set(k, [a, a + share]);
      const mid = a + share / 2;
      pos.set(k, { ...polar(rings[depth.get(k)], mid), a: mid, r: rings[depth.get(k)], depth: depth.get(k) });
      a += share;
    }
  }
  const tree = [...parent].map(([to, from]) => ({ from, to, implicit: implicit.has(to) }));
  const treeKey = new Set(tree.map((e) => [e.from, e.to].sort().join('|')));
  const cross = [];
  const seen = new Set();
  for (const l of links) {
    const key = [l.source, l.target].sort().join('|');
    if (l.source === l.target || treeKey.has(key) || seen.has(key) || !pos.has(l.source) || !pos.has(l.target)) continue;
    seen.add(key);
    cross.push({ a: l.source, b: l.target });
  }
  return { pos, tree, cross, rings, parent, adj };
}

export function createMemoryMap(stage, { icon, onSelect, onFile, centerTitle, countText }) {
  const world = el('div', 'mm-world');
  const svg = svgEl('svg', { class: 'mm-lines', width: '1', height: '1' });
  const ringsG = svgEl('g');
  const crossG = svgEl('g');
  const treeG = svgEl('g');
  svg.append(ringsG, crossG, treeG);
  world.append(svg);
  stage.append(world);
  let view = { k: 1, x: 0, y: 0 };
  let nodes = [];
  let layout = null;
  let centerId = null;
  let byId = new Map();
  let nodeEls = new Map();
  let edges = [];
  let selected = null;
  let hovered = null;
  let token = 0;
  let moved = false;
  let files = [];
  let hubBox = { hw: HUB_R, hh: HUB_R };

  const apply = () => {
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.k})`;
    stage.classList.toggle('mm-far', view.k < 0.6);
  };
  const size = () => { const r = stage.getBoundingClientRect(); return { w: r.width, h: r.height }; };

  function edgePath(from, to) {
    const a = layout.pos.get(from);
    const b = layout.pos.get(to);
    const ang = from === centerId ? b.a : Math.atan2(b.y - a.y, b.x - a.x);
    // from the centre a line leaves the card at its edge, whatever the card's shape
    const edge = Math.min(hubBox.hw / Math.max(Math.abs(Math.cos(ang)), 1e-6), hubBox.hh / Math.max(Math.abs(Math.sin(ang)), 1e-6)) + 4;
    const start = from === centerId ? polar(edge, b.a) : { x: a.x + Math.cos(ang) * TILE_R, y: a.y + Math.sin(ang) * TILE_R };
    const end = { x: b.x - Math.cos(ang) * TILE_R, y: b.y - Math.sin(ang) * TILE_R };
    if (from === centerId) return `M ${start.x} ${start.y} L ${end.x} ${end.y}`;
    const rm = (a.r + b.r) / 2;
    const c1 = polar(rm, a.a);
    const c2 = polar(rm, b.a);
    return `M ${start.x} ${start.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${end.x} ${end.y}`;
  }
  function crossPath(x, y) {
    const a = layout.pos.get(x);
    const b = layout.pos.get(y);
    const m = { x: ((a.x + b.x) / 2) * 0.72, y: ((a.y + b.y) / 2) * 0.72 };
    return `M ${a.x} ${a.y} Q ${m.x} ${m.y} ${b.x} ${b.y}`;
  }

  function nodeEl(n) {
    const p = layout.pos.get(n.id);
    const b = el('button', `mm-node${n.ghost ? ' ghost' : ''}${n.pinned ? ' pinned' : ''}`);
    b.type = 'button';
    b.style.left = `${p.x}px`;
    b.style.top = `${p.y}px`;
    b.style.setProperty('--c', graphColor(n.ghost ? 'ghost' : n.kind));
    b.setAttribute('aria-label', n.label);
    const tile = el('span', 'mm-tile');
    tile.append(icon(kindIcon(n.kind)));
    const label = el('span', 'mm-label');
    label.textContent = n.label;
    b.append(tile, label);
    b.addEventListener('click', () => { select(n.id); onSelect?.(n); });
    b.addEventListener('mouseenter', () => { hovered = n.id; light(); });
    b.addEventListener('mouseleave', () => { if (hovered === n.id) { hovered = null; light(); } });
    return b;
  }

  // the centre holds the central note and the instruction files the agent reads before every chat
  function hubEl(n) {
    const hub = el('div', 'mm-hub hub-edge');
    const head = el('button', 'mm-hub-head');
    head.type = 'button';
    head.append(createOrb(56, { animate: true, className: 'md' }));
    const title = el('span', 'mm-hub-title');
    title.textContent = n ? n.label : centerTitle;
    const sub = el('span', 'mm-hub-sub');
    sub.textContent = countText(nodes.filter((x) => !x.ghost && x.id !== centerId).length);
    head.append(title, sub);
    head.setAttribute('aria-label', title.textContent);
    if (n && !n.virtual) head.addEventListener('click', () => { select(n.id); onSelect?.(n); });
    hub.append(head);
    if (files.length) {
      const grid = el('div', 'mm-files');
      for (const f of files) {
        const b = el('button', `mm-file${f.custom ? ' custom' : ''}${f.over ? ' over' : ''}`);
        b.type = 'button';
        b.title = f.desc;
        b.append(icon('file'));
        const name = el('span', 'mm-file-name');
        name.textContent = f.name.replace(/\.md$/, '');
        const dot = el('span', 'mm-file-dot');
        b.append(name, dot);
        b.addEventListener('click', () => { select(null); onFile?.(f.name); });
        grid.append(b);
      }
      hub.append(grid);
    }
    return hub;
  }

  function render() {
    world.querySelectorAll('.mm-node, .mm-hub, .mm-packet').forEach((x) => x.remove());
    ringsG.replaceChildren(...[...layout.rings.slice(1), (layout.rings.at(-1) || 0) + 165, (layout.rings.at(-1) || 0) + 330]
      .filter((r) => r > 0).map((r, i, all) => svgEl('circle', { class: i >= all.length - 2 ? 'mm-ring faint' : 'mm-ring', cx: 0, cy: 0, r })));
    if (layout.rings.length < 2) ringsG.replaceChildren(...[310, 480].map((r) => svgEl('circle', { class: 'mm-ring faint', cx: 0, cy: 0, r })));
    const hub = hubEl(byId.get(centerId));
    world.append(hub);
    hubBox = { hw: hub.offsetWidth / 2 || HUB_R, hh: hub.offsetHeight / 2 || HUB_R };
    crossG.replaceChildren();
    treeG.replaceChildren();
    edges = [];
    for (const e of layout.tree) {
      const n = byId.get(e.to);
      const path = svgEl('path', { class: `mm-edge${e.implicit ? ' implicit' : ''}`, d: edgePath(e.from, e.to) });
      path.style.setProperty('--c', graphColor(n.ghost ? 'ghost' : n.kind));
      treeG.append(path);
      edges.push({ ...e, path, tree: true });
    }
    for (const e of layout.cross) {
      const path = svgEl('path', { class: 'mm-cross', d: crossPath(e.a, e.b) });
      crossG.append(path);
      edges.push({ from: e.a, to: e.b, path, tree: false });
    }
    nodeEls = new Map();
    for (const n of nodes) {
      if (n.id === centerId) continue;
      const b = nodeEl(n);
      world.append(b);
      nodeEls.set(n.id, b);
    }
    nodeEls.set(centerId, hub);
    light();
  }

  const chain = (id) => {
    const out = [];
    for (let cur = id; cur && cur !== centerId; cur = layout.parent.get(cur)) out.unshift(cur);
    return out;
  };

  // one note in focus: its neighbours and its path to the centre stay lit, everything else steps back
  function light() {
    const focus = hovered || selected;
    stage.classList.toggle('mm-focus', !!focus && focus !== centerId);
    const lit = new Set();
    const path = new Set();
    if (focus && focus !== centerId) {
      lit.add(focus);
      for (const x of layout.adj.get(focus) || []) lit.add(x);
      const c = chain(focus);
      c.forEach((x) => { lit.add(x); path.add(x); });
      lit.add(centerId);
    }
    for (const [id, b] of nodeEls) {
      b.classList.toggle('lit', lit.has(id));
      b.classList.toggle('sel', id === selected);
    }
    for (const e of edges) {
      const on = e.tree ? path.has(e.to) : false;
      const near = focus && (e.from === focus || e.to === focus);
      e.path.classList.toggle('on', on || (e.tree && near));
      e.path.classList.toggle('near', !e.tree && !!near);
    }
  }

  // a signal runs from the centre along the lit path, the way requests travel in the diagrams
  async function send(id) {
    const my = ++token;
    world.querySelectorAll('.mm-packet').forEach((x) => x.remove());
    if (reduceMotion.matches) return;
    const color = graphColor(byId.get(id)?.kind);
    for (const step of chain(id)) {
      const e = edges.find((x) => x.tree && x.to === step);
      if (!e) return;
      const dot = el('span', 'mm-packet');
      dot.style.setProperty('--c', color);
      world.append(dot);
      const len = e.path.getTotalLength();
      const dur = Math.min(900, 380 + len * 1.1);
      await new Promise((resolve) => {
        const t0 = performance.now();
        const frame = (now) => {
          if (my !== token) { dot.remove(); resolve(); return; }
          const t = Math.min(1, (now - t0) / dur);
          const q = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
          const p = e.path.getPointAtLength(len * q);
          dot.style.transform = `translate(${p.x}px, ${p.y}px)`;
          if (t < 1) requestAnimationFrame(frame); else { dot.remove(); resolve(); }
        };
        requestAnimationFrame(frame);
      });
      if (my !== token) return;
    }
    nodeEls.get(id)?.classList.add('arrived');
    setTimeout(() => nodeEls.get(id)?.classList.remove('arrived'), 700);
  }

  function select(id, { pan = false } = {}) {
    selected = id && byId.has(id) ? id : null;
    light();
    if (!selected) { token++; return; }
    if (pan) {
      const p = layout.pos.get(selected);
      const { w, h } = size();
      const sx = view.x + p.x * view.k;
      const sy = view.y + p.y * view.k;
      if (sx < 60 || sy < 60 || sx > w - 60 || sy > h - 60) {
        view = { ...view, x: (w > 760 ? (w - 360) / 2 : w / 2) - p.x * view.k, y: h / 2 - p.y * view.k };
        apply();
      }
    }
    send(selected);
  }

  // the first view frames the centre and the two nearest rings; "show all" is one button away
  function fit(all = false) {
    const { w, h } = size();
    if (!layout || !w) return;
    const rings = layout.rings.slice(1);
    const near = w < 600 ? rings[0] : rings[1] ?? rings[0];
    const outer = all ? Math.max(HUB_R + 60, ...[...layout.pos.values()].map((p) => p.r + 90)) : (near ?? HUB_R) + 90;
    const k = Math.max(0.3, Math.min(1.1, Math.min(w, h) / (outer * 2 + 20)));
    view = { k, x: w / 2, y: h / 2 };
    apply();
  }

  function zoom(factor, cx, cy) {
    moved = true;
    const { w, h } = size();
    const px = cx ?? w / 2;
    const py = cy ?? h / 2;
    const k = Math.min(2.4, Math.max(0.2, view.k * factor));
    view = { k, x: px - ((px - view.x) / view.k) * k, y: py - ((py - view.y) / view.k) * k };
    apply();
  }

  // ---- panning and zooming ----
  const pointers = new Map();
  let drag = null;
  let pinch = null;
  const local = (e) => { const r = stage.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  stage.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.mm-node, .mm-hub, .mm-ui')) return;
    stage.setPointerCapture(e.pointerId);
    const [x, y] = local(e);
    pointers.set(e.pointerId, [x, y]);
    if (pointers.size === 2) {
      const [[ax, ay], [bx, by]] = [...pointers.values()];
      pinch = { d: Math.hypot(ax - bx, ay - by), k: view.k, cx: (ax + bx) / 2, cy: (ay + by) / 2, x: view.x, y: view.y };
      drag = null;
      moved = true;
      return;
    }
    drag = { x, y, vx: view.x, vy: view.y };
    moved = true;
    stage.classList.add('mm-grabbing');
  });
  stage.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return;
    const [x, y] = local(e);
    pointers.set(e.pointerId, [x, y]);
    if (pinch && pointers.size === 2) {
      const [[ax, ay], [bx, by]] = [...pointers.values()];
      const k = Math.min(2.4, Math.max(0.2, pinch.k * (Math.hypot(ax - bx, ay - by) / pinch.d)));
      view = { k, x: pinch.cx - ((pinch.cx - pinch.x) / pinch.k) * k, y: pinch.cy - ((pinch.cy - pinch.y) / pinch.k) * k };
      apply();
      return;
    }
    if (drag) { view = { ...view, x: drag.vx + x - drag.x, y: drag.vy + y - drag.y }; apply(); }
  });
  const release = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) { drag = null; stage.classList.remove('mm-grabbing'); }
  };
  stage.addEventListener('pointerup', release);
  stage.addEventListener('pointercancel', release);
  stage.addEventListener('wheel', (e) => {
    if (e.target.closest('.mm-ui')) return;
    e.preventDefault();
    const [x, y] = local(e);
    zoom(Math.exp(-e.deltaY * 0.0015), x, y);
  }, { passive: false });
  // until the owner pans or zooms, the whole map follows the panel size
  const ro = new ResizeObserver(() => { if (!moved && layout) fit(); });
  ro.observe(stage);

  return {
    setData(data) {
      nodes = data.nodes.filter((n) => n.kind !== 'tag');
      centerId = data.center;
      if (!nodes.some((n) => n.id === centerId)) {
        centerId = 'center:none';
        nodes.push({ id: centerId, label: centerTitle, kind: 'person', weight: 0, virtual: true });
      }
      byId = new Map(nodes.map((n) => [n.id, n]));
      const links = data.links.filter((l) => byId.has(l.source) && byId.has(l.target));
      layout = layoutMemory(nodes, links, centerId);
      if (selected && !byId.has(selected)) selected = null;
      render();
      if (!moved) fit();
    },
    select,
    fit() { moved = false; fit(true); },
    setFiles(list) {
      files = list;
      if (layout) render();
    },
    zoom: (f) => zoom(f),
    isImplicit: (id) => !!layout?.tree.find((e) => e.to === id && e.implicit),
    destroy() { ro.disconnect(); token++; },
  };
}
