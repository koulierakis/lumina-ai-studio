from pathlib import Path

ROOT = Path.cwd()
OLLAMA = ROOT / "backend" / "code_builder" / "ollama_service.py"
UI = ROOT / "frontend" / "src" / "pages" / "CodeBuilder.jsx"

# 1) Harden structured parsing for small local models that may emit an extra
# leading/trailing brace or more than one JSON value despite schema mode.
text = OLLAMA.read_text(encoding="utf-8")
needle = '''            try:\n                parsed = json.loads(extracted)\n            except json.JSONDecodeError as second_error:\n                raise OllamaStructuredOutputError(\n                    "Ollama returned malformed structured JSON: "\n                    f"{second_error.msg} at line "\n                    f"{second_error.lineno}, column "\n                    f"{second_error.colno}."\n                ) from second_error\n'''
replacement = '''            try:\n                parsed = json.loads(extracted)\n            except json.JSONDecodeError as second_error:\n                # Some small local models can prepend one malformed delimiter\n                # before an otherwise valid schema-constrained JSON value.\n                # Recover only a value that the standard decoder can parse;\n                # Pydantic/schema validation still runs immediately afterwards.\n                decoder = json.JSONDecoder()\n                recovered = None\n                for candidate_index, candidate_character in enumerate(normalized_content):\n                    if candidate_character not in "{[":\n                        continue\n                    try:\n                        candidate_value, _ = decoder.raw_decode(\n                            normalized_content[candidate_index:]\n                        )\n                    except json.JSONDecodeError:\n                        continue\n                    if isinstance(candidate_value, (dict, list)):\n                        recovered = candidate_value\n                        break\n                if recovered is None:\n                    raise OllamaStructuredOutputError(\n                        "Ollama returned malformed structured JSON: "\n                        f"{second_error.msg} at line "\n                        f"{second_error.lineno}, column "\n                        f"{second_error.colno}."\n                    ) from second_error\n                parsed = recovered\n'''
if needle not in text:
    if "candidate_index, candidate_character" not in text:
        raise SystemExit("structured parser anchor not found; refusing unsafe patch")
else:
    text = text.replace(needle, replacement, 1)
OLLAMA.write_text(text, encoding="utf-8")

# 2) Add a visible stage/progress rail driven by the existing task phase.
ui = UI.read_text(encoding="utf-8")
anchor = "const TERMINAL_PHASES = new Set(['completed', 'failed', 'cancelled', 'timed_out', 'rolled_back', 'rollback_failed']);\n"
progress_code = '''\nconst PIPELINE_STAGES = [\n  ['queued', 'Queued'],\n  ['analyzing', 'Analyzing'],\n  ['planning', 'Planning'],\n  ['validating', 'Validating'],\n  ['awaiting_approval', 'Awaiting approval'],\n  ['approved', 'Approved'],\n  ['executing', 'Applying'],\n  ['verifying', 'Verifying'],\n  ['completed', 'Completed'],\n];\n\nfunction PipelineProgress({ task }) {\n  const phase = task?.phase || 'queued';\n  const aliases = { preparing: 'planning', reviewing: 'validating', building: 'verifying' };\n  const normalized = aliases[phase] || phase;\n  const terminalFailure = ['failed', 'cancelled', 'timed_out', 'rollback_failed'].includes(normalized);\n  let activeIndex = PIPELINE_STAGES.findIndex(([key]) => key === normalized);\n  if (activeIndex < 0) {\n    const events = Array.isArray(task?.events) ? task.events : [];\n    const lastKnown = [...events].reverse().map((event) => aliases[event?.phase] || event?.phase).find((value) => PIPELINE_STAGES.some(([key]) => key === value));\n    activeIndex = Math.max(0, PIPELINE_STAGES.findIndex(([key]) => key === lastKnown));\n  }\n  const percent = terminalFailure ? Math.max(5, Math.round((activeIndex / (PIPELINE_STAGES.length - 1)) * 100)) : Math.round((activeIndex / (PIPELINE_STAGES.length - 1)) * 100);\n  return (\n    <section className="mt-5 rounded-xl border border-white/[0.08] bg-white/[0.02] p-4" data-testid="code-builder-progress">\n      <div className="flex items-center justify-between gap-3"><span className="text-[10px] uppercase tracking-[0.18em] text-white/45">Execution progress</span><span className={`text-xs ${terminalFailure ? 'text-red-200' : 'text-gold'}`}>{terminalFailure ? `Stopped at ${phaseLabel(normalized)}` : `${percent}%`}</span></div>\n      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[0.07]"><div className={`h-full rounded-full transition-all duration-500 ${terminalFailure ? 'bg-red-300/70' : 'bg-gold'}`} style={{ width: `${percent}%` }} /></div>\n      <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-9">{PIPELINE_STAGES.map(([key, label], index) => { const done = index < activeIndex || normalized === 'completed'; const active = index === activeIndex && normalized !== 'completed'; return <div key={key} className={`rounded-md border px-2 py-2 text-center text-[9px] uppercase tracking-[0.08em] ${done ? 'border-emerald-400/20 text-emerald-200/80' : active ? 'border-gold/30 text-gold' : 'border-white/[0.06] text-white/25'}`}>{label}</div>; })}</div>\n    </section>\n  );\n}\n'''
if "function PipelineProgress" not in ui:
    if anchor not in ui:
        raise SystemExit("UI constants anchor not found; refusing unsafe patch")
    ui = ui.replace(anchor, anchor + progress_code, 1)

render_anchor = '''        </header>\n\n        <section className="mt-8 rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">'''
render_replacement = '''        </header>\n\n        {task && <PipelineProgress task={task} />}\n\n        <section className="mt-8 rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">'''
if "<PipelineProgress task={task}" not in ui:
    if render_anchor not in ui:
        raise SystemExit("UI render anchor not found; refusing unsafe patch")
    ui = ui.replace(render_anchor, render_replacement, 1)
UI.write_text(ui, encoding="utf-8")

print("LUMINA Code Builder final runtime patch applied")
