# LUMINA AI Windows Desktop Launcher

## Overview

The LUMINA AI Windows desktop launcher provides a one-click experience for starting the entire LUMINA AI Operating System. The user double-clicks the **LUMINA AI** desktop shortcut, and the launcher automatically:

1. Detects whether Docker Desktop is running
2. Starts Docker Desktop if required
3. Starts or verifies the required Docker services (Redis and Qdrant)
4. Starts the LUMINA backend (uvicorn on port 8000)
5. Starts the LUMINA frontend (npm start on port 3000)
6. Waits until backend and frontend health checks confirm readiness
7. Opens the LUMINA application in the default browser
8. Displays a clear error message if any service fails

## Architecture

```
Desktop Shortcut (.lnk)
    ↓
VBS Wrapper (hidden, no terminal)
    ↓
PowerShell Launcher (LuminaLauncher.ps1)
    ├── Docker Desktop detection & startup
    ├── Docker Compose services (Redis, Qdrant)
    ├── Backend startup (uvicorn)
    ├── Frontend startup (npm start)
    ├── Health check polling
    └── Browser open
```

## Files

| File | Purpose |
|------|---------|
| `launcher/windows/LuminaLauncher.ps1` | Main PowerShell launcher script with all startup, detection, and safety logic |
| `launcher/windows/Start_LUMINA_AI.vbs` | Hidden VBS wrapper that runs the PowerShell launcher with `-Action start` |
| `launcher/windows/Close_LUMINA_AI.vbs` | Hidden VBS wrapper that runs the PowerShell launcher with `-Action stop` |
| `launcher/windows/Install_LUMINA_Shortcuts.vbs` | One-time script that creates the desktop shortcuts |
| `launcher/tests/test_launcher_windows.py` | Automated tests validating launcher structure and logic |

## Installation

### One-time setup

Double-click `launcher/windows/Install_LUMINA_Shortcuts.vbs` to create two desktop shortcuts:

- **LUMINA AI** — Starts the application
- **Close LUMINA** — Stops the application

### Manual installation

If you prefer to create shortcuts manually:

1. Right-click on the desktop → New → Shortcut
2. Location: `wscript.exe "C:\path\to\lumina-ai-studio\launcher\windows\Start_LUMINA_AI.vbs"`
3. Name: `LUMINA AI`
4. Right-click the shortcut → Properties → Set Working Directory to the repo root

## Usage

### Starting LUMINA

Double-click the **LUMINA AI** desktop shortcut. The launcher will:

1. Check if backend and frontend are already running (skip if yes, just open browser)
2. Check if Docker Desktop is running (start it if not)
3. Start Redis and Qdrant containers via `docker compose up -d`
4. Start the backend with `python -m uvicorn server:app --host 127.0.0.1 --port 8000`
5. Start the frontend with `npm start` (port 3000)
6. Wait for health checks to pass (up to 180 seconds)
7. Open `http://localhost:3000/` in the default browser

### Stopping LUMINA

Double-click the **Close LUMINA** desktop shortcut. This will:

- Stop the frontend (node process on port 3000)
- Stop the backend (python process on port 8000)
- **NOT** stop Docker Desktop
- **NOT** stop Redis or Qdrant containers
- **NOT** stop unrelated Node or Python processes

### Checking status

Run from PowerShell:

```powershell
powershell -File launcher\windows\LuminaLauncher.ps1 -Action status
```

## Duplicate-Process Protection

Before starting anything, the launcher verifies:

- Backend port 8000 is not already serving
- Frontend port 3000 is not already serving
- If both are already running, it simply opens the browser

If LUMINA is already running, double-clicking the shortcut again will **not** create duplicate processes.

## Logging

All launcher activity is logged to:

```
.lumina-runtime/logs/launcher.log
```

Additional logs:

| Log file | Content |
|----------|---------|
| `backend.log` | Backend stdout/stderr |
| `frontend.log` | Frontend stdout/stderr |
| `docker_compose_up.log` | Docker compose up output |
| `docker_compose_up_err.log` | Docker compose up errors |

## Configuration

The PowerShell launcher accepts parameters that can be overridden:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-Action` | `start` | `start`, `stop`, or `status` |
| `-BackendPort` | `8000` | Backend port |
| `-FrontendPort` | `3000` | Frontend port |
| `-BackendHost` | `127.0.0.1` | Backend host |
| `-FrontendHost` | `localhost` | Frontend host |
| `-StartupTimeoutSeconds` | `180` | Max wait time for services |
| `-PollIntervalSeconds` | `2` | Health check poll interval |
| `-DockerComposeFile` | `docker-compose.dev.yml` | Docker compose file name |

Example:

```powershell
powershell -File launcher\windows\LuminaLauncher.ps1 -Action start -BackendPort 8001 -FrontendPort 3001
```

## Security

- **Execution Policy**: The VBS wrappers use `-ExecutionPolicy Bypass` which is scoped to the PowerShell process only. It does **not** change the system-wide execution policy.
- **No Profile**: `-NoProfile` is used to avoid loading user PowerShell profiles, ensuring a clean and fast startup.
- **No Hardcoded Paths**: The launcher dynamically derives the repository root from `$PSScriptRoot`.
- **Safe Path Quoting**: All paths with spaces are properly quoted in the VBS wrappers.

## Testing

Run the launcher tests:

```bash
cd c:\Users\User\Desktop\lumina-ai-studio
python -m pytest launcher/tests/test_launcher_windows.py -v
```

## Troubleshooting

### "LUMINA AI failed to start"

1. Check `.lumina-runtime/logs/launcher.log` for the error
2. Check `.lumina-runtime/logs/backend.log` for backend errors
3. Check `.lumina-runtime/logs/frontend.log` for frontend errors
4. Ensure Python 3.11+ is on PATH
5. Ensure Node.js and npm are on PATH
6. Ensure Docker Desktop is installed (optional but recommended)

### Port already in use

If port 3000 or 8000 is occupied by a non-LUMINA process:

1. Use `Close LUMINA` to stop LUMINA processes
2. Identify and stop the conflicting process
3. Or use custom ports: `-BackendPort 8001 -FrontendPort 3001`

### Docker Desktop won't start

The launcher will continue without Docker if Docker Desktop cannot be started. Redis and Qdrant will be unavailable, but the backend may still start in degraded mode.

## Windows Restart Resilience

The launcher works after a Windows restart because:

- It does not rely on any persistent state files
- It re-detects all services from scratch
- It starts Docker Desktop if it's not running
- The desktop shortcuts persist across restarts
- No manual intervention is required