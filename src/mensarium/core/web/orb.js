// The agent's face: a particle sphere whose surface ripples and breathes. One shared animation loop.

const STOPS = [
  [150, 170, 255],
  [164, 123, 255],
  [214, 108, 240],
  [255, 134, 196],
];
const BUCKETS = 24;
const ALPHAS = 8;
// Particles are batched by (color band, alpha step) so each frame issues ~200 fills instead of thousands.
const STYLES = Array.from({ length: BUCKETS }, (_, i) => {
  const t = (i / (BUCKETS - 1)) * (STOPS.length - 1);
  const k = Math.min(Math.floor(t), STOPS.length - 2);
  const f = t - k;
  const rgb = STOPS[k].map((c, j) => Math.round(c + (STOPS[k + 1][j] - c) * f)).join(',');
  return Array.from({ length: ALPHAS }, (_, a) => `rgba(${rgb},${((a + 1) / ALPHAS).toFixed(3)})`);
});

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const animated = new Set();
let frame = 0;

// Only orbs that are actually on screen are redrawn; with none visible the loop stops.
const observer = new IntersectionObserver((entries) => {
  for (const entry of entries) if (entry.target.orb) entry.target.orb.visible = entry.isIntersecting;
  kick();
});
reduceMotion.addEventListener('change', kick);

function kick() {
  if (frame || reduceMotion.matches) return;
  for (const orb of animated) if (orb.visible) { frame = requestAnimationFrame(loop); return; }
}

function points(count) {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const pts = new Float32Array(count * 5);
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const a = golden * i;
    const stray = Math.random() < 0.07;
    pts.set([Math.cos(a) * r, y, Math.sin(a) * r, stray ? 1.08 + Math.random() * 0.22 : 1, Math.random() * Math.PI * 2], i * 5);
  }
  return pts;
}

function draw(orb, time) {
  const { ctx, pts, px, dot, live, small } = orb;
  const t = time / 1000;
  const energy = orb.energy += ((live ? 1 : 0) - orb.energy) * 0.05;
  const amp = small ? 0.025 + 0.02 * energy : 0.085 + 0.1 * energy;
  const front = small ? 0.5 : 0.26;
  const pulse = 1 + (0.025 + 0.03 * energy) * Math.sin(t * (1.1 + 1.6 * energy));
  const rot = t * (0.18 + 0.25 * energy);
  const cr = Math.cos(rot);
  const sr = Math.sin(rot);
  const tilt = 0.35;
  const ct = Math.cos(tilt);
  const st = Math.sin(tilt);
  const radius = px * 0.36 * pulse;
  const c = px / 2;
  const n = pts.length / 5;

  const batches = orb.batches;
  for (const b of batches) b.length = 0;
  for (let i = 0; i < n; i++) {
    const o = i * 5;
    const bx = pts[o];
    const by = pts[o + 1];
    const bz = pts[o + 2];
    const wave = Math.sin(bx * 3.4 + t * 1.3) * Math.sin(by * 3.1 - t * 0.9) * Math.sin(bz * 3.6 + t * 0.7)
      + 0.45 * Math.sin(bx * 7.1 - by * 5.3 + bz * 2.2 + t * 1.9)
      + 0.2 * Math.sin(pts[o + 4] * 3 + t * 2.4);
    const r = pts[o + 3] * (1 + amp * wave) + (pts[o + 3] > 1 ? 0.04 * Math.sin(t * 2 + pts[o + 4]) : 0);
    const x1 = bx * cr + bz * sr;
    const z1 = -bx * sr + bz * cr;
    const y2 = by * ct - z1 * st;
    const z2 = by * st + z1 * ct;
    const rim = 1 - Math.abs(z2);
    if (small && pts[o + 3] > 1) continue;
    const alpha = (z2 > 0 ? front : 0.1) + 0.74 * rim * rim * (pts[o + 3] > 1 ? 0.6 : 1);
    if (alpha < 0.08) continue;
    const band = Math.max(0, Math.min(BUCKETS - 1, Math.round(((1 - y2) / 2) * (BUCKETS - 1))));
    const step = Math.min(ALPHAS - 1, Math.floor(alpha * ALPHAS));
    batches[band * ALPHAS + step].push(c + x1 * radius * r, c - y2 * radius * r, dot * (0.7 + 0.6 * rim));
  }

  ctx.clearRect(0, 0, px, px);
  ctx.globalCompositeOperation = 'lighter';
  for (let k = 0; k < batches.length; k++) {
    const b = batches[k];
    if (!b.length) continue;
    ctx.fillStyle = STYLES[Math.floor(k / ALPHAS)][k % ALPHAS];
    ctx.beginPath();
    for (let j = 0; j < b.length; j += 3) ctx.rect(b[j] - b[j + 2] / 2, b[j + 1] - b[j + 2] / 2, b[j + 2], b[j + 2]);
    ctx.fill();
  }
}

function loop(time) {
  frame = 0;
  if (reduceMotion.matches) return;
  let running = false;
  for (const orb of animated) {
    if (!orb.canvas.isConnected) { animated.delete(orb); observer.unobserve(orb.canvas); continue; }
    if (!orb.visible) continue;
    draw(orb, time);
    running = true;
  }
  if (running) frame = requestAnimationFrame(loop);
}

// size: CSS pixels. animate=false renders a single still frame (used for every message in a long thread).
export function createOrb(size, { animate = true, live = false, className = '' } = {}) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const px = Math.round(size * dpr);
  const canvas = document.createElement('canvas');
  canvas.width = px;
  canvas.height = px;
  canvas.className = `orb ${className}`.trim();
  canvas.style.setProperty('--s', `${size}px`);
  canvas.setAttribute('aria-hidden', 'true');
  const count = size >= 120 ? 4200 : size >= 48 ? 1500 : 420;
  const orb = {
    canvas, px, live, energy: live ? 1 : 0, small: size < 48, visible: false,
    ctx: canvas.getContext('2d'),
    pts: points(count),
    batches: Array.from({ length: BUCKETS * ALPHAS }, () => []),
    dot: Math.max(1, (size >= 48 ? 1.1 : 0.9) * dpr),
  };
  draw(orb, performance.now());
  if (animate) {
    canvas.orb = orb;
    animated.add(orb);
    observer.observe(canvas);
  }
  canvas.setLive = (value) => { orb.live = value; };
  return canvas;
}
