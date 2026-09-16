# Lumina AI Studio — delivery verification, 2026-09-16

Source: `work/lumina-production-unified` at `c0640e80b9875ff0baa41b326c5ba1f4dd1542c3`. Verification branch adds only Ruff formatting corrections in two test files.

## Verified on this source tree

- Backend and launcher: `python -m pytest backend/tests launcher/tests --override-ini addopts= -q` — 668 passed, 2 skipped, 0 failed.
- Frontend: `CI=true npm test -- --watchAll=false --runInBand` — 26 suites and 137 tests passed.
- Frontend: `npm run build` — compiled successfully.
- Python lint: `python -m ruff check backend launcher --output-format concise` — passed after three formatting fixes in two tests.
- Runtime: `python scripts/lumina-smoke.py` — startup, health, protected endpoint, login and auth/me passed in a local test environment.
- Render: service `lumina-ai-studio` latest deployment `dep-daleqssdoqps73ff1va0` of source commit `c0640e8` is live. Render error-level and 5xx queries since that deploy returned no events at verification time.

## Delivery boundaries

These results do not demonstrate an authenticated production session, end-to-end generation with real provider credentials, or a complete browser walkthrough of every studio. The README explicitly describes local mock video and voice modes and provider integrations requiring credentials and production verification. A live deploy and passing automated tests alone are insufficient to certify every advertised feature as operational. The prior Sonar quality gate and issue counts in `copyable_report.md` refer to an earlier commit and were not remeasured here.

## Rollback

The formatting patch touches only import order and a trailing newline in two test files. Revert the verification commit to restore the source tree; the production branch and current Render deployment were not modified by this verification.

## Authenticated production walkthrough (same date)

- Signed in through the production login form. Image Studio submitted one `flux` generation; the job failed. Render logged Replicate HTTP 402 and `Replicate billing or quota is unavailable for this request.` The UI advertised `flux — ready` because credentials were configured; that status did not imply usable billing.
- Documents: created a test document and saved content successfully. PDF export returned HTTP 200. Reopening the library exposed a title regression: the typed title had not persisted and the item appeared as `Untitled Document`. The production verification branch now combines title and content in one versioned save to prevent competing updates; this patch has not been deployed.
- LUMINA Mind: Groq answered the short test prompt and persisted the conversation. It listed the test document as `Untitled Document`, consistent with the title regression.
- Voice Studio: generated an MP3 from short Greek text; the browser audio element reported loaded media.
- Code Builder V2: planning failed before creating a plan because the configured default Groq code model `llama-3.3-70b-versatile` returned model_not_found for this account. The verification branch changes the fallback to the shared `LUMINA_GROQ_MODEL` or `openai/gpt-oss-120b`, which is already used by the working Mind flow. Production retest awaits deployment.
- Video Studio: existing jobs include queued and failed records. A text-to-video UI attempt did not result in a new server generation request. Automatic action review blocked a further attempt because it could create another production compute job. No fresh video result is certified.

The production branch and Render service remain at `c0640e8`; these findings demonstrate that the current release is not ready for an unqualified completion claim. Replicate billing/quota cannot be fixed in source code. Any change to paid provider billing requires account-side action by the owner.

## Rollback for the new fixes

The Document Studio patch changes only its save transaction; revert its commit to restore previous title-on-blur behavior. The Groq model defaults can be overridden with `GROQ_CODE_MODEL` and `GROQ_DOCUMENT_MODEL`; reverting their source change restores prior defaults. No database migration is involved.

## Verification after the proposed fixes

- Backend and launcher: 670 passed, 2 skipped, 0 failed (`python -m pytest backend/tests launcher/tests --override-ini addopts= -q --disable-warnings`).
- Frontend: 26 suites and 137 tests passed; production build compiled successfully.
- Ruff: all backend and launcher checks passed.
- These are branch-level results. An authenticated production regression check of document rename and Code Builder planning is required after deployment.
