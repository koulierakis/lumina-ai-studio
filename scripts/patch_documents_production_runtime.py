from pathlib import Path


def replace_if_present(path: str, old: str, new: str) -> bool:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        return False
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


changed = False
changed |= replace_if_present(
    "frontend/src/components/documentstudio/DocumentAIAssistantPanel.jsx",
    '<option value="">Automatic (Ollama)</option>',
    '<option value="groq">Automatic (Groq)</option>',
)
changed |= replace_if_present(
    "frontend/src/components/documentstudio/DocumentAIAssistantPanel.jsx",
    "const [provider, setProvider] = useState('');",
    "const [provider, setProvider] = useState('groq');",
)

mind_path = Path("frontend/src/pages/ExecutiveAdvisor.jsx")
mind = mind_path.read_text(encoding="utf-8")
import_line = "import { buildAuthoritativeTranscript } from '../platform/speechTranscript';"
if import_line not in mind:
    anchor = "import { detectStudioIntent } from '../platform/studioHandoff';"
    if anchor not in mind:
        raise RuntimeError("Mind import anchor missing")
    mind = mind.replace(anchor, anchor + "\n" + import_line, 1)
    changed = True

old_dictation = """    const dictationBase = message.trim();
    recognition.onstart = () => { setListening(true); setError(''); };
    recognition.onend = () => setListening(false);
    recognition.onerror = (event) => {
      setListening(false);
      if (event.error !== 'aborted') setError(`Η φωνητική πληκτρολόγηση σταμάτησε: ${event.error || 'άγνωστο σφάλμα'}.`);
    };
    recognition.onresult = (event) => {
      let finalText = '';
      let interimText = '';
      // Web Speech can re-emit earlier results while a phrase evolves. Rebuild
      // from the authoritative result list instead of appending deltas.
      for (let index = 0; index < event.results.length; index += 1) {
        const transcript = (event.results[index][0]?.transcript || '').trim();
        if (!transcript) continue;
        if (event.results[index].isFinal) finalText = `${finalText} ${transcript}`.trim();
        else interimText = `${interimText} ${transcript}`.trim();
      }
      setMessage([dictationBase, finalText, interimText].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim());
    };"""

new_dictation = """    const dictationBase = message.trim();
    recognition.onstart = () => { setListening(true); setError(''); };
    recognition.onend = () => setListening(false);
    recognition.onerror = (event) => {
      setListening(false);
      if (event.error !== 'aborted') setError(`Η φωνητική πληκτρολόγηση σταμάτησε: ${event.error || 'άγνωστο σφάλμα'}.`);
    };
    recognition.onresult = (event) => {
      // Only finalized Web Speech segments are authoritative. Interim hypotheses
      // are intentionally excluded because Chrome/Edge can re-emit and revise
      // them, which previously produced repeated words in LUMINA Mind.
      const authoritativeTranscript = buildAuthoritativeTranscript(event.results);
      setMessage([dictationBase, authoritativeTranscript].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim());
    };"""

if old_dictation in mind:
    mind = mind.replace(old_dictation, new_dictation, 1)
    changed = True
elif "buildAuthoritativeTranscript(event.results)" not in mind:
    raise RuntimeError("Mind dictation anchor missing")

mind_path.write_text(mind, encoding="utf-8")
print("patched" if changed else "already-patched")
