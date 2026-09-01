from __future__ import annotations

from pathlib import Path

PAGE = Path("frontend/src/pages/CodeBuilder.jsx")
TEST = Path("frontend/src/pages/CodeBuilder.test.js")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            print(f"{label}: already applied")
            return text
        raise RuntimeError(f"{label}: expected source block was not found")
    if count != 1:
        raise RuntimeError(f"{label}: expected one source block, found {count}")
    print(f"{label}: applying")
    return text.replace(old, new, 1)


def update_page(text: str) -> str:
    text = replace_once(
        text,
        "const DRAFT_STORAGE_KEY = 'lumina_code_builder_instruction';\n",
        "const DRAFT_STORAGE_KEY = 'lumina_code_builder_instruction';\nconst ENGINE_STORAGE_KEY = 'lumina_code_builder_engine';\n",
        "engine storage key",
    )
    text = replace_once(
        text,
        "  const [modelStatus, setModelStatus] = useState('unknown');\n  const recognitionRef = useRef(null);\n",
        "  const [modelStatus, setModelStatus] = useState('unknown');\n  const [engineStatus, setEngineStatus] = useState({ default: 'native', engines: [{ name: 'native', available: true, experimental: false, safe_mode: true }], openhands_ready: false });\n  const [codingEngine, setCodingEngine] = useState(() => (typeof window !== 'undefined' ? window.localStorage.getItem(ENGINE_STORAGE_KEY) || 'native' : 'native'));\n  const recognitionRef = useRef(null);\n",
        "engine state",
    )
    text = replace_once(
        text,
        "  useEffect(() => {\n    refreshModelStatus();\n  }, [refreshModelStatus]);\n\n  const toggleVoice = () => {\n",
        "  useEffect(() => {\n    refreshModelStatus();\n  }, [refreshModelStatus]);\n\n  const refreshEngineStatus = useCallback(async () => {\n    try {\n      const status = await apiGet('/code-builder/engines', { retry: false });\n      const engines = Array.isArray(status?.engines) && status.engines.length ? status.engines : [{ name: 'native', available: true, experimental: false, safe_mode: true }];\n      const normalized = { ...status, default: status?.default || 'native', engines };\n      setEngineStatus(normalized);\n      setCodingEngine((current) => {\n        const option = engines.find((item) => item.name === current);\n        return current === 'native' || option?.available ? current : 'native';\n      });\n    } catch {\n      setEngineStatus({ default: 'native', engines: [{ name: 'native', available: true, experimental: false, safe_mode: true }], openhands_ready: false });\n      setCodingEngine('native');\n    }\n  }, []);\n\n  useEffect(() => {\n    refreshEngineStatus();\n  }, [refreshEngineStatus]);\n\n  useEffect(() => {\n    window.localStorage.setItem(ENGINE_STORAGE_KEY, codingEngine);\n  }, [codingEngine]);\n\n  const toggleVoice = () => {\n",
        "engine status fetch",
    )
    text = replace_once(
        text,
        "        rollback_policy: 'on_any_failure',\n      });\n",
        "        rollback_policy: 'on_any_failure',\n        metadata: { coding_engine: codingEngine },\n      });\n",
        "engine task metadata",
    )
    text = replace_once(
        text,
        "          {voiceMessage && <p data-testid=\"code-builder-voice-status\" className=\"mt-2 text-sm text-white/55\">{voiceMessage}</p>}\n          <div className=\"mt-4 flex flex-wrap items-center justify-between gap-3\">\n",
        "          {voiceMessage && <p data-testid=\"code-builder-voice-status\" className=\"mt-2 text-sm text-white/55\">{voiceMessage}</p>}\n          <div className=\"mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-white/[0.07] bg-black/15 px-4 py-3\" data-testid=\"code-builder-engine-panel\">\n            <label className=\"flex items-center gap-3 text-sm text-white/65\" htmlFor=\"code-builder-engine\">\n              <span className=\"font-semibold text-white/80\">Coding engine</span>\n              <select id=\"code-builder-engine\" data-testid=\"code-builder-engine\" value={codingEngine} onChange={(event) => setCodingEngine(event.target.value)} disabled={busy} className=\"rounded-md border border-white/10 bg-white/[0.05] px-3 py-2 text-sm text-white outline-none focus:border-gold/40\">\n                {engineStatus.engines.map((engine) => <option key={engine.name} value={engine.name} disabled={!engine.available}>{engine.name === 'native' ? 'Native' : 'OpenHands'}{engine.experimental ? ' · experimental' : ''}{!engine.available ? ' · unavailable' : ''}</option>)}\n              </select>\n            </label>\n            <span className=\"text-xs text-white/40\">{codingEngine === 'openhands' ? (engineStatus.openhands_ready ? 'OpenHands runtime validated.' : 'OpenHands proposals still require approval and runtime validation.') : 'Native remains the default Code Builder engine.'}</span>\n          </div>\n          <div className=\"mt-4 flex flex-wrap items-center justify-between gap-3\">\n",
        "engine selector UI",
    )
    return text


