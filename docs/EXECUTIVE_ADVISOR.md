# LUMINA Executive Advisor

The Executive Advisor is the single advisory intelligence surface for LUMINA. It reuses the existing AI runtime and does not create a parallel runtime subsystem.

## Modes

- Auto: routes each request to the most relevant executive discipline.
- Board: evaluates the request across CEO, CFO, CMO, strategy, investment, operations, risk/compliance, and mentor perspectives and returns one unified recommendation.
- CEO / CFO / CMO / Strategy / Investment / Operations / Risk / Mentor: explicit role selection.
- Deep reasoning: requests a higher deliberation level from the selected provider.

## Providers

### Local (default)

Uses the existing local Ollama client already used by LUMINA. The advisor model is selected in this order:

1. `LUMINA_ADVISOR_MODEL`
2. LUMINA `preferred_ollama_model`
3. `qwen2.5:7b` fallback identifier

No cloud credential is required for Local mode.

### OpenAI cloud reasoning (optional)

Set `OPENAI_API_KEY` only in the backend environment. Never commit an API key to the repository.

Optional model override:

`LUMINA_OPENAI_MODEL=<model-id>`

If unset, the advisor uses its configured default model identifier.

OpenAI API usage is billed separately from any ChatGPT subscription.

### Web Research (optional)

Web Research uses the OpenAI Responses API web-search tool and therefore requires `OPENAI_API_KEY`. Source URLs returned by the provider are persisted with the assistant message and displayed in the Advisor UI.

## Document grounding

The Advisor reuses the existing Document Studio library instead of creating an independent upload or extraction system.

- Existing Document Studio documents can be attached directly to an advisory session.
- New PDF, DOCX, TXT, Markdown, HTML, PNG, JPEG, or WebP reference files are imported through the existing `documentApi.importFile` / `/api/documents/import` path.
- Document Studio remains the source of truth for the uploaded document and extracted text.
- Up to three documents can be grounded into a request at once.
- The current implementation sends a bounded text excerpt from each selected document as structured model context.
- Selected document IDs are stored locally per Advisor session so reopening the session can restore the same working references.

## Persistent context

Advisor state is owner-scoped and stored locally under:

`.lumina/advisor/state.json`

It contains:

- conversation sessions and message history;
- manually saved memories;
- the editable Advisor profile.

The user can delete sessions and individual memories. Sensitive information should only be added when the user intentionally wants it stored locally.

## API surface

The advisor extends the already-mounted `/api/runtime` router:

- `GET /api/runtime/advisor/status`
- `POST /api/runtime/advisor/ask`
- `GET /api/runtime/advisor/sessions`
- `GET /api/runtime/advisor/sessions/{session_id}`
- `DELETE /api/runtime/advisor/sessions/{session_id}`
- `GET /api/runtime/advisor/memory`
- `POST /api/runtime/advisor/memory`
- `DELETE /api/runtime/advisor/memory/{memory_id}`
- `GET /api/runtime/advisor/profile`
- `PUT /api/runtime/advisor/profile`

Document ingestion continues to use the existing Document Studio API rather than adding Advisor-specific upload endpoints.

## Safety and factual integrity

The system prompt requires the advisor to distinguish evidence from inference and not invent figures, legal status, source documents, or completed actions. High-stakes financial, legal, tax, compliance, medical, and investment conclusions must surface material uncertainty and professional-verification needs.

## Current capability boundary

The current implementation provides persistent advisory conversations, memory/profile context, role routing, Board Mode, local deep reasoning, optional OpenAI reasoning, optional web research with sources, and grounded analysis of Document Studio files.

It does not yet provide direct Gmail/Calendar actions, scheduled automations, arbitrary local code execution, or autonomous changes to external services. Those capabilities should be added as explicit tool integrations to this same advisor layer rather than as separate advisor agents.
