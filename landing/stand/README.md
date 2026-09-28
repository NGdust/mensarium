# Screenshot stand for the landing page

Starts a throwaway Core with a mock model and three real clients, seeds chats, a project, automations, plugins and memory notes, captures the pages with headless Chrome and writes them to `landing/shots/`. It never touches `~/.mensarium`: everything lives in `$MENSARIUM_STAND` (`/tmp/mensarium-stand` by default).

```sh
make dev
.venv/bin/python landing/stand/stand.py up      # mock model on 8798, Core on 8799, device folders
.venv/bin/python landing/stand/stand.py seed    # clients studio/forge/pi, plugins, notes, chats, a project, automations; the last chat waits for approval
landing/stand/shots.sh                          # log in with a one-time link, capture, approve, write jpeg to landing/shots
.venv/bin/python landing/stand/stand.py down    # stops only the processes listed in the stand's pids.txt
```

The model's answers are scripted in `mock_llm.py` and picked by the task text; the files the tools read and edit are created by `seed_files.py`. Ports come from `STAND_CORE_PORT` (8799), `STAND_MODEL_PORT` (8798) and `CDP_PORT` (9223) when another stand already runs. Clients are paired with `allow_remote_update=False`, so the stand can never restart the real services on this machine.
