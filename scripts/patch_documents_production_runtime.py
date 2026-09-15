from pathlib import Path


def replace_once(path: str, old: str, new: str) -> bool:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"Patch anchor missing in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


changed = False
changed |= replace_once(
    "frontend/src/components/documentstudio/DocumentAIAssistantPanel.jsx",
    '<option value="">Automatic (Ollama)</option>',
    '<option value="groq">Automatic (Groq)</option>',
)
changed |= replace_once(
    "frontend/src/components/documentstudio/DocumentAIAssistantPanel.jsx",
    "const [provider, setProvider] = useState('');",
    "const [provider, setProvider] = useState('groq');",
)

old_dictation = """    let committed = message.trim();
    recognition.onstart = () => { setListening(true); setError(''); };
    recognition.onend = () => setListening(false);
    recognition.onerror = (event) => {
      setListening(false);
      if (event.error !== 'aborted') setError(`Η φωνητική πληκτρολόγηση σταμάτησε: ${event.error || 'άγνωστο σφάλμα'}.`);
    };
    recognition.onresult = (event) => {
      let interim = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const transcript = event.results[index][0]?.transcript || '';
        if (event.results[index].isFinal) committed = `${committed} ${transcript}`.trim();
        else interim += transcript;
      }
      setMessage(`${committed}${interim ? ` ${interim}` : ''}`.trim());
    };"""

new_dictation = """    const dictationBase = message.trim();
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

changed |= replace_once("frontend/src/pages/ExecutiveAdvisor.jsx", old_dictation, new_dictation)
print("patched" if changed else "already-patched")
