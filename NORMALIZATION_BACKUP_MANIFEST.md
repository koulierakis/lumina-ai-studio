# Repository Normalization Backup Manifest

Created: 2026-07-24 (Europe/Athens)

This manifest records the pre-normalization workspace layout and the retention
decision for every top-level item. It intentionally contains no secret values.

## Authoritative inputs

- `lumina-ai-studio-main/backend/`: only complete backend source, including the
  authentication hardening (`auth.py`, `login_limiter.py`, server integration,
  and security unit tests).
- `lumina-ai-studio-main/tests/`: complete root API test suite.
- `lumina-ai-studio-main/test_reports/`: historical test reports.
- `lumina-ai-studio-main/frontend/`: complete frontend baseline.
- `frontend/`: same 100 project files as the nested frontend, with 10 newer
  valid changes. The root versions of those files are retained as an overlay:
  `AuthImage.jsx`, `Sprint3Panels.jsx`, `api.js`, `Editor.jsx`, `Gallery.jsx`,
  `Generate.jsx`, `IdentityPacks.jsx`, `VideoEditor.jsx`, `VideoProjects.jsx`,
  and `ffmpegExport.js`.
- `lumina-ai-studio-main/README.md` and
  `lumina-ai-studio-main/PROJECT_HANDOVER.md`: authoritative documentation
  because they include the authentication-hardening update.
- Root `IMPLEMENTATION_STATUS.md`: authoritative implementation status.

## Duplicate and incomplete trees

| Pre-normalization path | Finding | Normalization action |
| --- | --- | --- |
| `.git/` | Empty; no Git repository metadata | Recreate with `git init` |
| `backend/` | Empty incomplete copy | Replace with authoritative backend |
| `frontend/` | Complete active copy with 10 newer fixes | Retain as final frontend |
| `lumina-ai-studio-main/frontend/` | Complete but 10 files behind root | Remove after source comparison |
| `lumina-ai-studio-main/backend/` | Authoritative backend | Move to root |
| `lumina-ai-studio-main/tests/` | Authoritative tests | Move to root |
| `lumina-ai-studio-main/memory/` | Byte-identical to root `memory/` | Retain root copy |
| `lumina-ai-studio-main/.emergent/` | Byte-identical to root `.emergent/` | Retain root copy |
| duplicated root/nested design and test-result files | Byte-identical | Retain root copies |

## Secrets and runtime data

- `lumina-ai-studio-main/backend/.env` contains local owner, JWT, MongoDB, and
  provider configuration. It is retained at `backend/.env`, remains ignored,
  and is never copied into this manifest.
- Both frontend `.env` files contain only the local backend URL. The active root
  copy is retained and ignored.
- Generated reference and output media under backend storage is user data. It is
  retained in place with the backend and ignored by Git.
- No credential, token, or secret file is approved for Git tracking.

## Confirmed generated or temporary material

The following are reproducible or diagnostic artifacts and may be removed:

- both frontend `node_modules/` directories;
- both frontend `build/` directories;
- backend `.venv/`, `__pycache__/`, and `.pytest_cache/`;
- root `.pytest_tmp/`;
- root `*.stdout.log` and `*.stderr.log`;
- nested `project_tree.txt` (generated stale inventory).

## Preserved archive

- `LUMINA.rar` is retained under `backups/` because its contents cannot be
  proven obsolete from the filesystem audit.

## Pre-normalization content hashes

- Root and nested `design_guidelines.json`:
  `0A932261E95FFFE4AAFDC5305A69FD88E8574A959CFA6D4EE2853AC0F39FB54B`
- Root and nested `test_result.md`:
  `53F98D35AF485125F614F6E4DB9D9F58D334BC2B086ABB4E277AD13A950792A9`
- Root and nested `memory/PRD.md`:
  `D60B3C11FBB0E5F62A8F55EEB2F18E2E8CC41747EE6149DD5D26C0673394051C`
- Pre-normalization root `README.md`:
  `AF97D3D08508990F8A864EEF306CE8327B00FA6A54F1B1E5DCF5DCFDA12B8C3D`
- Authoritative nested `README.md`:
  `63657903EDF54F5C928E9710636236E8C2F5BEF701663F3172CAC7B102575713`
- Pre-normalization root `PROJECT_HANDOVER.md`:
  `480580FEF90F0CBA68600DE4C70BF202C0698EAD3608F76906210713F5FC5312`
- Authoritative nested `PROJECT_HANDOVER.md`:
  `1251C9BD1460F4E02625F621D40DC745D5074E42798032B91DCDB9046B707E16`

## Recovery source

The pre-existing `LUMINA.rar` archive is retained in `backups/`. This manifest
and the initial Git commit created after normalization provide the normalized
source inventory.
