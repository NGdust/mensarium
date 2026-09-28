"""OpenAI-compatible mock: picks a scripted scenario by the task text, answers step by step with real tool calls."""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

MODEL = "qwen3-coder:30b"
LOG = open(sys.argv[1] if len(sys.argv) > 1 else "/dev/null", "a")


def call(name, **args):
    return {"tool": name, "args": args}


def final(text):
    return {"final": text}


SCENARIOS = [
    ("nightly backup on forge", [
        call("files.read", path="log/backup.log"),
        call("files.read", path="etc/cron.d/backup"),
        call("files.list", path="backup", depth=1),
        {"text": "The cron job still calls `/opt/backup/run.sh`, which was moved to `/srv/backup/run.sh` on the 22nd. I will point the job at the new path; the schedule and the log destination stay as they are.",
         **call("files.edit", path="etc/cron.d/backup", old="/opt/backup/run.sh", new="/srv/backup/run.sh")},
        call("files.read", path="etc/cron.d/backup"),
        final("Fixed. The job in `srv/etc/cron.d/backup` pointed to `/opt/backup/run.sh`, which no longer exists after the move on the 22nd; it now runs `/srv/backup/run.sh`. Cron re-reads `/etc/cron.d` on its own, so the next run is tonight at 02:00.\n\nIf you want, I can add a `--verify` run after the backup so a missing script is reported instead of failing silently."),
    ]),
    ("502 for the grafana host", [
        call("files.read", path="nginx/sites/grafana.conf"),
        call("files.read", path="log/nginx-error.log", max_lines=40),
        call("files.read", path="apps/monitoring/compose.yaml"),
        final("The upstream moved, nginx did not. `grafana.conf` still proxies to `127.0.0.1:3000`, but `compose.yaml` was changed yesterday to publish Grafana on port `3100` (the comment says it was freed for the new build service). Every request since then hits a closed port, which nginx reports as `connect() failed (111: Connection refused)` and answers with 502.\n\nTwo ways to fix it:\n\n1. Change `proxy_pass` in `srv/nginx/sites/grafana.conf` to `http://127.0.0.1:3100` and reload nginx.\n2. Or move Grafana back to 3000 in `compose.yaml` if the other service can take a different port.\n\nSay which one and I will make the change; both need your approval since they touch config files."),
    ]),
    ("free 20 gb", [
        call("files.list", path=".", depth=2),
        call("files.list", path="Library/Caches", depth=1),
        call("files.list", path="Downloads", depth=1),
        final("Here is what I would remove first, largest and safest at the top. Nothing is deleted yet.\n\n| Path | Size | Why it is safe |\n|---|---|---|\n| `home/Library/Caches/Homebrew` | 9.8 GB | downloaded bottles, brew re-downloads on demand |\n| `home/Library/Caches/pip` | 3.1 GB | wheel cache, rebuilt automatically |\n| `home/Downloads/ubuntu-24.04.1-live-server-arm64.iso` | 2.6 GB | installer, already used for forge |\n| `home/Downloads/xcode-cli-tools-16.dmg` | 1.9 GB | installed, the image is not needed |\n| `home/Library/Caches/com.docker.docker` | 1.4 GB | build cache, docker recreates it |\n| `home/Library/Caches/ms-playwright` | 1.2 GB | browser builds, re-downloaded by playwright install |\n\nThat is 20.0 GB. Photos, Documents and the projects folder are untouched. Tell me to go ahead and I will delete them one by one, each with your approval."),
    ]),
    ("open ports", [
        call("shell.exec", command="cat status/ports.txt"),
        final("Listening right now:\n\n| Port | Process | Note |\n|---|---|---|\n| 22 | sshd | expected |\n| 80, 443 | nginx | expected, both proxied to containers |\n| 3100 | grafana (docker-proxy) | moved from 3000 yesterday |\n| 5432 | postgres | bound to 127.0.0.1 only |\n| 8787 | mensarium core | this Core |\n| 9090 | prometheus (docker-proxy) | bound to 0.0.0.0, was 127.0.0.1 last week |\n\nThe one to look at is 9090: prometheus is now reachable from the network without auth. It was probably a `ports:` edit in `compose.yaml`; I can bind it back to localhost if you want."),
    ]),
    ("morning report", [
        call("files.read", path="status/summary.txt"),
        final("Morning report for atlas.\n\n- Disks: `/` 61% used (38 GB free), `/srv` 44% (312 GB free). No change since yesterday.\n- Updates: 4 packages pending, none security. `nginx` 1.26.2 → 1.26.3.\n- Failed units: none. `backup.service` ran at 02:00 and finished in 6 min.\n- Containers: 7 running, 0 restarted overnight.\n\nNothing needs you today."),
    ]),
    ("certificate on the mail host", [
        call("files.read", path="status/cert.txt"),
        final("NO_REPLY"),
    ]),
    ("rotate nginx logs", [
        call("files.list", path="log", depth=1),
        final("Rotated 3 files older than 30 days in `srv/log` (412 MB), kept the last 30 days as is. The next run is Sunday 03:00."),
    ]),
    ("healthcheck to the backup container", [
        call("files.read", path="compose.yaml"),
        {"text": "The `backup` service has no `healthcheck`, so compose reports it as running even when restic cannot reach the repository. I will add a check that runs `restic snapshots --last` every 10 minutes with a 30 second timeout.",
         **call("files.edit", path="compose.yaml", old="    volumes:\n      - ./backup:/etc/backup:ro\n      - data:/data:ro\n", new="    volumes:\n      - ./backup:/etc/backup:ro\n      - data:/data:ro\n    healthcheck:\n      test: [\"CMD\", \"restic\", \"snapshots\", \"--last\", \"--quiet\"]\n      interval: 10m\n      timeout: 30s\n      retries: 3\n")},
        call("git.diff", repo="."),
        final("Added a `healthcheck` to the `backup` service in `compose.yaml`: `restic snapshots --last --quiet` every 10 minutes, 30 s timeout, unhealthy after 3 failures. The change is committed on this chat's branch; merge it when you are happy with the interval."),
    ]),
    ("docker compose pull fail on pi", [
        call("files.read", path="compose.yaml"),
        final("`docker compose pull` fails on pi because two images in `compose.yaml` have no arm64 build: `grafana/loki:2.9.2` is fine, but `cadvisor` is pinned to an amd64-only tag and `mailhog/mailhog` has never published arm64. On a Raspberry Pi the pull ends with `no matching manifest for linux/arm64/v8`.\n\nOptions: use `gcr.io/cadvisor/cadvisor:v0.49.1` (multi-arch) and replace mailhog with `axllent/mailpit`, or keep those two services on atlas only with a profile."),
    ]),
    ("what changed", [
        call("git.status", repo="."),
        call("git.diff", repo="."),
        final("Two files changed since the last commit:\n\n- `compose.yaml`: Grafana now publishes port 3100 instead of 3000, with a comment that 3000 was freed for the build service.\n- `nginx/sites/grafana.conf`: unchanged, which is why the proxy still points at 3000.\n\nNothing is staged yet."),
    ]),
]


