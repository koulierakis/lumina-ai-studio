# Lumina AI Desktop Studio — Implementation Status

## Completed in this revision
- Repository normalized to the single `LUMINA/` root.
- Authoritative backend, frontend, tests, reports, and documentation consolidated.
- Ten newer root-frontend fixes preserved over the complete nested baseline.
- Empty Git metadata replaced with a valid repository.
- Environment examples and production-grade ignore rules added.
- Windows-safe default media storage now resolves beside `backend/storage.py`.
- Authentication hardening: bcrypt owner-password hashes, constant-time legacy
  comparison, and per-client brute-force throttling with `Retry-After`.
- Provider-neutral contracts and capability metadata.
- Provider registry and manager.
- Manual provider selection.
- Automatic ordered fallback.
- Retry with exponential backoff.
- Normalized provider errors for authentication, quota, rate limits, timeouts and availability.
- Runtime provider status, capabilities and usage statistics endpoint.
- Gemini identity-preserving generation/edit connector retained and hardened.
- Removed legacy `EMERGENT_LLM_KEY` credential fallback.
- OpenAI Images generation connector.
- Stable Diffusion-compatible REST connector.
- Identity-capability filtering during fallback.
- Duplicate Identity Packs route removed.
- Frontend provider selector and live provider readiness status.
- Existing frontend lint/build defect in Gallery fixed.
- Unit tests for fallback and identity capability selection.

## Validation
- Python syntax compilation: passed.
- Backend unit suite: 19 passed.
- Live backend integration suite with local mock provider: 58 passed, 1 skipped.
- Frontend locked dependency validation (`npm ci`, `npm ls`): passed.
- React optimized production build: passed.

## Repository root
Run all commands from the directory containing `backend/`, `frontend/`,
`tests/`, and this file. The former `lumina-ai-studio-main/` duplicate no
longer exists.

## Normalization fixes
- Corrected the Windows/local storage default and the `reference` to
  `references/` directory mapping exposed by the live integration suite.
- Aligned React, React DOM, date-fns, and ESLint with supported peer ranges;
  regenerated `package-lock.json`.
- Removed hardcoded test credentials. Live suites now read local environment
  configuration and support `LUMINA_TEST_OWNER_PASSWORD`.

## Provider configuration
Use backend environment variables:
- `IMAGE_PROVIDER=gemini`
- `IMAGE_PROVIDER_FALLBACKS=gemini,openai,stable-diffusion`
- `PROVIDER_RETRIES=2`
- `PROVIDER_TIMEOUT_SECONDS=120`
- `GEMINI_API_KEY=...`
- `OPENAI_API_KEY=...`
- `STABLE_DIFFUSION_URL=http://127.0.0.1:7860`
- `STABLE_DIFFUSION_API_KEY=...` (optional)
