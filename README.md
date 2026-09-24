# Mensarium

Переносимый agent harness. **Core** (главный агент) вызывает LLM, строит контекст, проверяет предложенные моделью действия политиками, ждёт подтверждения пользователя и пишет аудит. **Target Agent** — тонкий демон без LLM на управляемой машине: держит исходящее WebSocket-соединение к Core и исполняет только подписанные ED25519 запросы.

Модель никогда не получает прямого доступа к shell, файлам, сети или секретам: она только предлагает `tool_call`, а Core решает, можно ли его выполнить.

## Установка

Core (один раз, на сервере или ноутбуке):

```sh
curl -fsSL https://mensarium.com/install.sh | sh -s -- --role core
```

Target (на каждой машине, где агент будет работать). Код пары создаётся в UI Core (Targets → Pair new target) или командой `mensarium core pair-code`:

```sh
curl -fsSL https://mensarium.com/install.sh | sh -s -- --server http://<core-host>:8787 --code WOLF-SKY-4821
```

UI Core показывает готовую команду для target — она берёт установщик прямо с вашего Core и `--server` не требует.

Установщик сам ставит [uv](https://docs.astral.sh/uv/) и Python 3.12 в `~/.mensarium`, кладёт команду `mensarium` в `~/.local/bin`, спрашивает настройки и регистрирует фоновый сервис (launchd на macOS, systemd на Linux). Docker не нужен.

## Команды

| Команда | Что делает |
|---|---|
| `mensarium setup` | Интерактивная настройка Core или Target |
| `mensarium status` | Что установлено и запущено |
| `mensarium version` | Версия, роли на этой машине и доступное обновление |
| `mensarium update` | Обновиться: Core с mensarium.com, устройство со своего Core (`--check` только проверить) |
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
- Режимы доступа в каждом чате: «С запросом действий» (по умолчанию) и «Полный доступ». Машина с Core всегда доступна агенту как устройство.
- Tools v0.1: `files.list`, `files.read`, `files.search`, `git.status`, `git.diff` (read, без подтверждения) и `shell.exec` (всегда с подтверждением «Approve once»). Правки файлов — через `git apply` с патчем в stdin.
- Память (Настройки → Память): заметки со ссылками `[[Название]]`, интерактивный граф связей и сновидения — ночная консолидация новых чатов в долговременную память с дневником. Агент ищет, читает и дополняет память инструментами `memory.*`, закреплённые и важные заметки попадают в системный промпт.
- Маркетплейс (Настройки → Маркетплейс): навыки — инструкции, которые агент загружает через `skills.read`, и инструменты — шаблоны команд, которые уходят на устройство как `shell.exec` и проходят те же проверки и подтверждения. Каталог встроен в релиз и обновляется с mensarium.com; свой пакет добавляется манифестом в YAML.
- Target проверяет подпись, nonce, срок жизни запроса, хеш политики и наличие approval; пути ограничены выбранными папками, программы — allowlist-ом; `.env`, ключи и токены не читаются и вычищаются из вывода.
- Хранилище Core — SQLite в `~/.mensarium/core`; секреты — файлы с правами 0600, в UI, промпты и на target не попадают.
- После рестарта Core незавершённые задачи переходят в `PAUSED` и сами не продолжаются.

## Разработка

```sh
make dev     # .venv с пакетом в editable-режиме
make lint    # ruff + mypy
make dist    # dist/: install.sh, архив и latest.json для раздачи (нужен чистый git)
make release # dist + тег vX.Y.Z
make core    # Core в foreground (нужен ~/.mensarium/core/config.yaml, см. mensarium setup)
```
