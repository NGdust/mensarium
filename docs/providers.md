# LLM providers

Mensarium talks to the model through one active provider at a time, chosen from a config'd list. Every provider except the two local CLIs speaks the OpenAI-compatible `/v1/chat/completions` API; switching kinds only changes configuration, never the rest of the harness. This page covers the supported kinds, how to add and switch between them, and how context window, image and usage-limit handling differ per kind.

## Supported kinds

| Kind id | Title | Transport | Default address | Default model | API key |
|---|---|---|---|---|---|
| `ollama_cloud` | Ollama Cloud | HTTP | `https://ollama.com/v1` | `gpt-oss:120b` | required ([ollama.com/settings/keys](https://ollama.com/settings/keys)) |
| `ollama_local` | Ollama | HTTP | `http://127.0.0.1:11434/v1` | `qwen3:8b` | none |
| `llama_cpp` | llama.cpp | HTTP | `http://127.0.0.1:8080/v1` | `local` | none |
| `lmstudio` | LM Studio | HTTP | `http://127.0.0.1:1234/v1` | `local` | none |
| `openai` | OpenAI | HTTP | `https://api.openai.com/v1` | `gpt-4.1-mini` | required ([platform.openai.com/api-keys](https://platform.openai.com/api-keys)) |
| `openrouter` | OpenRouter | HTTP | `https://openrouter.ai/api/v1` | `openai/gpt-oss-120b` | required ([openrouter.ai/keys](https://openrouter.ai/keys)) |
| `openai_compatible` | OpenAI-compatible | HTTP | `http://127.0.0.1:8000/v1` (edit to your server) | — | optional |
| `claude_code` | Claude Code (local) | CLI | the `claude` command on the Core host | `claude-sonnet-5` | none (uses your Claude Code login) |
| `codex_cli` | Codex CLI (local) | CLI | the `codex` command on the Core host | account default | none (uses your Codex login) |

The two CLI kinds run a local coding-agent binary as the model call: their own tools are switched off for the call (`--tools ""` for Claude Code, `-s read-only`/`--ignore-rules` for Codex), Mensarium's tools are described in the prompt instead, and the answer is forced into a JSON object the harness parses as a tool call or final answer. They think through your existing subscription rather than an API key.

## Adding a provider

The first provider is set up by the `mensarium core`/`mensarium core setup` wizard (step 2 of 4): it auto-detects a `claude`/`codex` binary on the Core host (offered first, with login status shown) and otherwise asks for a kind, base URL, API key and default model, fetching the model list to fill an autocomplete prompt.

Every provider afterwards — adding, editing, or removing one — is done in Settings → Providers in the web UI, which calls:

```
GET    /v1/providers                 # list, plus locally-detected CLIs not yet added
PUT    /v1/providers/{id}            # add or edit
DELETE /v1/providers/{id}            # remove (refused if it's the only one)
POST   /v1/providers/test            # check reachability/login and list models, without saving
```

Fields on `PUT /v1/providers/{id}`:

| Field | Meaning |
|---|---|
| `kind` | One of the kind ids above |
| `base_url` | HTTP base URL, or the CLI command/path for `claude_code`/`codex_cli` |
| `default_model` | Required; must be non-empty |
| `api_key` | Omit to keep the currently stored key, send `""` to delete it, or a new value to replace it |
| `timeout_s` | Request timeout, 5-600, default 90 |
| `max_retries` | Retries on transport errors and `429`/`5xx` responses, 0-5, default 2 |
| `vision_model` | Optional — see [Image (vision) model](#image-vision-model) |

The provider id (`{id}` in the URL) is a free-form identifier (lowercase letters, digits, `-`, `_`) you choose; it doesn't have to match the kind, so you can run two `openai_compatible` providers side by side under different ids. An HTTP provider's key needs `http://`/`https://`; a CLI provider's `base_url` must be an executable found on the Core host.

## Where the API key is stored

Keys never appear in `config.yaml`. Saving one writes it to a file in `core/secrets/` (see [Configuration](configuration.md#data-directory-mensarium)) and `config.yaml` keeps only a `secret://<name>` reference. The first-run Ollama Cloud key is named `ollama-api-key`; every other provider's key is named `provider-<id>-key`. Removing a provider deletes its key file, unless another provider still references the same one.

## Claude Code / Codex CLI specifics

- **Detection**: Core probes `PATH` plus a handful of common install locations (`~/.local/bin`, `~/.claude/local`, `~/.claude/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, `~/.npm-global/bin`, `~/.volta/bin`, `~/.bun/bin`, `~/.cargo/bin`, and any `nvm` node version's `bin`) for `claude` and `codex`, cached 60 seconds. Detected-but-not-added CLIs show up in `GET /v1/providers`'s `detected` list.
- **Login**: Claude Code needs `claude auth status` to report logged in (run `claude` on the Core host and log in); Codex needs `codex login status`. `CLAUDE_CONFIG_DIR` (default `~/.claude`) and `CODEX_HOME` (default `~/.codex`) point at where each CLI keeps its login/session state, and can be overridden with those environment variables.
- **Models**: Claude Code's list is fixed — `claude-fable-5-1`, `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5`. Codex's list comes from the account live, via `codex app-server`'s `model/list` RPC — there is no static fallback list.
- **Sessions**: each chat keeps one CLI session (`--resume` for Claude Code, `exec resume` for Codex) and only sends the messages the session hasn't seen yet, so the CLI can serve the rest from its own cache. Each call runs in an isolated temp working directory the CLI has no other access to.

## Switching the active provider

Picking a model when starting a new chat uses that provider/model for that chat only. To change what new chats and background work (automations, dreaming) use by default, set it as the default from the chat's model picker — this calls `PUT /v1/system/model`, which persists `llm.active_provider` and that provider's `default_model`. Both this and any add/edit/remove in Settings → Providers apply immediately: no Core restart, per [Configuration](configuration.md#what-needs-a-restart).

## Model listing

`GET /v1/models` lists every configured provider's models, grouped, each with a 20-second timeout; a provider that fails to answer is included with its error instead of being dropped from the list.

## Context window handling

`context_window(model)` reports how many tokens the server says the model takes per request; the harness uses it to size how much chat history fits (`fit_history` — the profile's own token budget, 12000 tokens by default, is used only when the window can't be determined). How it's obtained depends on the kind, and successful lookups are cached 10 minutes (failed ones, 1 minute):

| Kind | Source |
|---|---|
| `ollama_local` | `GET /api/ps` — the size the model is actually loaded with |
| `ollama_cloud` | `POST /api/show` — the model's `*.context_length` field |
| `llama_cpp` | `GET /props` — `default_generation_settings.n_ctx` |
| `lmstudio` | `GET /api/v0/models/{model}` — `loaded_context_length` or `max_context_length` |
| `openai`, `openrouter`, `openai_compatible` | `GET /models` — the model entry's `context_length`, `max_model_len` or `context_window`, if the server includes one |
| `claude_code` | Reported per call in Claude Code's own usage output (`modelUsage.contextWindow`) |
| `codex_cli` | `$CODEX_HOME/models_cache.json`, scaled by the account's `effective_context_window_percent` |

## Image (vision) model

If a chat step includes an image and the active provider has `vision_model` set, that model is used for the request instead of the chat's chosen model. If it's unset, or the model rejects the image, Mensarium retries the step without the image and posts a note in the chat suggesting a vision model be set in Settings → Providers.

## Usage and limits display

Settings → Providers shows a usage window per provider (`GET /v1/limits`, refreshed with `POST /v1/limits/refresh`); a window is flagged once its used percentage passes 75%. How each kind's usage is known:

| Kind | How |
|---|---|
| `ollama_cloud`, `ollama_local`, `llama_cpp`, `lmstudio` | Not supported — these don't expose usage/limits |
| `openai`, `openai_compatible` | Passive: known only after the provider has answered at least once, from `x-ratelimit-*` response headers |
| `openrouter` | Polled every 10 minutes via `GET /key` (credit usage), without spending quota |
| `codex_cli` | Polled every 10 minutes via `codex app-server`'s `account/rateLimits/read`, without spending quota |
| `claude_code` | Probed every 30 minutes via the Claude OAuth usage API, without spending quota, including when the subscription quota is exhausted |

## See also

- [Configuration](configuration.md) — `llm.*` keys in `core/config.yaml`, where the API key file lives
- [Core](core.md) — the setup wizard's provider step
- [Chats](chats.md) — picking a model per chat
- [Secrets](secrets.md) — how this differs from user secrets the agent uses by name
