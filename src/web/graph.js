// Memory map: the central note in the middle, every other note in the sector of its topic around it, the important
// ones nearest the centre, drawn like the product's diagrams: a lit hub, tiles on a dotted field, the sector and its
// lines in the topic's colour, the tile's icon by the note's kind. Drag the background to pan, zoom with the wheel
// or a pinch; picking a note lights its links.

import { createOrb } from './orb.js';

// A note's type is its colour, on the tile, its line and its dot. Bright tones read on the black field; on paper
// the same hues have to be deeper, or mint and amber disappear. Fixed for the page's life: theme.js reloads on a switch.
const light = document.documentElement.dataset.theme === 'light';
const KIND_COLORS = light
  ? {
    fact: '#7445f0',
    preference: '#cf3b80',
    project: '#4560cf',
    person: '#a2701a',
    device: '#12855f',
    howto: '#a93bc9',
    note: '#6d6780',
    tag: '#127f78',
    ghost: '#938da4',
  }
  : {
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
// Topics get their colour by position in the topic list, so it holds until a topic is added or removed.
const TOPIC_COLORS = light
  ? ['#4560cf', '#a2701a', '#12855f', '#7445f0', '#cf3b80', '#127f78', '#a93bc9', '#b3541e']
  : ['#96aaff', '#f2b867', '#5ad49a', '#a47bff', '#ff86c4', '#6fd3c9', '#d66cf0', '#f0a06c'];
const KIND_ICONS = { fact: 'book', preference: 'sliders', project: 'folder', person: 'user', device: 'laptop', howto: 'list', task: 'check', topic: 'layers', note: 'file' };
export const NO_TOPIC = 'topic:none';
export const graphColor = (kind) => KIND_COLORS[kind] || KIND_COLORS.note;
export const topicColor = (i) => (i < 0 ? KIND_COLORS.ghost : TOPIC_COLORS[i % TOPIC_COLORS.length]);
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

const INNER = 260;
const STEP = 124;
const GAP = 124;
const SECTOR_GAP = 0.12;

// Areas: every topic gets a sector of the circle, wide in proportion to its notes; notes outside any topic share
// one grey sector. A sector is split into sections by the tag its notes share (the server picks one per note), and
// inside a section the notes follow their links: the most linked note nearest the centre, the notes that mention
// it on the rings behind it, so a chain of links reads outward. A ghost (a title that is linked to but has no note
// yet) sits in the sector of the note that mentions it. Topic notes themselves are not tiles: the sector is the topic.
export function layoutMemory(nodes, links, centerId, topics) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const adj = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const l of links) {
    if (l.source !== l.target && adj.has(l.source) && adj.has(l.target)) { adj.get(l.source).add(l.target); adj.get(l.target).add(l.source); }
  }
  const topicIds = new Set(topics.map((t) => t.id));
  const area = new Map();
  for (const n of nodes) if (n.id !== centerId && n.kind !== 'topic') area.set(n.id, topicIds.has(n.topic) ? n.topic : NO_TOPIC);
  // shortest path from the centre over links: the lit trail and the packet follow it
  const parent = new Map();
  const seen = new Set([centerId]);
  for (const queue = [centerId]; queue.length;) {
    const cur = queue.shift();
    for (const x of adj.get(cur)) if (!seen.has(x)) { seen.add(x); parent.set(x, cur); queue.push(x); }
  }
  const rank = (id) => (byId.get(id).pinned ? 50 : 0) + (byId.get(id).weight || 0) * 3 + adj.get(id).size;
  const kinds = [...topics.map((t) => t.id), NO_TOPIC].filter((k) => [...area.values()].includes(k));
  const groups = new Map(kinds.map((k) => [k, [...area].filter(([, a]) => a === k).map(([id]) => id)]));
  // depth-first over the links inside a section: a note comes right after the note it is linked to
  const chainOrder = (ids) => {
    const set = new Set(ids);
    const seen = new Set();
    const out = [];
    const inner = (id) => [...adj.get(id)].filter((x) => set.has(x));
    const visit = (id) => {
      if (seen.has(id)) return;
      seen.add(id);
      out.push(id);
      inner(id).sort((a, b) => rank(b) - rank(a)).forEach(visit);
    };
    [...ids].sort((a, b) => inner(b).length - inner(a).length || rank(b) - rank(a) || byId.get(a).label.localeCompare(byId.get(b).label)).forEach(visit);
    return out;
  };
  const free = 2 * Math.PI - kinds.length * SECTOR_GAP;
  const minAngle = (GAP * 1.15) / INNER;
  const weights = kinds.map((k) => 3 + groups.get(k).length);
  const total = weights.reduce((s, w) => s + w, 0);
  let angles = weights.map((w) => (w / total) * free);
  const small = angles.filter((a) => a < minAngle).length;
  if (small && small < kinds.length) {
    const left = free - small * minAngle;
    const big = angles.filter((a) => a >= minAngle).reduce((s, a) => s + a, 0);
    angles = angles.map((a) => (a < minAngle ? minAngle : (a / big) * left));
  }
  const pos = new Map([[centerId, { x: 0, y: 0, a: 0, r: 0 }]]);
  const sectors = [];
  let a0 = -Math.PI / 2 - angles[0] / 2;
  let ringCount = 0;
  kinds.forEach((kind, i) => {
    const ids = groups.get(kind);
    const angle = angles[i];
    // sections by tag, the untagged rest last; each takes a slice of the sector in proportion to its notes
    const tags = [...new Set(ids.map((id) => byId.get(id).group || ''))].sort((x, y) => (x === '') - (y === '') || x.localeCompare(y));
    const parts = tags.map((tag) => ({ tag, ids: chainOrder(ids.filter((id) => (byId.get(id).group || '') === tag)) }));
    const total = parts.reduce((s, p) => s + p.ids.length + 1, 0);
    let b0 = a0;
    let outerRing = 0;
    const sections = [];
    for (const p of parts) {
      const slice = (angle * (p.ids.length + 1)) / total;
      let ring = 0;
      for (let placed = 0; placed < p.ids.length; ring++) {
        const r = INNER + ring * STEP;
        const take = Math.min(p.ids.length - placed, Math.max(1, Math.floor((slice * r) / GAP)));
        const stepA = slice / take;
        for (let j = 0; j < take; j++) {
          const a = b0 + stepA * (j + 0.5);
          pos.set(p.ids[placed + j], { ...polar(r, a), a, r, ring });
        }
        placed += take;
      }
      outerRing = Math.max(outerRing, ring);
      sections.push({ tag: p.tag, a0: b0, a1: b0 + slice, outer: INNER + (ring - 1) * STEP });
      b0 += slice;
    }
    ringCount = Math.max(ringCount, outerRing);
    const topic = topics.find((t) => t.id === kind);
    sectors.push({ kind, topic, color: topicColor(topics.indexOf(topic)), a0, a1: a0 + angle, count: ids.filter((id) => !byId.get(id).ghost).length, outer: INNER + (outerRing - 1) * STEP, sections });
    a0 += angle + SECTOR_GAP;
  });
  const rings = Array.from({ length: ringCount + 1 }, (_, i) => INNER + i * STEP);
  const edges = [];
  const keys = new Set();
  for (const l of links) {
    const key = [l.source, l.target].sort().join('|');
    if (l.source === l.target || keys.has(key) || !pos.has(l.source) || !pos.has(l.target)) continue;
    keys.add(key);
    const toCenter = l.source === centerId || l.target === centerId;
    edges.push({ from: toCenter ? centerId : l.source, to: toCenter ? (l.source === centerId ? l.target : l.source) : l.target, tree: toCenter });
  }
  return { pos, sectors, rings, parent, adj, area, edges };
}

