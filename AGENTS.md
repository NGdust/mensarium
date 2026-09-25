# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Состояние репозитория

Проект называется **Mensarium** (пакет `mensarium`, команда `mensarium`, данные в `~/.mensarium`, env `MENSARIUM_HOME`). Требования — [.docs/portable-agent-harness-spec.md](.docs/portable-agent-harness-spec.md). Репозиторий `git@github.com:NGdust/mensarium.git` будет публичным: `.docs/`, `AGENTS.md`, `.Codex/` в git не попадают (см. `.gitignore`).

Осознанные отступления от спеки (пользователь просил установку без Docker одним `install.sh`):
- SQLite (`core/db.py`) вместо Postgres/Redis/Dramatiq; agent loop — asyncio-задачи внутри процесса Core (`core/orchestrator.py`).
- Один Python-пакет `src/mensarium/` вместо monorepo `apps/` + `packages/`; подпакеты повторяют `packages/*` из спеки.
- UI — статический vanilla JS (`core/web/`), раздаётся самим Core; без Next.js.
- Бэкап `.pab` — scrypt + AES-GCM по паролю вместо age; без TLS/mTLS, целостность запросов держат подписи ED25519.
- Добавлен read-tool `files.list`; правки файлов — через `shell.exec` `git apply -` со stdin.

## Команды

- `make dev` — `.venv` с пакетом в editable-режиме; `make lint` (= `make test`) — ruff + mypy; юнит-тестов пока нет по просьбе пользователя.
- `make dist` — `dist/install.sh` + `dist/mensarium.tar.gz` из `HEAD` (коммитить до сборки) для раздачи на https://mensarium.com.
- `mensarium core serve` / `mensarium target run` — foreground; `mensarium setup` — интерактивный мастер; `mensarium status`.
- Сервер 194.87.128.55 (общий, там же другие проекты): установщик раздаёт nginx из `/var/www/mensarium-install/`, конфиг `/etc/nginx/sites-available/mensarium-install.conf`.

## Архитектура

Три роли, границы между ними — главный инвариант проекта:

- **Core (Main Agent / Harness)** — `apps/core-api` (FastAPI: REST, WebSocket, auth) + `apps/core-worker` (agent loop, Dramatiq + Redis). Вызывает LLM, строит контекст, валидирует tool proposals, ждёт approval, пишет аудит. Сам на target ничего не исполняет.
- **LLM** — только предлагает действие в строгой схеме (`final` или `tool_call`). Не видит секретов, shell, сети и target напрямую.
- **Target Agent** — `apps/target-agent`, Python asyncio daemon без LLM. Держит исходящее WSS-соединение к Core, входящих портов не открывает, исполняет только подписанные ED25519 `execution.request` (проверка signature, nonce, TTL, `policy_snapshot_hash`).

Общий код живёт в `packages/`: `contracts` (Pydantic + JSON Schema, источник правды для всех сообщений), `agent-core` (state machine, context builder), `llm-providers`, `policy-engine`, `tool-runtime`, `target-protocol`, `shared`. UI — `apps/web` (Next.js + TypeScript + shadcn/ui).

### Поток исполнения tool call

```
LLM proposal → schema validation → target capability check → policy evaluation
→ risk classification → approval (если нужен) → signed request → target execution
→ signed result → artifact storage → observation в контекст → следующий шаг
```

Состояния задачи: `NEW → VALIDATING → PLANNING → WAITING_APPROVAL → EXECUTING → OBSERVING → PLANNING | SUCCEEDED | FAILED | CANCELED | PAUSED`. После рестарта Core задача уходит в `PAUSED` или `FAILED_RECOVERABLE` и сама не продолжает.

### LLM-провайдеры

Весь domain-код работает через протокол `LLMProvider` (`list_models`, `chat`, `healthcheck`) и собственные `ChatRequest` / `ModelResponse`. Фаза 1 — `OllamaCloudProvider` (OpenAI-compatible endpoint), фаза 2 — `LocalOllamaProvider` и `LlamaCppProvider`. Смена провайдера меняет только конфиг: контракты, профили, политики, Target Agent и UI не трогаются. Provider, model, параметры и usage сохраняются в `task_steps`.

## Инварианты безопасности

Нарушение любого из них — баг, даже если функционально всё работает:

- `target_id`, allowed roots, risk и scope вычисляет Core; из ответа модели их не берём.
- Tool descriptions и политики грузятся из доверенного registry, из RAG и tool output — никогда. Содержимое файлов, stdout/stderr и веб-страниц — недоверенные данные.
- Модель не может вызвать tool вне `allowed_tools` активного профиля.
- Риски `write`, `execute`, `network`, `destructive` требуют approval на конкретное действие (`Approve once`, с expiry, повторно не используется). `privileged` в MVP запрещён.
- `OLLAMA_API_KEY` и прочие секреты живут только в Core; в prompts, UI bundle, логи, audit и Target Agent не попадают. Интеграции получают ссылки вида `secret://name`.
- `files.read` / `files.search` редактируют `.env`, токены и приватные ключи.
- Replay и подмена execution request блокируются (nonce + expiry + подпись).

## Правила разработки из спеки

- Любое изменение контракта в `packages/contracts` идёт вместе с JSON Schema и contract test.
- Каждый запрос и tool call несёт `request_id`, `trace_id`, `task_id`, `target_id`, `workspace_id`.
- Внешние ID — UUIDv7 или ULID с префиксами (`task_`, `tgt_`, `tc_`, `apr_`, `ws_`).
- Конфигурация через env / config file, секреты — SOPS+age или Docker secrets.
- Логи — JSON, трейсинг — OpenTelemetry.
- Не выходить за v0.1 scope без явной просьбы: один пользователь и workspace, профиль `coding-agent-v1`, tools `files.read`, `files.search`, `git.status`, `git.diff`, `shell.exec`; без browser, screen capture и MCP.
