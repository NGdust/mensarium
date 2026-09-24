// Memory graph: force-directed layout on a canvas, in the spirit of Obsidian's graph view.
// Drag nodes, pan the background, zoom with the wheel or a pinch; hover highlights a node's neighbourhood.

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
export const graphColor = (kind) => KIND_COLORS[kind] || KIND_COLORS.note;

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');

export function createGraph(canvas, { onSelect } = {}) {
  const ctx = canvas.getContext('2d');
  let nodes = [];
  let links = [];
  let byId = new Map();
  let neighbours = new Map();
  let view = { k: 1, x: 0, y: 0 };
  let alpha = 0;
  let raf = 0;
  let hover = null;
  let selected = null;
  let fitted = false;
  let width = 0;
  let height = 0;
  const dpr = () => Math.min(window.devicePixelRatio || 1, 2);

  function resize() {
    const r = canvas.getBoundingClientRect();
    width = r.width;
    height = r.height;
    canvas.width = Math.round(width * dpr());
    canvas.height = Math.round(height * dpr());
    draw();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);

  function setData(data) {
    const old = byId;
    nodes = data.nodes.map((n) => {
      const prev = old.get(n.id);
      const angle = Math.random() * Math.PI * 2;
      const dist = 40 + Math.random() * 160;
      return { ...n, x: prev?.x ?? Math.cos(angle) * dist, y: prev?.y ?? Math.sin(angle) * dist, vx: 0, vy: 0, fixed: false };
    });
    byId = new Map(nodes.map((n) => [n.id, n]));
    links = data.links.filter((l) => byId.has(l.source) && byId.has(l.target)).map((l) => ({ source: byId.get(l.source), target: byId.get(l.target) }));
    neighbours = new Map(nodes.map((n) => [n.id, new Set()]));
    for (const l of links) {
      neighbours.get(l.source.id).add(l.target.id);
      neighbours.get(l.target.id).add(l.source.id);
    }
    for (const n of nodes) n.r = n.kind === 'tag' ? 3.5 : 4 + Math.sqrt(neighbours.get(n.id).size) * 2.4 + (n.weight || 0) * 0.3;
    if (selected && !byId.has(selected.id)) selected = null;
    else if (selected) selected = byId.get(selected.id);
    fitted = fitted && old.size > 0;
    reheat(1);
    if (reduceMotion.matches) { for (let i = 0; i < 300; i++) tick(); alpha = 0; fit(); draw(); }
  }

  function tick() {
    const n = nodes.length;
    const repulse = 900;
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
        if (d2 > 250000) continue;
        const f = (repulse * alpha) / d2;
        const d = Math.sqrt(d2);
        a.vx += (dx / d) * f; a.vy += (dy / d) * f;
        b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      }
    }
    for (const l of links) {
      const dx = l.target.x - l.source.x;
      const dy = l.target.y - l.source.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 70) * 0.04 * alpha;
      l.source.vx += (dx / d) * f; l.source.vy += (dy / d) * f;
      l.target.vx -= (dx / d) * f; l.target.vy -= (dy / d) * f;
    }
    for (const p of nodes) {
      p.vx -= p.x * 0.004 * alpha;
      p.vy -= p.y * 0.004 * alpha;
      if (p.fixed) { p.vx = 0; p.vy = 0; continue; }
      p.vx *= 0.6; p.vy *= 0.6;
      p.x += p.vx; p.y += p.vy;
    }
    alpha *= 0.985;
  }

  function reheat(value = 0.3) {
    alpha = Math.max(alpha, value);
    if (!raf && !reduceMotion.matches) raf = requestAnimationFrame(loop);
  }

  function loop() {
    raf = 0;
    if (alpha > 0.01) {
      tick(); tick();
      if (!fitted && alpha < 0.35) { fit(); fitted = true; }
      raf = requestAnimationFrame(loop);
    }
    draw();
  }

  function fit() {
    if (!nodes.length || !width) return;
    let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
    for (const p of nodes) { minX = Math.min(minX, p.x); minY = Math.min(minY, p.y); maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y); }
    const k = Math.min(2, Math.max(0.25, Math.min(width / (maxX - minX + 120), height / (maxY - minY + 120))));
    view = { k, x: width / 2 - ((minX + maxX) / 2) * k, y: height / 2 - ((minY + maxY) / 2) * k };
  }

  const toWorld = (sx, sy) => [(sx - view.x) / view.k, (sy - view.y) / view.k];

  function nodeAt(sx, sy) {
    const [wx, wy] = toWorld(sx, sy);
    let best = null;
    let bestD = Infinity;
    for (const p of nodes) {
      const d = Math.hypot(p.x - wx, p.y - wy);
      if (d < Math.max(p.r + 4, 10 / view.k) && d < bestD) { best = p; bestD = d; }
    }
    return best;
  }

  function draw() {
    const s = dpr();
    ctx.setTransform(s, 0, 0, s, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.setTransform(s * view.k, 0, 0, s * view.k, s * view.x, s * view.y);
    const focus = hover || selected;
    const near = focus ? neighbours.get(focus.id) : null;
    const lit = (p) => !focus || p === focus || near.has(p.id);

    ctx.lineWidth = 1 / view.k;
    for (const l of links) {
      const on = focus && (l.source === focus || l.target === focus);
      ctx.strokeStyle = on ? 'rgba(187, 156, 255, 0.85)' : focus ? 'rgba(255, 255, 255, 0.04)' : 'rgba(255, 255, 255, 0.13)';
      ctx.beginPath();
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
      ctx.stroke();
    }
    for (const p of nodes) {
      const color = graphColor(p.ghost ? 'ghost' : p.kind);
      ctx.globalAlpha = lit(p) ? 1 : 0.18;
      if (p === selected || p === hover) {
        ctx.fillStyle = color;
        ctx.globalAlpha *= 0.22;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r + 6, 0, Math.PI * 2); ctx.fill();
        ctx.globalAlpha = 1;
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      if (p.ghost) {
        ctx.strokeStyle = color; ctx.lineWidth = 1.2 / view.k; ctx.stroke();
      } else {
        ctx.fillStyle = color; ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const fontSize = 12 / view.k;
    ctx.font = `${fontSize}px Onest, system-ui, sans-serif`;
    for (const p of nodes) {
      const important = p.r * view.k > 9 || view.k > 1.6;
      if (!(p === focus || (near && near.has(p.id)) || (!focus && important))) continue;
      ctx.fillStyle = lit(p) ? (p === focus ? '#f3f1f7' : 'rgba(203, 198, 214, 0.9)') : 'rgba(203, 198, 214, 0.2)';
      const label = p.label.length > 34 ? `${p.label.slice(0, 33)}…` : p.label;
      ctx.fillText(label, p.x, p.y + p.r + 4 / view.k);
    }
  }

  // ---- pointer interaction ----
  const pointers = new Map();
  let drag = null;
  let pinch = null;

  const local = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };

  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    const [sx, sy] = local(e);
    pointers.set(e.pointerId, [sx, sy]);
    if (pointers.size === 2) {
      const [[ax, ay], [bx, by]] = [...pointers.values()];
      pinch = { d: Math.hypot(ax - bx, ay - by), k: view.k, cx: (ax + bx) / 2, cy: (ay + by) / 2, x: view.x, y: view.y };
      if (drag?.node) drag.node.fixed = false;
      drag = null;
      return;
    }
    const node = nodeAt(sx, sy);
    drag = { node, sx, sy, vx: view.x, vy: view.y, moved: false };
    if (node) { node.fixed = true; reheat(0.25); }
  });

  canvas.addEventListener('pointermove', (e) => {
    const [sx, sy] = local(e);
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, [sx, sy]);
    if (pinch && pointers.size === 2) {
      const [[ax, ay], [bx, by]] = [...pointers.values()];
      const k = Math.min(4, Math.max(0.15, pinch.k * (Math.hypot(ax - bx, ay - by) / pinch.d)));
      view = { k, x: pinch.cx - ((pinch.cx - pinch.x) / pinch.k) * k, y: pinch.cy - ((pinch.cy - pinch.y) / pinch.k) * k };
      draw();
      return;
    }
    if (drag) {
      if (Math.hypot(sx - drag.sx, sy - drag.sy) > 4) drag.moved = true;
      if (drag.node) {
        const [wx, wy] = toWorld(sx, sy);
        drag.node.x = wx; drag.node.y = wy;
        reheat(0.2);
      } else {
        view.x = drag.vx + sx - drag.sx;
        view.y = drag.vy + sy - drag.sy;
      }
      draw();
      return;
    }
    const node = nodeAt(sx, sy);
    if (node !== hover) {
      hover = node;
      canvas.style.cursor = node ? 'pointer' : 'grab';
      draw();
    }
  });

  const release = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!drag) return;
    if (drag.node) drag.node.fixed = false;
    if (!drag.moved) {
      selected = drag.node;
      draw();
      onSelect?.(drag.node);
    }
    drag = null;
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.addEventListener('pointerleave', () => { if (!drag && hover) { hover = null; draw(); } });

  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const [sx, sy] = local(e);
    const k = Math.min(4, Math.max(0.15, view.k * Math.exp(-e.deltaY * 0.0015)));
    view = { k, x: sx - ((sx - view.x) / view.k) * k, y: sy - ((sy - view.y) / view.k) * k };
    draw();
  }, { passive: false });

  return {
    setData,
    select(id) {
      selected = byId.get(id) || null;
      if (selected && width) {
        // leave room for the preview panel that opens on the right of wide screens
        const cx = width > 760 ? (width - 360) / 2 : width / 2;
        const cy = width > 760 ? height / 2 : height * 0.3;
        view = { ...view, x: cx - selected.x * view.k, y: cy - selected.y * view.k };
      }
      draw();
    },
    fit() { fit(); draw(); },
    zoom(factor) {
      const k = Math.min(4, Math.max(0.15, view.k * factor));
      view = { k, x: width / 2 - ((width / 2 - view.x) / view.k) * k, y: height / 2 - ((height / 2 - view.y) / view.k) * k };
      draw();
    },
    destroy() { ro.disconnect(); cancelAnimationFrame(raf); raf = 0; },
  };
}
