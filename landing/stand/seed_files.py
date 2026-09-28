"""Device roots for the stand: files the scripted chats read and edit."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])


def w(path, text, mode=None):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    if mode:
        p.chmod(mode)


def sparse(path, size):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        f.truncate(size)


# ---- atlas: the Core host ----
w("atlas/srv/nginx/sites/grafana.conf", """server {
    listen 443 ssl http2;
    server_name grafana.home.lan;

    ssl_certificate     /etc/letsencrypt/live/home.lan/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/home.lan/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
""")
w("atlas/srv/log/nginx-error.log", "\n".join(
    f"2026/09/28 0{7 + i // 12}:{(i * 5) % 60:02d}:1{i % 10} [error] 1412#1412: *{8801 + i} connect() failed (111: Connection refused) while connecting to upstream, client: 10.0.1.{20 + i % 4}, server: grafana.home.lan, request: \"GET /api/health HTTP/2.0\", upstream: \"http://127.0.0.1:3000/api/health\", host: \"grafana.home.lan\""
    for i in range(36)) + "\n")
w("atlas/srv/apps/monitoring/compose.yaml", """services:
  grafana:
    image: grafana/grafana:11.2.0
    restart: unless-stopped
    ports:
      - "3100:3000"   # 3000 freed for the build service
    volumes:
      - grafana:/var/lib/grafana
    environment:
      GF_SERVER_ROOT_URL: https://grafana.home.lan

  prometheus:
    image: prom/prometheus:v2.54.1
    restart: unless-stopped
    ports:
      - "0.0.0.0:9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus:/prometheus

  loki:
    image: grafana/loki:2.9.2
    restart: unless-stopped
    volumes:
      - loki:/loki

volumes:
  grafana:
  prometheus:
  loki:
""")
w("atlas/srv/status/ports.txt", """COMMAND        PID   USER   FD   TYPE  NODE NAME
sshd           812   root    3u  IPv4  TCP *:22 (LISTEN)
nginx         1412   root    6u  IPv4  TCP *:80 (LISTEN)
nginx         1412   root    7u  IPv4  TCP *:443 (LISTEN)
docker-pr     2231   root    4u  IPv4  TCP *:3100 (LISTEN)
postgres      1120   postgres 5u IPv4  TCP 127.0.0.1:5432 (LISTEN)
mensarium     2790   v       9u  IPv4  TCP *:8787 (LISTEN)
docker-pr     2244   root    4u  IPv4  TCP *:9090 (LISTEN)
""")
w("atlas/srv/status/summary.txt", """disk / 61% used 38G free
disk /srv 44% used 312G free
updates pending: 4 (nginx 1.26.2 -> 1.26.3, curl, libssl3, tzdata)
failed units: none
backup.service last run 02:00 duration 6m12s status ok
containers running: 7 restarted overnight: 0
""")
w("atlas/srv/status/cert.txt", "mail.home.lan notAfter=Dec 14 09:12:00 2026 GMT issuer=Let's Encrypt\n")
for i, name in enumerate(["access.log.1", "access.log.2", "access.log.3", "error.log.1", "access.log"]):
    sparse(f"atlas/srv/log/{name}", 140_000_000 - i * 9_000_000)

# ---- forge: the Linux workstation ----
w("forge/srv/log/backup.log", "\n".join(
    f"Sep {d} 02:00:0{1 + (d % 3)} forge backup[{4100 + d * 87}]: /opt/backup/run.sh: No such file or directory"
    for d in (23, 24, 25, 26, 27, 28)) + "\n")
w("forge/srv/etc/cron.d/backup", "0 2 * * * root /opt/backup/run.sh --target nas >> /var/log/backup.log 2>&1\n")
w("forge/srv/backup/run.sh", "#!/bin/sh\nset -e\nrestic -r sftp:nas:/backups/forge backup /home /etc --exclude-file=/srv/backup/exclude.txt\nrestic -r sftp:nas:/backups/forge forget --keep-daily 14 --keep-weekly 8 --prune\ndate > /srv/backup/last-success\n", 0o755)
w("forge/srv/backup/exclude.txt", "/home/*/.cache\n/home/*/node_modules\n/home/*/.local/share/Trash\n")
w("forge/srv/backup/last-success", "Mon Sep 22 02:06:41 CEST 2026\n")

# ---- studio: the MacBook ----
home = "studio/home"
for d in ("Documents/notes", "Pictures/Photos Library.photoslibrary/originals", "Movies", "Music"):
    (ROOT / home / d).mkdir(parents=True, exist_ok=True)
sparse(f"{home}/Library/Caches/Homebrew/downloads/8f3e-node-22.9.0.arm64_sequoia.bottle.tar.gz", 9_800_000_000 // 3)
sparse(f"{home}/Library/Caches/Homebrew/downloads/1a2b-llvm-18.1.8.arm64_sequoia.bottle.tar.gz", 9_800_000_000 // 3)
sparse(f"{home}/Library/Caches/Homebrew/downloads/77c1-postgresql@16-16.4.arm64_sequoia.bottle.tar.gz", 9_800_000_000 // 3)
sparse(f"{home}/Library/Caches/pip/http-v2/wheels.cache", 3_100_000_000)
sparse(f"{home}/Library/Caches/com.docker.docker/buildkit.cache", 1_400_000_000)
sparse(f"{home}/Library/Caches/ms-playwright/chromium-1140/chrome-mac.zip", 1_200_000_000)
sparse(f"{home}/Downloads/ubuntu-24.04.1-live-server-arm64.iso", 2_600_000_000)
sparse(f"{home}/Downloads/xcode-cli-tools-16.dmg", 1_900_000_000)
w(f"{home}/Downloads/invoice-2026-09.pdf", "%PDF-1.4\n")
w(f"{home}/Documents/notes/homelab.md", "# homelab\n\n- atlas: core, nginx, monitoring\n- forge: builds, backups to nas\n- pi: zigbee, dns\n")

repo = ROOT / home / "projects" / "homelab"
repo.mkdir(parents=True, exist_ok=True)
(repo / "nginx" / "sites").mkdir(parents=True, exist_ok=True)
(repo / "backup").mkdir(exist_ok=True)
(repo / "compose.yaml").write_text("""services:
  grafana:
    image: grafana/grafana:11.2.0
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - grafana:/var/lib/grafana

  loki:
    image: grafana/loki:2.9.2
    restart: unless-stopped
    volumes:
      - loki:/loki

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.47.2-amd64
    restart: unless-stopped
    privileged: true

  mailhog:
    image: mailhog/mailhog:v1.0.1
    restart: unless-stopped
    ports:
      - "8025:8025"

  backup:
    image: restic/restic:0.17.1
    restart: unless-stopped
    entrypoint: ["/etc/backup/run.sh"]
    volumes:
      - ./backup:/etc/backup:ro
      - data:/data:ro

volumes:
  grafana:
  loki:
  data:
""")
(repo / "nginx" / "sites" / "grafana.conf").write_text("server {\n    listen 443 ssl http2;\n    server_name grafana.home.lan;\n    location / { proxy_pass http://127.0.0.1:3000; }\n}\n")
(repo / "backup" / "run.sh").write_text("#!/bin/sh\nrestic backup /data\n")
(repo / "README.md").write_text("# homelab\n\nCompose stacks for atlas, forge and pi.\n")
env = {**os.environ, "GIT_AUTHOR_NAME": "v", "GIT_AUTHOR_EMAIL": "v@home.lan", "GIT_COMMITTER_NAME": "v", "GIT_COMMITTER_EMAIL": "v@home.lan"}
if not (repo / ".git").exists():
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "monitoring stack and backup"], cwd=repo, check=True, env=env)
    (repo / "compose.yaml").write_text((repo / "compose.yaml").read_text().replace('      - "3000:3000"', '      - "3100:3000"   # 3000 freed for the build service'))
print("seeded", ROOT)