def update_test(text: str) -> str:
    text = replace_once(
        text,
        "    expect(page).toContain('No production writes before explicit approval.');\n",
        "    expect(page).toContain('No production writes before explicit approval.');\n    expect(page).toContain(\"apiGet('/code-builder/engines'\");\n    expect(page).toContain('data-testid=\"code-builder-engine\"');\n    expect(page).toContain(\"metadata: { coding_engine: codingEngine }\");\n",
        "static engine assertions",
    )
    anchor = "  test('handles microphone denial without breaking the composer', async () => {\n"
    test_block = '''  test('submits the explicitly selected OpenHands engine in task metadata', async () => {\n    apiGet.mockImplementation((url) => {\n      if (url === '/code-builder/engines') return Promise.resolve({\n        default: 'native',\n        openhands_ready: false,\n        engines: [\n          { name: 'native', available: true, experimental: false, safe_mode: true },\n          { name: 'openhands', available: true, experimental: true, safe_mode: true },\n        ],\n      });\n      if (url === '/code-builder/model-status') return Promise.resolve({ status: 'ready' });\n      return Promise.resolve({ items: [] });\n    });\n    await renderComposer();\n    const engine = container.querySelector('[data-testid="code-builder-engine"]');\n    const input = container.querySelector('[data-testid="code-builder-instruction"]');\n    await act(async () => {\n      engine.value = 'openhands';\n      engine.dispatchEvent(new Event('change', { bubbles: true }));\n      setTextareaValue(input, 'Prepare a safe OpenHands proposal');\n    });\n    await act(async () => container.querySelector('[data-testid="code-builder-create"]').click());\n    expect(apiPost).toHaveBeenCalledWith('/code-builder/tasks', expect.objectContaining({\n      instruction: 'Prepare a safe OpenHands proposal',\n      metadata: { coding_engine: 'openhands' },\n      require_approval: true,\n    }));\n  });\n\n  test('falls back to Native when OpenHands is unavailable', async () => {\n    window.localStorage.setItem('lumina_code_builder_engine', 'openhands');\n    apiGet.mockImplementation((url) => {\n      if (url === '/code-builder/engines') return Promise.resolve({\n        default: 'native',\n        openhands_ready: false,\n        engines: [\n          { name: 'native', available: true, experimental: false, safe_mode: true },\n          { name: 'openhands', available: false, experimental: true, safe_mode: true },\n        ],\n      });\n      return Promise.resolve({ items: [] });\n    });\n    await renderComposer();\n    expect(container.querySelector('[data-testid="code-builder-engine"]').value).toBe('native');\n  });\n\n'''
    return replace_once(text, anchor, test_block + anchor, "engine interaction tests")


def main() -> None:
    PAGE.write_text(update_page(PAGE.read_text(encoding="utf-8")), encoding="utf-8")
    TEST.write_text(update_test(TEST.read_text(encoding="utf-8")), encoding="utf-8")
    print("Code Builder engine selector migration completed.")


if __name__ == "__main__":
    main()
