// Colour theme. Dark is the product's own look and the default; light repaints the same tokens for a bright room,
// and "auto" follows the system. index.html applies data-theme before the first paint, so there is no flash while
// this module loads; here we only report the choice and change it. Switching reloads the page, the way the language
// does, so the two canvas faces (orb.js, graph.js) can read their palette once at load instead of watching for it.

export const THEMES = ['dark', 'light', 'auto'];

function stored() {
  try { return localStorage.getItem('theme'); } catch { return null; }
}

// themeChoice is what the owner picked, theme is what is on screen once "auto" is resolved.
export const themeChoice = THEMES.includes(stored()) ? stored() : 'dark';
export const theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';

export function setTheme(value) {
  if (!THEMES.includes(value)) return;
  try { localStorage.setItem('theme', value); } catch { /* storage unavailable */ }
  location.reload();
}
