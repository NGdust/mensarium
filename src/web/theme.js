// Colour theme: a palette family and a mode. Mensarium is the product's own look and lives in styles.css; every other
// family (the built-in ones follow OpenClaw's palettes, plus one imported from tweakcn) is nine base colours per mode
// that paint() spreads over the same tokens. The painted CSS is cached, and index.html puts it on the page together
// with data-theme before the first paint. Switching reloads the page, the way the language does, so the two canvas
// faces (orb.js, graph.js) can read their palette once at load instead of watching for it.

export const MODES = ['auto', 'light', 'dark'];

// [panel, surface, text, text-2, muted, accent, accent-2, button, button text]
export const PALETTES = {
  mensarium: { name: 'Mensarium', dark: ['#0e0b10', '#16141c', '#f3f1f7', '#cbc6d6', '#8f8a9b', '#a47bff', '#ff86c4'], light: ['#ffffff', '#ffffff', '#17141f', '#433d52', '#6d6780', '#7445f0', '#cf3b80'] },
  claw: { name: 'Claw', dark: ['#0e1015', '#161920', '#f4f4f5', '#bcbcc0', '#8b8b94', '#ff5c5c', '#14b8a6', '#d13c3c', '#ffffff'], light: ['#faf9f7', '#ffffff', '#211e1a', '#403c35', '#6e6960', '#bd4531', '#0d9488', '#bd4531', '#ffffff'] },
  knot: { name: 'Knot', dark: ['#080808', '#111113', '#f5f5f7', '#c6c6cb', '#8a8a94', '#e5243b', '#b8bdc4', '#d92a3f', '#fafafa'], light: ['#f9f9fb', '#ffffff', '#18181b', '#3a3a42', '#68676f', '#c41e30', '#5a626e', '#c41e30', '#ffffff'] },
  dash: { name: 'Dash', dark: ['#1a1210', '#221a16', '#f0e4da', '#d8c8b8', '#a18f80', '#cf8b4d', '#dcb878', '#cf8b4d', '#1a1210'], light: ['#f7f2ec', '#fffcf8', '#2c2118', '#4a3828', '#725d4d', '#8a512c', '#7d6027', '#8a512c', '#ffffff'] },
  absolutely: { name: 'Absolutely', dark: ['#1c1c1a', '#232320', '#f5f1e8', '#e4dfd4', '#aba498', '#d97757', '#b8926a', '#d97757', '#241f1b'], light: ['#faf9f5', '#ffffff', '#1f1d1a', '#3d3a33', '#6b655b', '#a8452a', '#8a6a44', '#a8452a', '#ffffff'] },
  tide: { name: 'Tide', dark: ['#10151b', '#161d25', '#f2f6fa', '#c9d2da', '#9dabb9', '#5ab6d8', '#7f9bb5', '#5ab6d8', '#0b1116'], light: ['#f7f9fb', '#ffffff', '#1b232b', '#333c45', '#5f6b76', '#1f6f8f', '#3d6d88', '#1f6f8f', '#ffffff'] },
  beacon: { name: 'Beacon', dark: ['#000000', '#0a0a0a', '#ffffff', '#ebebeb', '#c9c9c9', '#ffc233', '#8ecdff', '#ffc233', '#000000'], light: ['#ffffff', '#ffffff', '#000000', '#1a1a1a', '#3a3a3a', '#6e4a00', '#09428d', '#6e4a00', '#ffffff'] },
  phosphor: { name: 'Phosphor', dark: ['#0a0f0a', '#0e150e', '#e8f5e9', '#cfe0cf', '#93ac95', '#4ade80', '#8fd6a5', '#4ade80', '#07120a'], light: ['#f4f7f4', '#ffffff', '#16201a', '#2a352b', '#566b58', '#10693a', '#2f6b47', '#10693a', '#ffffff'] },
  crt: { name: 'CRT', dark: ['#090a09', '#0e0e0e', '#ececec', '#c6c6c6', '#999999', '#e8e8e8', '#ffcf5c', '#e8e8e8', '#111111'], light: ['#f5f5f4', '#ffffff', '#1b1b1b', '#373737', '#5f5f5f', '#1f1f1f', '#7a5d10', '#1f1f1f', '#ffffff'] },
  manuscript: { name: 'Manuscript', dark: ['#211e18', '#2a271f', '#efe8d6', '#d8d0bc', '#ab9f84', '#8fa8e0', '#cfa85e', '#8fa8e0', '#101c33'], light: ['#f6f1e4', '#fdfbf3', '#1d1a12', '#322d22', '#6a604e', '#31549b', '#7d6118', '#31549b', '#ffffff'] },
  rose: { name: 'Rosé', dark: ['#191724', '#1f1d2e', '#efedfa', '#d5d2eb', '#9793b0', '#ebbcba', '#f6c177', '#ebbcba', '#3f2224'], light: ['#faf4ed', '#fffaf3', '#292339', '#3e3857', '#665d87', '#9c4f66', '#286983', '#9c4f66', '#ffffff'] },
  miami: { name: 'Miami', dark: ['#140f1e', '#1c1530', '#efeaf9', '#cfc7e8', '#968bbd', '#f472b6', '#5fd7e8', '#f472b6', '#3c0a24'], light: ['#f7f3f6', '#fefcfe', '#241c2b', '#3c3244', '#6b5f74', '#b0246f', '#0f6f7d', '#b0246f', '#ffffff'] },
};