def pick(messages):
    text = ""
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content")
            text = c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            break
    low = text.lower()
    for key, steps in SCENARIOS:
        if key in low:
            return steps
    return [final("Done. Nothing else was needed for this request.")]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._json({"object": "list", "data": [{"id": MODEL, "object": "model"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        messages = body.get("messages", [])
        LOG.write(json.dumps({"n": len(messages), "last": str(messages[-1].get("content"))[:300] if messages else ""}) + "\n"); LOG.flush()
        steps = pick(messages)
        done = sum(1 for m in messages if m.get("role") == "assistant")
        step = steps[min(done, len(steps) - 1)]
        time.sleep(0.6)
        msg = {"role": "assistant", "content": step.get("text") or step.get("final") or None}
        finish = "stop"
        if "tool" in step:
            msg["tool_calls"] = [{"id": f"call_{done + 1}", "type": "function", "function": {"name": step["tool"].replace(".", "__"), "arguments": json.dumps(step["args"])}}]
            finish = "tool_calls"
        prompt = len(json.dumps(messages)) // 4
        out = len(json.dumps(msg)) // 4
        self._json({
            "id": f"chatcmpl-{int(time.time() * 1000)}", "object": "chat.completion", "created": int(time.time()), "model": MODEL,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": out, "total_tokens": prompt + out,
                      "prompt_tokens_details": {"cached_tokens": int(prompt * 0.8) if done else 0}},
        })


HTTPServer(("127.0.0.1", int(sys.argv[2]) if len(sys.argv) > 2 else 8798), H).serve_forever()
