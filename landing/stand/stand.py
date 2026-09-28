"""Throwaway Mensarium stand for the landing screenshots: mock LLM on 8798, Core on 8799, three real clients, scripted chats.
Usage: stand.py up | seed | approve | link | offline NAME | down. Ports: STAND_CORE_PORT (8799), STAND_MODEL_PORT (8798). Everything lives under $MENSARIUM_STAND (default /tmp/mensarium-stand);
only PIDs from its pids.txt are ever killed. Needs `make dev` first; run from the repo checkout."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent
PY = REPO / ".venv/bin/python"
MENS = REPO / ".venv/bin/mensarium"
STAND = Path(os.environ.get("MENSARIUM_STAND", "/tmp/mensarium-stand"))
ROOTS = STAND / "roots"
CORE_HOME = STAND / "home-core"
CORE_PORT = int(os.environ.get("STAND_CORE_PORT", "8799"))
MODEL_PORT = int(os.environ.get("STAND_MODEL_PORT", "8798"))
CORE_URL = f"http://127.0.0.1:{CORE_PORT}"
PIDS = STAND / "pids.txt"
STATE = STAND / "state.json"


def env_for(home):
    return {**os.environ, "MENSARIUM_HOME": str(home), "PYTHONUNBUFFERED": "1"}


def spawn(cmd, home, log):
    p = subprocess.Popen(cmd, env=env_for(home), stdout=open(log, "ab"), stderr=subprocess.STDOUT, start_new_session=True)
    with open(PIDS, "a") as f:
        f.write(f"{p.pid} {Path(home).name} {' '.join(map(str, cmd))}\n")
    return p


def wait_http(url, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"timeout waiting for {url}")


def up():
    STAND.mkdir(parents=True, exist_ok=True)
    if not ROOTS.exists():
        subprocess.run([sys.executable, str(SCRIPTS / "seed_files.py"), str(ROOTS)], check=True)
    (CORE_HOME / "core").mkdir(parents=True, exist_ok=True)
    cfg = {
        "server": {"host": "127.0.0.1", "port": CORE_PORT, "public_url": CORE_URL},
        "device": {"enabled": True, "name": "atlas", "roots": [str(ROOTS / "atlas/srv")], "allow_full_access": True, "allow_shell": True, "allow_remote_plugins": True},
        "plugins": {"catalog_url": None},
        "llm": {"active_provider": "local", "providers": {"local": {"kind": "llama_cpp", "base_url": f"http://127.0.0.1:{MODEL_PORT}/v1", "default_model": "qwen3-coder:30b", "timeout_s": 60, "max_retries": 0}}},
    }
    (CORE_HOME / "core/config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    spawn([sys.executable, str(SCRIPTS / "mock_llm.py"), str(STAND / "mock.log"), str(MODEL_PORT)], CORE_HOME, STAND / "mock-server.log")
    wait_http(f"http://127.0.0.1:{MODEL_PORT}/v1/models")
    spawn([str(MENS), "core", "serve"], CORE_HOME, STAND / "core.log")
    wait_http(f"{CORE_URL}/healthz", 60)
    print("core up")


class Api:
    def __init__(self):
        token = subprocess.run([str(MENS), "core", "token"], env=env_for(CORE_HOME), capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
        self.c = httpx.Client(base_url=CORE_URL, timeout=60)
        r = self.c.post("/v1/auth/login", json={"token": token})
        r.raise_for_status()

    def get(self, path, **kw):
        r = self.c.get(path, **kw); r.raise_for_status(); return r.json()

    def post(self, path, body=None):
        r = self.c.post(path, json=body or {})
        if r.status_code >= 400:
            raise RuntimeError(f"{path}: {r.status_code} {r.text[:400]}")
        return r.json()

    def wait_task(self, task_id, timeout=180):
        t0 = time.time()
        while time.time() - t0 < timeout:
            t = self.get(f"/v1/tasks/{task_id}")
            if t["status"] in ("SUCCEEDED", "FAILED", "CANCELED", "PAUSED", "FAILED_RECOVERABLE", "WAITING_APPROVAL"):
                return t
            time.sleep(1)
        raise SystemExit(f"task {task_id} still {t['status']}")

    def pending_approval(self, task_id):
        found = None
        try:
            with self.c.stream("GET", f"/v1/tasks/{task_id}/events", timeout=httpx.Timeout(10, read=4)) as r:
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[5:])
                    if ev.get("event") == "tool_call.pending_approval":
                        found = ev["payload"]["approval_id"]
                    if ev.get("event") == "tool_call.approval_decided":
                        found = None
        except httpx.ReadTimeout:
            pass
        return found

    def run(self, target_id, text, mode="ask", project_id=None):
        t = self.post("/v1/tasks", {"target_id": target_id, "input": text, "mode": mode, "project_id": project_id})
        t = self.wait_task(t["id"])
        while t["status"] == "WAITING_APPROVAL":
            aid = self.pending_approval(t["id"])
            if not aid:
                time.sleep(1); t = self.get(f"/v1/tasks/{t['id']}"); continue
            self.post(f"/v1/approvals/{aid}/decision", {"decision": "approve", "confirm": True})
            time.sleep(1)
            t = self.wait_task(t["id"])
        print(f"  task {t['id']} {t['status']}: {text[:60]}")
        return t


def pair_client(api, name, roots, gateway_port=None):
    home = STAND / f"home-{name}"
    home.mkdir(exist_ok=True)
    code = api.post("/v1/targets/pairing-codes")["code"]
    script = (
        "from mensarium.client.pairing import pair\nfrom mensarium.client.config import ClientPaths, load_client_config, save_client_config\n"
        f"p = ClientPaths(); pair(p, server={CORE_URL!r}, code={code!r}, name={name!r}, roots={roots!r}, allow_full_access={name == 'studio'!r}, allow_remote_update=False)\n"
        + (f"c = load_client_config(p); c.gateway.enabled = True; c.gateway.port = {gateway_port}; save_client_config(p, c)\n" if gateway_port else "")
    )
    subprocess.run([str(PY), "-c", script], env=env_for(home), check=True)
    spawn([str(MENS), "client", "run"], home, STAND / f"client-{name}.log")
    if gateway_port:
        spawn([str(MENS), "client", "gateway", "run"], home, STAND / f"gateway-{name}.log")
    print(f"client {name} paired and started")


def target_by_name(api, name, tries=30):
    for _ in range(tries):
        for t in api.get("/v1/targets"):
            if t["name"] == name and t["status"] == "online":
                return t["id"]
        time.sleep(1)
    raise SystemExit(f"{name} did not come online")


def seed():
    api = Api()
    atlas = target_by_name(api, "atlas")
    pair_client(api, "studio", [str(ROOTS / "studio/home")], gateway_port=8791)
    pair_client(api, "forge", [str(ROOTS / "forge/srv")])
    pair_client(api, "pi", [str(ROOTS / "forge/srv")])
    studio = target_by_name(api, "studio")
    forge = target_by_name(api, "forge")
    state = {"atlas": atlas, "studio": studio, "forge": forge}

    for pid in ("git-history", "docker", "web-search"):
        try:
            api.post("/v1/plugins", {"id": pid})
            print("  plugin", pid)
        except RuntimeError as e:
            print("  plugin failed", e)
    me = api.post("/v1/memory/center", {"title": "About me"})
    api.c.patch(f"/v1/memory/notes/{me['id']}", json={"body": "Runs a small homelab: [[atlas]] in Falkenstein, [[forge]] at home and a [[pi]] in the garage, works on [[studio]]. Prefers short answers and a diff before any change."}).raise_for_status()
    notes = [
        ("atlas", "Hetzner box in Falkenstein that runs Core. nginx in front of everything, monitoring stack in /srv/apps/monitoring. See [[Grafana moved to port 3100]].", "device", ["server"], False),
        ("forge", "Linux workstation at home. Nightly backups to the NAS, see [[Backups]].", "device", ["home"], False),
        ("studio", "MacBook Pro, the main laptop: Homebrew, uv, Docker Desktop.", "device", ["laptop"], False),
        ("pi", "Raspberry Pi 4 in the garage with zigbee2mqtt and DNS; often offline at night.", "device", ["home"], False),
        ("homelab", "Compose stacks for [[atlas]], [[forge]] and [[pi]]; the repository lives on [[studio]] in ~/projects/homelab.", "project", ["compose"], False),
        ("Backups", "restic to the NAS every night at 02:00 from [[forge]]; the script is /srv/backup/run.sh.", "howto", ["restic"], False),
        ("Rotate nginx logs weekly", "Logs older than 30 days go away every Sunday at 03:00 on [[atlas]].", "howto", ["nginx"], False),
        ("Grafana moved to port 3100", "Since 2026-09-27 Grafana publishes 3100 on [[atlas]]; 3000 is taken by the build service.", "fact", ["monitoring"], False),
        ("Show the diff before editing configs", "Show the exact old and new lines before proposing files.edit on anything under /etc. [[About me]]", "preference", ["approvals"], True),
        ("Short answers", "Lead with the result, a few sentences at most. [[About me]]", "preference", [], True),
        ("Maria", "Shares the NAS; ask before touching /volume1/family. Mostly uses [[forge]] shares.", "person", ["family"], False),
        ("Editor", "vim for quick edits, VS Code for projects.", "preference", [], False),
    ]
    for title, body, kind, tags, pinned in notes:
        api.post("/v1/memory/notes", {"title": title, "body": body, "kind": kind, "tags": tags, "pinned": pinned, "importance": 6})

    print("chats")
    api.run(atlas, "Why is nginx returning 502 for the grafana host since this morning?")
    api.run(atlas, "Show which ports are listening on the device and which processes own them. Point out anything unexpected.")
    api.run(studio, "Free 20 GB on this laptop without touching Photos. List what you would delete first.")

    print("project")
    proj = api.post("/v1/projects", {"name": "homelab", "source_target_id": studio, "source_path": str(ROOTS / "studio/home/projects/homelab")})
    for _ in range(60):
        p = api.get(f"/v1/projects/{proj['id']}")
        if p.get("status") == "ready":
            break
        if p.get("status") == "error":
            raise SystemExit(f"project error: {p}")
        time.sleep(1)
    state["project"] = proj["id"]
    api.run(studio, "Why does docker compose pull fail on pi", project_id=proj["id"])
    api.run(studio, "What changed in this repo since the last commit? Describe it briefly.", project_id=proj["id"])
    api.run(studio, "Add a healthcheck to the backup container", project_id=proj["id"])

    seed_rest(api, atlas, forge, state)


def seed_rest(api=None, atlas=None, forge=None, state=None):
    api = api or Api()
    if state is None:
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        atlas = atlas or target_by_name(api, "atlas")
        forge = forge or target_by_name(api, "forge")
        state.update({"atlas": atlas, "forge": forge})
    existing = {a["name"] for a in api.get("/v1/automations")["items"]}
    print("automations")
    autos = [
        ("Morning report: disks, updates, failed units", "Morning report for atlas: disk usage, pending updates, failed systemd units, containers restarted overnight. Read srv/status/summary.txt and summarize.", {"kind": "cron", "expr": "30 7 * * *", "tz": "Europe/Berlin"}, atlas),
        ("Check the certificate on the mail host", "Check the certificate on the mail host in srv/status/cert.txt. If it expires in more than 14 days answer NO_REPLY, otherwise say how many days are left.", {"kind": "every", "every_s": 6 * 3600, "tz": "Europe/Berlin"}, atlas),
        ("Rotate nginx logs older than 30 days", "Rotate nginx logs older than 30 days in srv/log, keep the last 30 days.", {"kind": "cron", "expr": "0 3 * * 0", "tz": "Europe/Berlin"}, atlas),
    ]
    for name, prompt, schedule, target in autos:
        if name in existing:
            continue
        a = api.post("/v1/automations", {"name": name, "prompt": prompt, "schedule": schedule, "target_id": target, "mode": "full"})
        if "certificate" in name or "Morning" in name:
            api.post(f"/v1/automations/{a['id']}/run")
            time.sleep(1)
            for _ in range(90):
                runs = api.get(f"/v1/automations/{a['id']}/runs")
                items = runs if isinstance(runs, list) else runs.get("items", [])
                if items and items[0]["status"] != "running":
                    break
                time.sleep(1)
            print("  run", name, items[0]["status"] if items else "none")

    print("forge chat, stops at the approval")
    t = api.post("/v1/tasks", {"target_id": forge, "input": "The nightly backup on forge has been failing since Tuesday. Find out why and fix the cron job.", "mode": "ask"})
    t = api.wait_task(t["id"])
    state["forge_task"] = t["id"]
    state["forge_status"] = t["status"]
    STATE.write_text(json.dumps(state, indent=2))
    print("seeded", state)


def approve_forge():
    api = Api()
    state = json.loads(STATE.read_text())
    aid = api.pending_approval(state["forge_task"])
    api.post(f"/v1/approvals/{aid}/decision", {"decision": "approve", "confirm": True})
    t = api.wait_task(state["forge_task"])
    print("forge", t["status"])


def link():
    script = "from mensarium.core.config import CorePaths\nfrom mensarium.client.gateway import auth\nprint(auth.write_link(CorePaths().device))"
    print(subprocess.run([str(PY), "-c", script], env=env_for(CORE_HOME), capture_output=True, text=True, check=True).stdout.strip())


def offline(name):
    """Stop one client's processes so the device shows as offline, the way a sleeping machine looks."""
    keep = []
    for line in PIDS.read_text().splitlines():
        pid, home = line.split()[:2]
        if home == f"home-{name}":
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            keep.append(line)
    PIDS.write_text("".join(f"{x}\n" for x in keep))
    print(f"{name} is offline")


def down():
    if not PIDS.exists():
        return
    for line in PIDS.read_text().splitlines():
        pid = int(line.split()[0])
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    PIDS.unlink()
    print("stand stopped")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "offline":
        offline(sys.argv[2])
    else:
        {"up": up, "seed": seed, "rest": seed_rest, "approve": approve_forge, "link": link, "down": down}[cmd]()
