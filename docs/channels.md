# Channels: Telegram

A channel lets you talk to the agent from a messenger instead of the web UI. Mensarium currently supports one channel, Telegram, implemented as a bot that long-polls the Telegram Bot API — no inbound port or public URL is needed.

## Creating a bot with @BotFather

In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the prompts. BotFather gives you a token that looks like `123456789:AbCdEf...`.

## Connecting in Settings → Channels

Open **Settings → Channels → Telegram**, paste the token into the "Bot token" field and connect. Core validates the token against Telegram's `getMe` before saving it; the token is written to a Core secret (`channel-telegram-token`) and never leaves the Core server. Connecting also clears any Telegram webhook and registers the bot's command menu.

Once configured, the panel shows the bot's connection state (`Connecting…`, `Waiting for the owner`, `Connected`, `Error`), and lets you:

- toggle the channel on/off,
- pick which device the bot works on ("First available device" or a specific one),
- pick the access mode for tasks started from Telegram,
- see and open the bot's current chat,
- replace the token (for a different bot; this resets the owner binding),
- disconnect (deletes the token and the owner binding from Core; chats already started from Telegram stay in the sidebar).

## Owner binding

The bot answers only one Telegram account: **the first account that sends it any message** after it is connected (or after an owner unbind). That account's numeric Telegram user id is recorded as the owner; every other account's messages are silently ignored. Unbind the owner from Settings → Channels — the next account to write becomes the new owner, and the current chat is detached from the bot.

## Which device tasks run on

A message from the bound owner continues the channel's current chat (one task at a time) or starts a new task on the configured device (or the first non-revoked device if none is configured), using the access mode set in Settings → Channels and the `coding-agent-v1` profile.

## Commands

| Command | Effect |
|---|---|
| `/new` | Ends the current chat; the next message starts a new one. |
| `/stop` | Cancels the task currently running. |
| `/status` | Shows the current chat's title, status, device and model. |
| `/whoami` | Shows your name and Telegram user id. |
| `/start`, `/help` | Shows the command list. |

While a task is running, sending another message is rejected with "Still working on the previous message. Wait for the reply or send /stop." Progress is shown as an editable "Working…" message listing the last few tool actions, replaced by the final reply when the task finishes.

## Approvals via buttons

When a tool call needs approval, the bot sends a message with the tool's display text, its risk level, the command/prompt (when applicable), any secret names involved, the tool name and device, and how many minutes remain — with inline buttons **Run once** (labeled "Run once (irreversible)" for `destructive` risk) and **Reject**. Tapping a button answers the approval the same way the web UI's "Approve once" does; the message is then edited to show the decision (Approved / Rejected / Expired, not executed).

## Formatting

The agent's markdown replies are converted to the HTML subset Telegram's Bot API accepts (bold, italic, strikethrough, inline code, code blocks, links, headings-as-bold, lists-as-bullets); tables render as preformatted blocks. Long replies are split into multiple messages (Telegram's ~4096-character limit, cut with headroom at blank lines and never inside a code fence). If Telegram rejects the HTML, the same text is resent as plain text rather than dropped. A screenshot produced during the turn is sent as a photo, with the reply text as its caption when it's short enough to fit a caption.

## Automation notifications

Automations that have `notify` enabled and a Telegram channel bound send their result, and a link to the run's chat when it's waiting for approval, through this same bot (see [docs/automations.md](automations.md)).

## Unlinking / rotating the token

- **Replace the token** (Settings → Channels → Bot → Replace) points the channel at a different bot; because the bot identity changed, the owner binding and current chat are reset.
- **Disconnect** (Settings → Channels → Bot → Disconnect) deletes the stored token and the owner binding entirely; reconnecting requires pasting a token again and re-binding an owner.
- **Unbind** (Settings → Channels → Owner → Unbind) keeps the token and bot but clears the owner and current chat, so the next person to message the bot becomes its owner.

## Polling, no inbound port

The bot uses Telegram's `getUpdates` long polling exclusively (`deleteWebhook` is called on startup to make sure no webhook is set), so Core needs no inbound port, public hostname or TLS certificate for this channel to work — only outbound HTTPS to `api.telegram.org`. A `409` error from Telegram (another process polling the same bot, e.g. a webhook or a second Core instance) is surfaced as the channel's error state with backoff and retry; a `401` (bad/revoked token) stops the channel.

See also: [docs/security.md](security.md) for how approvals, risk levels and secrets work in general.