function load(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function save(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* storage unavailable */ }
}

const HEX = /^#[0-9a-f]{6}$/;
const validPalette = (p) => Array.isArray(p) && p.length === 9 && p.every((c) => HEX.test(c));

function loadCustom() {
  try {
    const c = JSON.parse(load('theme-custom'));
    return c && typeof c.name === 'string' && validPalette(c.dark) && validPalette(c.light) ? c : null;
  } catch { return null; }
}

// modeChoice is what the owner picked, theme is what is on screen once "auto" is resolved.
export const modeChoice = MODES.includes(load('theme')) ? load('theme') : 'dark';
export const theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
export const custom = loadCustom();
export const paletteChoice = load('palette') === 'custom' ? (custom ? 'custom' : 'mensarium') : PALETTES[load('palette')] ? load('palette') : 'mensarium';

const paletteOf = (id) => (id === 'custom' ? loadCustom() : PALETTES[id]);

// The three dots on a theme's card: accent, second accent and ground, in the mode on screen.
export function swatches(id) {
  const p = paletteOf(id)?.[theme] || [];
  return [p[5], p[6], p[0]];
}

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const mix = (a, b, t) => a.map((c, i) => Math.round(c + (b[i] - c) * t));
const toHex = (c) => `#${c.map((x) => x.toString(16).padStart(2, '0')).join('')}`;
const alpha = (c, a) => `rgba(${c.join(', ')}, ${a})`;

function paint(palette, dark) {
  const [panel, surface, text, text2, muted, accent, accent2, btn, btnFg] = palette.map(rgb);
  const k = dark ? 1 : 0.55;
  const frame = dark ? mix(panel, [0, 0, 0], 0.45) : mix(panel, text, 0.06);
  const orb = [accent2, mix(accent2, accent, 0.5), accent, mix(accent, text, 0.3)];
  return {
    frame: toHex(frame),
    panel: toHex(panel),
    surface: toHex(surface),
    'surface-2': toHex(mix(surface, text, 0.05)),
    'surface-3': toHex(mix(surface, text, 0.1)),
    ink: text.join(', '),
    card: mix(panel, text, 0.045).join(', '),
    'card-hi': mix(panel, text, 0.08).join(', '),
    veil: panel.join(', '),
    text: toHex(text),
    'text-2': toHex(text2),
    muted: toHex(muted),
    faint: toHex(mix(muted, panel, 0.3)),
    accent: toHex(accent),
    'accent-strong': toHex(mix(accent, text, 0.25)),
    'accent-soft': alpha(accent, 0.13),
    'accent-line': alpha(accent, 0.45),
    'accent-btn': toHex(btn),
    'accent-btn-hover': toHex(mix(btn, text, 0.12)),
    'accent-fg': toHex(btnFg),
    select: alpha(accent, 0.3),
    'select-fg': toHex(text),
    'haze-panel': `radial-gradient(90% 70% at 60% -18%, ${alpha(accent, 0.12 * k)}, ${alpha(accent, 0.035 * k)} 50%, transparent 80%)`,
    'haze-stage': `radial-gradient(55% 55% at 50% 52%, ${alpha(accent, 0.11 * k)}, ${alpha(accent, 0.02 * k)} 55%, transparent 80%)`,
    'haze-login': `radial-gradient(60% 55% at 50% -8%, ${alpha(accent, 0.12 * k)}, ${alpha(accent, 0.03 * k)} 50%, transparent 80%)`,
    'hub-fill': `linear-gradient(180deg, ${toHex(mix(surface, text, 0.03))}, ${toHex(surface)})`,
    'cross-near': alpha(accent, 0.7),
    ...Object.fromEntries(orb.map((c, i) => [`orb-${i + 1}`, `rgb(${c.join(', ')})`])),
  };
}

function css(id) {
  const p = id === 'mensarium' ? null : paletteOf(id);
  if (!p) return '';
  const block = (mode) => `:root[data-theme="${mode}"]{${Object.entries(paint(p[mode], mode === 'dark')).map(([k, v]) => `--${k}:${v};`).join('')}}`;
  return block('dark') + block('light');
}

