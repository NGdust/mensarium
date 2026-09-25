[English](README.md) · Русский

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
| `mensarium update` | Обновиться: Core с mensarium.com, устройство со своего Core (`--check` только проверить). Из web UI: Обзор → «Обновить» для Core, Устройства → «Обновить до …» для агентов |
| `mensarium core serve` | Запуск Core в foreground |
| `mensarium core token` | Токен для входа в web UI |
| `mensarium core pair-code` | Одноразовый код пары (10 минут) |
| `mensarium core backup -o file.pab` / `restore file.pab` | Зашифрованный перенос Core на другой хост |
| `mensarium target pair --server URL --code CODE --root DIR` | Пара без мастера (`--no-full-access`, `--no-remote-update` — запреты на устройстве) |
| `mensarium target run` | Запуск Target Agent в foreground |
| `mensarium plugins list [--catalog]`, `info ID`, `install ID\|file.yaml`, `update ID`, `remove ID` | Плагины Core на этой машине |
| `mensarium plugins config ID KEY=VALUE [--secret KEY] [--placement core\|УСТРОЙСТВО] [--risk RISK]` | Настройки плагина; секреты вводятся без эха |
| `mensarium mcp add NAME --command 'npx -y pkg' \| --url URL [--secret-env KEY] [--device NAME]` | MCP-сервер в Core или на устройстве; `mcp list`, `probe`, `tools`, `remove` |
| `mensarium target plugins` | MCP-серверы, которые Core запустил на этом устройстве |
| `mensarium service install\|restart\|logs core\|target` | Управление сервисом |
| `mensarium uninstall --purge` | Удалить сервисы и данные |

## Как устроено

```
LLM proposal → schema validation → target capability check → policy evaluation
→ risk classification → approval (если нужен) → signed request → target execution
→ signed result → artifact → observation в контекст → следующий шаг
```

- LLM-провайдеры: Ollama Cloud, локальный Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter или любой OpenAI-совместимый сервер — все через OpenAI-совместимый API. Добавляются, проверяются и переключаются в Настройки → Провайдеры (или в `mensarium setup`); активный провайдер меняется без перезапуска, ключи хранятся в секретах Core.
- Режимы доступа в каждом чате: «С запросом действий» (по умолчанию) и «Полный доступ». Машина с Core всегда доступна агенту как устройство.
- Tools v0.1: `files.list`, `files.read`, `files.search`, `git.status`, `git.diff` (read, без подтверждения) и `shell.exec` (всегда с подтверждением «Approve once»). Правки файлов — через `git apply` с патчем в stdin.
- Память (Настройки → Память): заметки со ссылками `[[Название]]`, интерактивный граф связей и сновидения — ночная консолидация новых чатов в долговременную память с дневником. Агент ищет, читает и дополняет память инструментами `memory.*`, закреплённые и важные заметки попадают в системный промпт.
- Плагины (Настройки → Плагины или `mensarium plugins` / `mensarium mcp` на сервере Core) расширяют агента: навыки — инструкции, которые он загружает через `skills.read`; инструменты устройства — шаблоны команд, которые уходят на устройство как `shell.exec`; инструменты Core работают в самом Core (`web.search` через Brave Search, `web.fetch` с блокировкой внутренних адресов); MCP-серверы работают в Core или на выбранном устройстве и дают агенту `mcp.<сервер>.<инструмент>`. У плагинов есть настройки с секретными полями, которые остаются в Core, и уровень риска, от которого зависит подтверждение; каталог встроен в релиз и обновляется с mensarium.com. Устройство запускает MCP-сервер, только если его программа есть в списке разрешённых и устройство разрешает плагины от Core. Если для запроса у агента нет инструмента (поиск в интернете, браузер, GitHub...), он ищет плагин в каталоге через `plugins.find` и предлагает его через `plugins.install`: установка всегда ждёт подтверждения, даже в полном доступе, ключи вводятся только в Настройки → Плагины, а сервер, который работает на устройстве, ставится на устройство этого чата.
- Каналы (Настройки → Каналы): общение с агентом из мессенджера. Telegram: вставьте токен бота из @BotFather; первый аккаунт Telegram, который напишет боту, становится его владельцем и единственным, кого бот слушает. Сообщения становятся задачами на выбранном устройстве (по умолчанию машина с Core) и продолжают один чат; `/new` начинает новый, `/stop` останавливает задачу. Подтверждения приходят кнопками, ответ — сообщением; токен хранится в секретах Core.
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
