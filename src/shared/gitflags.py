"""Flags every git call of Mensarium runs with: no colors, no signing, no hooks, no filesystem monitor."""

GIT_SAFE_FLAGS = ("-c", "color.ui=never", "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
