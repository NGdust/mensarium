#!/bin/bash
# Re-shoot every landing screenshot from a seeded stand: stand.py up && stand.py seed, then this script.
set -e
cd "$(dirname "$0")/../.."
STAND=${MENSARIUM_STAND:-/tmp/mensarium-stand}
OUT=${1:-$STAND/shots}
mkdir -p "$OUT"
P=".venv/bin/python landing/stand/cdp.py"
U=http://127.0.0.1:${STAND_CORE_PORT:-8799}
# the stand lives in a temp folder; on the page its folders read like the machines they stand for,
# and every device except the MacBook reports the Linux it plays
ROOTS_RE=$(printf '%s' "$STAND/roots" | sed 's|^/private||; s|[/.]|\\&|g')
OPEN="(() => {
  const R = [[/(?:\\/private)?${ROOTS_RE}\\/studio\\/home/g, '/Users/v'], [/(?:\\/private)?${ROOTS_RE}\\/(?:atlas|forge)\\/srv/g, '/srv']];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) { let v = n.nodeValue; for (const [a, b] of R) v = v.replace(a, b); if (v !== n.nodeValue) n.nodeValue = v; }
  const P = { atlas: 'linux-x86_64', forge: 'linux-x86_64', pi: 'linux-aarch64' };
  document.querySelectorAll('.device').forEach((d) => { const name = d.querySelector('.row-title')?.firstChild?.textContent?.trim(); const desc = d.querySelector('.row-desc'); if (P[name] && desc) desc.textContent = desc.textContent.replace('darwin-arm64', P[name]); });
  document.querySelectorAll('.work-head').forEach((b) => { if (!b.closest('.work').classList.contains('open')) b.click(); });
})()"
state() { .venv/bin/python -c "import json,sys; print(json.load(open('$STAND/state.json'))['$1'])"; }
FORGE=$(state forge_task); PROJECT=$(state project)
shot() { $P shot "$U/$2" "$OUT/$1.png" "${3:-1440}" "${4:-900}" "${5:-2}" "${6:-}" 2>/dev/null | grep -o 'saved.*'; }
.venv/bin/python landing/stand/stand.py offline pi
rm -rf "$STAND/chrome/cdp"; $P start cdp
$P shot "$U/login?link=$(.venv/bin/python landing/stand/stand.py link)" "$OUT/login.png" 2>/dev/null | grep -o 'saved.*'
shot new "#/" 1440 900 2 "$OPEN"
shot hero-approval "#/chat/$FORGE" 1440 900 2 "$OPEN"
.venv/bin/python landing/stand/stand.py approve; sleep 3
shot hero-done "#/chat/$FORGE" 1440 900 2 "$OPEN"
shot devices "#/settings/devices" 1440 900 2 "$OPEN"
shot project "#/projects/$PROJECT" 1440 900 2 "$OPEN"
shot automations "#/automations"
shot plugins "#/settings/plugins"
shot memory "#/settings/memory"
shot audit "#/settings/audit" 1440 900 2 "$OPEN"
$P stop
# into the landing: 1920 px wide, jpeg
for n in new hero-approval hero-done devices project automations plugins memory audit; do
  t=$n; [ "$n" = new ] && t=hero-new
  sips -s format jpeg -s formatOptions 82 --resampleWidth 1920 "$OUT/$n.png" --out "landing/shots/$t.jpg" >/dev/null
done
printf '{"mensarium": "%s", "captured": "%s", "how": "headless Chrome over CDP against a throwaway Core with three paired clients; every screen is the product UI as served by Core"}\n' "$(.venv/bin/mensarium version | cut -d' ' -f2)" "$(date -u +%Y-%m-%dT%H:%MZ)" > landing/shots/provenance.json
echo "landing/shots updated"
