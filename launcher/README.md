# LUMINA Runtime Manager

Local start / stop / status tooling for LUMINA. It starts the backend, frontend, and (when needed) Ollama, waits until services are ready, then opens the dashboard.

## Requirements

- Python 3.11+
- Node.js + npm
- Ollama (optional but required for Local AI / Code Creator)
- Model: `qwen2.5-coder:7b` (or the model set in runtime settings)

No paid cloud services are required.

## Commands

Run from the repository (any cwd works; the launcher finds the repo root):

```bat
python launcher\lumina_launcher.py start
python launcher\lumina_launcher.py stop
python launcher\lumina_launcher.py restart
python launcher\lumina_launcher.py status
python launcher\lumina_launcher.py doctor
```

| Command | Behavior |
|---------|----------|
| `start` | Starts Ollama if needed, then backend and frontend. Opens the dashboard after readiness checks. |
| `stop` | Stops **only** LUMINA-owned processes recorded in runtime state. |
| `restart` | Safe stop, then start. |
| `status` | Shows backend / frontend / Ollama readiness and owned PIDs. |
| `doctor` | Checks Python, Node, npm, Ollama, model, paths, and ports. |
| `set-keys` | Interactively stores API keys in `backend/.env` (hidden input, never printed). |

Meaningful exit codes: `0` success, `2` already running, `3` missing dependency / doctor failure, `4` port in use, `5` startup timeout, `6` shutdown failure.

## Paths

| Item | Location |
|------|----------|
| Runtime state / config / logs | `<repo>\.lumina-runtime\` |
| Config | `<repo>\.lumina-runtime\config.json` |
| State / PIDs | `<repo>\.lumina-runtime\runtime_state.json` |
| Logs | `<repo>\.lumina-runtime\logs\` (`runtime.log`, `backend.log`, `frontend.log`, `ollama.log`) |

## Windows double-click launchers

1. Double-click `launcher\windows\Create_Desktop_Shortcuts.vbs` once.
2. Use the Desktop shortcuts **Start LUMINA** and **Stop LUMINA**.

Or double-click:

- `launcher\windows\Start_LUMINA.vbs`
- `launcher\windows\Stop_LUMINA.vbs`

Normal startup hides the console. Failures show a clear message box and point at the log folder.

These scripts do **not** replace any older temporary launcher until you choose to switch.

## Configuration

Edit Settings → **Runtime manager** in the app, or edit `.lumina-runtime/config.json`.

Supported keys (validated; invalid files fall back to defaults):

- `dashboard_auto_open`
- `preferred_ollama_model`
- `backend_port` / `frontend_port`
- `startup_timeout_seconds`
- `automatic_ollama_startup`
- `logging_level`
- `remote_access` (see below)
- `backend_host` / `frontend_host` (advanced; set automatically by `remote_access`)

Port changes apply on the next `start` / restart.

## Opening LUMINA from your phone or tablet

Set `remote_access` to `true` (Settings → **Runtime manager**, or `"remote_access": true` in `.lumina-runtime/config.json`). The launcher then:

- binds the backend and frontend to `0.0.0.0` so other devices on the network can reach them;
- serves the frontend from the same origin so the phone calls the backend through the web server (`REACT_APP_BACKEND_URL` is left empty) instead of trying its own `127.0.0.1`;
- prints the reachable address, so you do not have to hunt for an IP:

```text
Dashboard: http://127.0.0.1:3000/
Phone / tablet: http://192.168.1.20:3000/ (same private network or Tailscale)
```

`status` reports the same address as `remote_url`. If no private address can be detected, the launcher says so and points you to a VPN such as Tailscale.

Keep this on a trusted private network. LUMINA does not expose itself to the public internet or configure a public hostname; do not port-forward `0.0.0.0`.

## Adding API keys

Cloud studios (Documents/Mind, images, video, voice) read their keys from
`backend/.env`, which is never committed. The launcher can fill them in for you
with hidden input, so keys never enter your shell history or any log:

```bat
python launcher\lumina_launcher.py set-keys
```

Pick the providers by number (for example `1,2`), or `all`, then paste each key
at the hidden prompt. Skip a key with Enter. Restart LUMINA afterwards.

The catalog maps providers to variables: `GROQ_API_KEY` (Documents AI + Mind),
`GEMINI_API_KEY` (images), `OPENAI_API_KEY`, `CLOUDFLARE_API_TOKEN` +
`CLOUDFLARE_ACCOUNT_ID`, `REPLICATE_API_TOKEN`, `HF_TOKEN`, `LUMA_API_KEY`,
`ELEVENLABS_API_KEY`, and `HEYGEN_API_KEY`. You can also edit `backend/.env`
directly; see `backend/.env.example` for every supported variable. Local
providers (`edge-tts`, `mock`, `Ollama`) need no key.

## Troubleshooting

| Symptom | What to do |
|---------|------------|
| Port already in use | `status` / `doctor`, stop the foreign process, or change ports in Settings. |
| Ollama missing | Install Ollama and ensure `ollama` is on PATH. |
| Model missing | `ollama pull qwen2.5-coder:7b` |
| Frontend never ready | Check `.lumina-runtime\logs\frontend.log` and that `npm` works in `frontend\`. |
| Stale lock / PIDs | `stop` clears owned state; doctor/start also cleans dead PIDs. |
| Already running | `status`, open http://localhost:3000, or `stop` then `start`. |

Shutdown never uses `taskkill /F /IM python.exe` or `taskkill /F /IM node.exe`. Only PIDs owned by LUMINA are targeted.

## Optional PyInstaller build

A sample spec is provided at `launcher/lumina_launcher.spec`. PyInstaller is **not** required and is not a project dependency.

```bat
pip install pyinstaller
pyinstaller launcher\lumina_launcher.spec
```
