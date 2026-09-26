#!/bin/sh
# Mensarium installer: installs the `mensarium` command; `mensarium core` or `mensarium client` configures the machine.
#   curl -fsSL https://mensarium.com/install.sh | sh
#   sh install.sh                      (from a source checkout)
#   sh install.sh uninstall
set -eu

MENSARIUM_HOME="${MENSARIUM_HOME:-$HOME/.mensarium}"
MENSARIUM_SOURCE_DEFAULT=""
MENSARIUM_SOURCE="${MENSARIUM_SOURCE:-$MENSARIUM_SOURCE_DEFAULT}"
BIN_DIR="${MENSARIUM_BIN_DIR:-$HOME/.local/bin}"
PYTHON_VERSION="3.12"

ACTION="install"

if [ -t 1 ]; then
  B="$(printf '\033[1m')"; D="$(printf '\033[2m')"; R="$(printf '\033[0m')"
  CY="$(printf '\033[36m')"; GR="$(printf '\033[32m')"; YE="$(printf '\033[33m')"; RE="$(printf '\033[31m')"
else
  B=""; D=""; R=""; CY=""; GR=""; YE=""; RE=""
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %s\n' "$GR" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$YE" "$R" "$*"; }
die()  { printf '\n  %s✗ %s%s\n\n' "$RE" "$*" "$R" >&2; exit 1; }

usage() {
  cat <<EOF
Mensarium installer

Usage: install.sh [options]
       install.sh uninstall

Options:
  --source PATH|URL    Source checkout, .tar.gz URL or git URL

After installing, run `mensarium core` on the main machine or `mensarium client` on another machine the agent should work on.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --source) MENSARIUM_SOURCE="$2"; shift 2 ;;
    uninstall) ACTION="uninstall"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

LOG="$(mktemp "${TMPDIR:-/tmp}/mensarium-install.XXXXXX")"

run_step() {
  title="$1"; shift
  if [ -t 1 ]; then
    ("$@") >>"$LOG" 2>&1 &
    pid=$!
    i=0
    while kill -0 "$pid" 2>/dev/null; do
      case $((i % 10)) in
        0) f='⠋';; 1) f='⠙';; 2) f='⠹';; 3) f='⠸';; 4) f='⠼';; 5) f='⠴';; 6) f='⠦';; 7) f='⠧';; 8) f='⠇';; *) f='⠏';;
      esac
      printf '\r  %s%s%s %s' "$CY" "$f" "$R" "$title"
      i=$((i + 1))
      sleep 0.1
    done
    if wait "$pid"; then
      printf '\r  %s✓%s %s\n' "$GR" "$R" "$title"
    else
      printf '\r  %s✗%s %s\n' "$RE" "$R" "$title"
      say "${D}--- last lines of $LOG ---${R}"
      tail -n 25 "$LOG" >&2
      exit 1
    fi
  else
    say "  - $title"
    "$@" >>"$LOG" 2>&1 || { tail -n 25 "$LOG" >&2; die "$title failed"; }
  fi
}

fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then wget -q "$1" -O "$2"
  else die "curl or wget is required"; fi
}

banner() {
  printf '%s' "$CY$B"
  cat <<'EOF'

 __  __ _____ _   _ ____    _    ____  ___ _   _ __  __
|  \/  | ____| \ | / ___|  / \  |  _ \|_ _| | | |  \/  |
| |\/| |  _| |  \| \___ \ / _ \ | |_) || || | | | |\/| |
| |  | | |___| |\  |___) / ___ \|  _ < | || |_| | |  | |
|_|  |_|_____|_| \_|____/_/   \_\_| \_\___|\___/|_|  |_|
EOF
  printf '%s' "$R"
  say "  ${D}Portable Agent Harness installer${R}"
  say ""
}

if [ "$ACTION" = "uninstall" ]; then
  if [ -x "$MENSARIUM_HOME/venv/bin/mensarium" ]; then
    "$MENSARIUM_HOME/venv/bin/mensarium" uninstall --purge </dev/tty
  else
    say "Mensarium is not installed in $MENSARIUM_HOME"
  fi
  exit 0
fi

banner

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
  Darwin|Linux) ok "Platform: $OS $ARCH" ;;
  *) die "unsupported OS: $OS (macOS and Linux are supported)" ;;
