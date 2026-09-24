# Mensarium

Переносимый agent harness. **Core** (главный агент) вызывает LLM, строит контекст, проверяет предложенные моделью действия политиками, ждёт подтверждения пользователя и пишет аудит. **Target Agent** — тонкий демон без LLM на управляемой машине: держит исходящее WebSocket-соединение к Core и исполняет только подписанные ED25519 запросы.

Модель никогда не получает прямого доступа к shell, файлам, сети или секретам: она только предлагает `tool_call`, а Core решает, можно ли его выполнить.

## Установка

Core (один раз, на сервере или ноутбуке):

```sh
git clone https://github.com/NGdust/mensarium.git && sh mensarium/install.sh
```

или с уже развёрнутого Core:

```sh
curl -fsSL http://<core-host>/install.sh | sh -s -- --role core
```

Target (на каждой машине, где агент будет работать). Код пары создаётся в UI Core (Targets → Pair new target) или командой `mensarium core pair-code`:

```sh
curl -fsSL http://<core-host>/install.sh | sh -s -- --code WOLF-SKY-4821
```

Установщик сам ставит [uv](https://docs.astral.sh/uv/) и Python 3.12 в `~/.mensarium`, кладёт команду `mensarium` в `~/.local/bin`, спрашивает настройки и регистрирует фоновый сервис (launchd на macOS, systemd на Linux). Docker не нужен.

## Команды

| Команда | Что делает |
|---|---|
| `mensarium setup` | Интерактивная настройка Core или Target |
| `mensarium status` | Что установлено и запущено |
| `mensarium core serve` | Запуск Core в foreground |
| `mensarium core token` | Токен для входа в web UI |
| `mensarium core pair-code` | Одноразовый код пары (10 минут) |
| `mensarium core backup -o file.pab` / `restore file.pab` | Зашифрованный перенос Core на другой хост |
| `mensarium target pair --server URL --code CODE --root DIR` | Пара без мастера |
| `mensarium target run` | Запуск Target Agent в foreground |
| `mensarium service install\|restart\|logs core\|target` | Управление сервисом |
| `mensarium uninstall --purge` | Удалить сервисы и данные |

## Как устроено

```
LLM proposal → schema validation → target capability check → policy evaluation
→ risk classification → approval (если нужен) → signed request → target execution
→ signed result → artifact → observation в контекст → следующий шаг
```

- LLM-провайдеры: Ollama Cloud, локальный Ollama, llama.cpp — все через OpenAI-совместимый API; смена провайдера меняет только конфиг.
- Tools v0.1: `files.list`, `files.read`, `files.search`, `git.status`, `git.diff` (read, без подтверждения) и `shell.exec` (всегда с подтверждением «Approve once»). Правки файлов — через `git apply` с патчем в stdin.
- Target проверяет подпись, nonce, срок жизни запроса, хеш политики и наличие approval; пути ограничены выбранными папками, программы — allowlist-ом; `.env`, ключи и токены не читаются и вычищаются из вывода.
- Хранилище Core — SQLite в `~/.mensarium/core`; секреты — файлы с правами 0600, в UI, промпты и на target не попадают.
- После рестарта Core незавершённые задачи переходят в `PAUSED` и сами не продолжаются.

## Разработка

```sh
make dev     # .venv с пакетом в editable-режиме
make lint    # ruff + mypy
make core    # Core в foreground (нужен ~/.mensarium/core/config.yaml, см. mensarium setup)
```