// A release may retune a palette: repaint what index.html applied from the cache when it no longer matches.
const painted = css(paletteChoice);
if (painted !== (load('theme-css') || '')) {
  save('theme-css', painted || null);
  let style = document.getElementById('palette');
  if (!style && painted) style = document.head.appendChild(Object.assign(document.createElement('style'), { id: 'palette' }));
  if (style) style.textContent = painted;
}
document.querySelector('meta[name="theme-color"]')?.setAttribute('content', getComputedStyle(document.documentElement).getPropertyValue('--frame').trim());

export function setMode(value) {
  if (!MODES.includes(value)) return;
  save('theme', value);
  location.reload();
}

export function setPalette(id) {
  if (!paletteOf(id)) return;
  save('palette', id);
  save('theme-css', css(id) || null);
  location.reload();
}

export function removeCustom() {
  save('theme-custom', null);
  if (paletteChoice === 'custom') setPalette('mensarium');
  else location.reload();
}

// ---- tweakcn import ----
// A tweakcn theme is a shadcn registry item: cssVars.light and cssVars.dark in any CSS colour syntax. Each colour
// goes through a canvas and comes out as #rrggbb, so nothing but colours from the payload ever reaches the page.

const THEME_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const TWEAKCN_HOSTS = ['tweakcn.com', 'www.tweakcn.com'];

function tweakcnId(input) {
  const value = String(input || '').trim().replace(/[.,;:]+$/, '');
  if (!value) throw new Error('Paste a tweakcn theme link or ID.');
  if (THEME_ID.test(value)) return value;
  let url;
  try { url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`); } catch { throw new Error('This is not a tweakcn theme link.'); }
  if (!TWEAKCN_HOSTS.includes(url.hostname)) throw new Error('Only tweakcn.com theme links are supported.');
  const parts = url.pathname.split('/').filter(Boolean);
  const id = (parts[0] === 'themes' && parts.length === 2) || (parts[0] === 'r' && parts[1] === 'themes' && parts.length === 3)
    ? parts.at(-1).replace(/\.json$/, '')
    : url.searchParams.get('theme') || url.searchParams.get('id');
  if (!id || !THEME_ID.test(id)) throw new Error('This is not a tweakcn theme link.');
  return id;
}

let ctx = null;

function colorHex(value) {
  if (typeof value !== 'string' || value.length > 120) return null;
  let v = value.trim();
  if (/^[\d.]+\s+[\d.]+%\s+[\d.]+%$/.test(v)) v = `hsl(${v})`;
  ctx ||= Object.assign(document.createElement('canvas'), { width: 1, height: 1 }).getContext('2d', { willReadFrequently: true });
  for (const probe of ['#000001', '#000002']) {
    ctx.fillStyle = probe;
    ctx.fillStyle = v;
    if (ctx.fillStyle === probe) return null;
  }
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillRect(0, 0, 1, 1);
  return toHex([...ctx.getImageData(0, 0, 1, 1).data.slice(0, 3)]);
}

function fromShadcn(vars) {
  const c = (key) => colorHex(vars?.[key]);
  const text = c('foreground');
  const muted = c('muted-foreground');
  const primary = c('primary');
  const palette = [
    c('background'), c('card') || c('background'), text, text && muted ? toHex(mix(rgb(text), rgb(muted), 0.3)) : text, muted,
    primary, c('chart-2') || c('accent') || primary, primary, c('primary-foreground'),
  ];
  return validPalette(palette) ? palette : null;
}

export async function importTweakcn(input) {
  const id = tweakcnId(input);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  let data;
  try {
    const res = await fetch(`https://tweakcn.com/r/themes/${encodeURIComponent(id)}`, { headers: { accept: 'application/json' }, signal: controller.signal });
    if (res.status === 404) throw new Error('tweakcn has no theme with this link.');
    if (!res.ok) throw new Error('tweakcn did not return the theme, try again later.');
    data = await res.json();
  } catch (err) {
    if (err instanceof SyntaxError || controller.signal.aborted || err instanceof TypeError) throw new Error('tweakcn did not return the theme, try again later.');
    throw err;
  } finally { clearTimeout(timer); }
  const vars = data?.cssVars || {};
  const dark = fromShadcn(vars.dark || vars.light);
  const light = fromShadcn(vars.light || vars.dark);
  if (!dark || !light) throw new Error('The theme has no colours this interface can use.');
  const name = String(data.title || data.name || id).slice(0, 60);
  save('theme-custom', JSON.stringify({ id, name, dark, light }));
  setPalette('custom');
}