esac
command -v tar >/dev/null 2>&1 || die "tar is required"

# ---- source ---------------------------------------------------------------
SRC_DIR="$MENSARIUM_HOME/src"
SCRIPT_DIR=""
case "$0" in
  */install.sh|install.sh) SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)" ;;
esac

stage_source() {
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/mensarium-src.XXXXXX")"
  mkdir -p "$tmp/x"
  if [ -n "$MENSARIUM_SOURCE" ] && [ -d "$MENSARIUM_SOURCE" ]; then
    (cd "$MENSARIUM_SOURCE" && tar -cf - pyproject.toml install.sh src $( [ -f README.md ] && echo README.md )) | (cd "$tmp/x" && tar -xf -)
  elif [ -n "$MENSARIUM_SOURCE" ] && [ -f "$MENSARIUM_SOURCE" ]; then
    tar -xzf "$MENSARIUM_SOURCE" -C "$tmp/x"
  elif [ -n "$MENSARIUM_SOURCE" ]; then
    case "$MENSARIUM_SOURCE" in
      *.git|git@*) git clone --depth 1 "$MENSARIUM_SOURCE" "$tmp/x/repo" ;;
      *) fetch "$MENSARIUM_SOURCE" "$tmp/src.tar.gz" && tar -xzf "$tmp/src.tar.gz" -C "$tmp/x" ;;
    esac
  fi
  pkg="$(find "$tmp/x" -maxdepth 2 -name pyproject.toml | head -n 1)"
  [ -n "$pkg" ] || { echo "source has no pyproject.toml"; exit 1; }
  pkg="$(dirname "$pkg")"
  if [ "$(cd "$pkg" && pwd -P)" != "$(mkdir -p "$SRC_DIR" && cd "$SRC_DIR" && pwd -P)" ]; then
    rm -rf "$SRC_DIR"
    mkdir -p "$MENSARIUM_HOME"
    mv "$pkg" "$SRC_DIR"
  fi
  rm -rf "$tmp"
}

if [ -z "$MENSARIUM_SOURCE" ] && [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -f "$SCRIPT_DIR/src/__init__.py" ]; then
  MENSARIUM_SOURCE="$SCRIPT_DIR"
fi
if [ -z "$MENSARIUM_SOURCE" ]; then
  die "no source: run from a checkout, pass --source, or set MENSARIUM_SOURCE=<git or tar.gz url>"
fi
mkdir -p "$MENSARIUM_HOME"
chmod 700 "$MENSARIUM_HOME"
run_step "Fetching Mensarium source" stage_source

# ---- uv + python ------------------------------------------------------------
UV="$(command -v uv 2>/dev/null || true)"
install_uv() {
  mkdir -p "$MENSARIUM_HOME/bin"
  fetch https://astral.sh/uv/install.sh "$MENSARIUM_HOME/uv-install.sh"
  UV_INSTALL_DIR="$MENSARIUM_HOME/bin" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh "$MENSARIUM_HOME/uv-install.sh"
  rm -f "$MENSARIUM_HOME/uv-install.sh"
}
if [ -z "$UV" ]; then
  if [ -x "$MENSARIUM_HOME/bin/uv" ]; then
    UV="$MENSARIUM_HOME/bin/uv"
  else
    run_step "Installing uv (Python toolchain manager)" install_uv
    UV="$MENSARIUM_HOME/bin/uv"
  fi
fi
ok "uv: $("$UV" --version)"

VENV="$MENSARIUM_HOME/venv"
make_venv() { "$UV" venv --quiet --allow-existing --python "$PYTHON_VERSION" "$VENV"; }
install_pkg() { "$UV" pip install --quiet --python "$VENV/bin/python" --reinstall-package mensarium "$SRC_DIR"; }
run_step "Preparing Python $PYTHON_VERSION environment" make_venv
run_step "Installing Mensarium and dependencies" install_pkg

mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/mensarium" "$BIN_DIR/mensarium"
ok "Command installed: $BIN_DIR/mensarium ($("$VENV/bin/mensarium" version))"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not in PATH; add: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
rm -f "$LOG"

say ""
say "  Next step on this machine:"
say "    ${B}mensarium core${R}     run the Core here (the agent's brain, the web UI and its first device)"
say "    ${B}mensarium client${R}   connect this machine to a Core (the agent works here, the web UI opens here)"
say ""