export function createMemoryMap(stage, { icon, onSelect, onFile, onArea, centerTitle, countText, noTopicLabel }) {
  const world = el('div', 'mm-world');
  const svg = svgEl('svg', { class: 'mm-lines', width: '1', height: '1' });
  const areasG = svgEl('g');
  const ringsG = svgEl('g');
  const crossG = svgEl('g');
  const treeG = svgEl('g');
  svg.append(areasG, ringsG, crossG, treeG);
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
  let only = { area: null, kind: null };
  let token = 0;
  let moved = false;
  let files = [];
  let hubBox = { hw: HUB_R, hh: HUB_R };

  const apply = () => {
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.k})`;
    stage.classList.toggle('mm-far', view.k < 0.75);
  };
  const size = () => { const r = stage.getBoundingClientRect(); return { w: r.width, h: r.height }; };

  // from the centre a line leaves the card at its edge, whatever the card's shape; between notes it bends towards the centre
  function edgePath(e) {
    const a = layout.pos.get(e.from);
    const b = layout.pos.get(e.to);
    if (e.tree) {
      const edge = Math.min(hubBox.hw / Math.max(Math.abs(Math.cos(b.a)), 1e-6), hubBox.hh / Math.max(Math.abs(Math.sin(b.a)), 1e-6)) + 4;
      const start = polar(edge, b.a);
      const end = polar(b.r - TILE_R, b.a);
      return `M ${start.x} ${start.y} L ${end.x} ${end.y}`;
    }
    const m = { x: ((a.x + b.x) / 2) * 0.72, y: ((a.y + b.y) / 2) * 0.72 };
    return `M ${a.x} ${a.y} Q ${m.x} ${m.y} ${b.x} ${b.y}`;
  }
  // a sector is a ring slice from just outside the hub to a little past its last ring
  function wedgePath(s) {
    const r0 = INNER - 90;
    const r1 = s.outer + STEP * 0.55;
    const big = s.a1 - s.a0 > Math.PI ? 1 : 0;
    const [p, q, u, v] = [polar(r1, s.a0), polar(r1, s.a1), polar(r0, s.a1), polar(r0, s.a0)];
    return `M ${p.x} ${p.y} A ${r1} ${r1} 0 ${big} 1 ${q.x} ${q.y} L ${u.x} ${u.y} A ${r0} ${r0} 0 ${big} 0 ${v.x} ${v.y} Z`;
  }
  // text along an arc; on the lower half the arc is drawn backwards so the text stays upright
  function arcText(id, r, a0, a1, cls, content) {
    const lower = Math.sin((a0 + a1) / 2) > 0;
    const p = polar(r, lower ? a1 : a0);
    const q = polar(r, lower ? a0 : a1);
    const big = a1 - a0 > Math.PI ? 1 : 0;
    const path = svgEl('path', { id, d: `M ${p.x} ${p.y} A ${r} ${r} 0 ${big} ${lower ? 0 : 1} ${q.x} ${q.y}`, fill: 'none' });
    const text = svgEl('text', { class: cls });
    const tp = svgEl('textPath', { href: `#${id}`, startOffset: '50%', 'text-anchor': 'middle' });
    tp.textContent = content;
    text.append(tp);
    return [path, text, lower];
  }
  // the sector's name runs along its inner edge, its sections along the outer rim with thin dividers between them
  function areaLabel(s) {
    const lower = Math.sin((s.a0 + s.a1) / 2) > 0;
    const [path, text] = arcText(`mm-arc-${s.kind}`, INNER - (lower ? 44 : 78), s.a0, s.a1, 'mm-area-label', `${s.topic ? s.topic.title : noTopicLabel} · ${s.count}`);
    text.style.setProperty('--c', s.color);
    text.addEventListener('click', () => onArea?.(s.kind, s.topic || null));
    const rim = s.outer + STEP * 0.55;
    const extras = s.sections.length > 1 ? s.sections.flatMap((sec, i) => {
      const out = [];
      if (sec.tag) {
        const low = Math.sin((sec.a0 + sec.a1) / 2) > 0;
        const [p, t] = arcText(`mm-sec-${s.kind}-${i}`, rim + (low ? 20 : 12), sec.a0, sec.a1, 'mm-section-label', sec.tag);
        t.style.setProperty('--c', s.color);
        out.push(p, t);
      }
      if (i) {
        const a = polar(INNER - 50, sec.a0);
        const b = polar(rim, sec.a0);
        const line = svgEl('path', { class: 'mm-divider', d: `M ${a.x} ${a.y} L ${b.x} ${b.y}` });
        line.style.setProperty('--c', s.color);
        out.push(line);
      }
      return out;
    }) : [];
    return [path, text, ...extras];
  }

  function nodeEl(n) {
    const p = layout.pos.get(n.id);
    const b = el('button', `mm-node${n.ghost ? ' ghost' : ''}${n.pinned ? ' pinned' : ''}${n.pinned || (n.weight || 0) >= 8 ? ' key' : ''}`);
    b.type = 'button';
    b.style.left = `${p.x}px`;
    b.style.top = `${p.y}px`;
    b.style.setProperty('--c', n.ghost ? graphColor('ghost') : sectorOf(n.id).color);
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

  const sectorOf = (id) => layout.sectors.find((s) => s.kind === layout.area.get(id)) || layout.sectors[0];

  function render() {
    world.querySelectorAll('.mm-node, .mm-hub, .mm-packet').forEach((x) => x.remove());
    areasG.replaceChildren(...layout.sectors.flatMap((s) => {
      const wedge = svgEl('path', { class: 'mm-wedge', d: wedgePath(s), 'data-area': s.kind });
      wedge.style.setProperty('--c', s.color);
      return [wedge, ...areaLabel(s)];
    }));
    ringsG.replaceChildren(...[...layout.rings, layout.rings.at(-1) + STEP].map((r, i, all) => svgEl('circle', { class: i === all.length - 1 ? 'mm-ring faint' : 'mm-ring', cx: 0, cy: 0, r })));
    const hub = hubEl(byId.get(centerId));
    world.append(hub);
    hubBox = { hw: hub.offsetWidth / 2 || HUB_R, hh: hub.offsetHeight / 2 || HUB_R };
    crossG.replaceChildren();
    treeG.replaceChildren();
    edges = [];
    for (const e of layout.edges) {
      const path = svgEl('path', { class: e.tree ? 'mm-edge' : 'mm-cross', d: edgePath(e) });
      if (e.tree) path.style.setProperty('--c', sectorOf(e.to).color);
      (e.tree ? treeG : crossG).append(path);
      edges.push({ ...e, path });
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
  const touches = (e, a, b) => (e.from === a && e.to === b) || (e.from === b && e.to === a);

  // one note in focus: its neighbours and its path to the centre stay lit, everything else steps back;
  // with one area or kind chosen, the rest fades
  const shown = (id) => id === centerId || ((!only.area || layout.area.get(id) === only.area) && (!only.kind || byId.get(id)?.kind === only.kind));
  function light() {
    const focus = hovered || selected;
    stage.classList.toggle('mm-focus', !!focus && focus !== centerId);
    stage.classList.toggle('mm-only', !!(only.area || only.kind));
    const lit = new Set();
    const trail = new Set();
    if (focus && focus !== centerId) {
      lit.add(focus);
      for (const x of layout.adj.get(focus) || []) lit.add(x);
      const c = chain(focus);
      if (layout.parent.has(focus)) c.forEach((x, i) => { lit.add(x); trail.add([c[i - 1] ?? centerId, x].sort().join('|')); });
      lit.add(centerId);
    }
    for (const [id, b] of nodeEls) {
      b.classList.toggle('lit', lit.has(id));
      b.classList.toggle('sel', id === selected);
      b.classList.toggle('in', shown(id));
    }
    for (const e of edges) {
      const near = !!focus && (e.from === focus || e.to === focus);
      e.path.classList.toggle('on', near || trail.has([e.from, e.to].sort().join('|')));
      e.path.classList.toggle('in', shown(e.from) && shown(e.to));
    }
    for (const w of areasG.querySelectorAll('.mm-wedge')) w.classList.toggle('in', !only.area || w.dataset.area === only.area);
  }

  // a signal runs from the centre along the lit path, the way requests travel in the diagrams
  async function send(id) {
    const my = ++token;
    world.querySelectorAll('.mm-packet').forEach((x) => x.remove());
    if (reduceMotion.matches || !layout.parent.has(id)) return;
    const color = sectorOf(id).color;
    let prev = centerId;
    for (const step of chain(id)) {
      const e = edges.find((x) => touches(x, prev, step));
      if (!e) return;
      const forward = e.from === prev;
      prev = step;
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
          const p = e.path.getPointAtLength(len * (forward ? q : 1 - q));
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

  // the whole map in view: the areas are the point, so nothing is cropped
  function fit() {
    const { w, h } = size();
    if (!layout || !w) return;
    const outer = Math.max(HUB_R + 60, ...[...layout.pos.values()].map((p) => p.r + 90));
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
      centerId = data.center;
      // topics are sectors, not tiles; the centre stays a tile-less card even if it is a topic
      nodes = data.nodes.filter((n) => n.kind !== 'tag' && (n.kind !== 'topic' || n.id === centerId));
      const topics = (data.topics || []).filter((t) => t.id !== centerId);
      if (!nodes.some((n) => n.id === centerId)) {
        centerId = 'center:none';
        nodes.push({ id: centerId, label: centerTitle, kind: 'person', weight: 0, virtual: true });
      }
      byId = new Map(nodes.map((n) => [n.id, n]));
      const links = data.links.filter((l) => byId.has(l.source) && byId.has(l.target));
      layout = layoutMemory(nodes, links, centerId, topics);
      if (selected && !byId.has(selected)) selected = null;
      if (only.area && !layout.sectors.some((s) => s.kind === only.area)) only = { ...only, area: null };
      render();
      if (!moved) fit();
    },
    select,
    fit() { moved = false; fit(); },
    setFiles(list) {
      files = list;
      if (layout) render();
    },
    setOnly(next) { only = { ...only, ...next }; if (layout) light(); },
    only: () => only,
    sectors: () => layout?.sectors || [],
    members: (area) => nodes.filter((n) => layout?.area.get(n.id) === (area || NO_TOPIC) && !n.ghost),
    color: (id) => (layout && layout.area.has(id) ? sectorOf(id).color : graphColor('note')),
    zoom: (f) => zoom(f),
    isDetached: (id) => !layout?.adj.get(id)?.size,
    destroy() { ro.disconnect(); token++; },
  };
}
