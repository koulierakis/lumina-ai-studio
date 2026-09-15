import { useEffect, useMemo, useRef, useState } from 'react';
import { apiPost, uploadFormData } from '../../lib/api';
import { toast } from 'sonner';

const PROMPTS = [
  'Καλησπέρα. Αυτή είναι η φυσική μου φωνή και μιλάω με τον συνηθισμένο μου ρυθμό.',
  'Σήμερα θέλω να δοκιμάσω καθαρή άρθρωση, φυσικές παύσεις και ήρεμη αναπνοή.',
  'Όταν μιλάω επαγγελματικά, ο τόνος μου είναι σταθερός, καθαρός και αποφασιστικός.',
  'Σε μια καθημερινή συζήτηση μιλάω πιο χαλαρά, χωρίς να αλλάζω τον φυσικό χαρακτήρα της φωνής μου.',
  'Μπορώ να μιλήσω πιο αργά όταν χρειάζεται, αλλά και πιο γρήγορα όταν η συζήτηση το απαιτεί.',
  'Η φωνή μου πρέπει να διατηρεί το φυσικό της ύψος, την ένταση, τις παύσεις και τον τρόπο που προφέρω τις λέξεις.',
  'Αυτό το δείγμα περιλαμβάνει αριθμούς: ένα, δύο, τρία, δέκα, είκοσι πέντε, εκατό και δύο χιλιάδες είκοσι έξι.',
  'Ολοκληρώνω την ηχογράφηση με φυσικό τόνο, χωρίς υπερβολή, χωρίς θεατρικότητα και χωρίς να πιέζω τη φωνή μου.'
];

export default function PersonalVoiceCapture({ packs = [], reload }) {
  const [packId, setPackId] = useState('');
  const [newPackName, setNewPackName] = useState('My Voice');
  const [index, setIndex] = useState(0);
  const [state, setState] = useState('idle');
  const [seconds, setSeconds] = useState(0);
  const [blob, setBlob] = useState(null);
  const [audioUrl, setAudioUrl] = useState('');
  const [consent, setConsent] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [accepted, setAccepted] = useState([]);
  const [error, setError] = useState('');

  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);

  const selectedPack = useMemo(() => packs.find(p => p.id === packId), [packs, packId]);
  const complete = index >= PROMPTS.length;

  useEffect(() => () => {
    clearInterval(timerRef.current);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
  }, [audioUrl]);

  const resetTake = () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl('');
    setBlob(null);
    setSeconds(0);
    setState('idle');
    setError('');
  };

  const createPack = async () => {
    const name = newPackName.trim();
    if (!name) return;
    try {
      const created = await apiPost('/voice/packs', {
        name,
        consent_confirmed: true,
        ownership_declaration: 'I own this voice and consent to use it.'
      });
      setPackId(created.id);
      await reload?.();
      toast.success('Voice Pack created.');
    } catch (e) {
      setError(e.message || 'Could not create Voice Pack.');
    }
  };

  const start = async () => {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError('Η εγγραφή δεν υποστηρίζεται από αυτόν τον browser.');
      return;
    }
    try {
      setError('');
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = e => { if (e.data?.size) chunksRef.current.push(e.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        streamRef.current = null;
        const nextBlob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        setBlob(nextBlob);
        setAudioUrl(URL.createObjectURL(nextBlob));
        setState('review');
        clearInterval(timerRef.current);
      };
      recorder.start();
      setSeconds(0);
      setState('recording');
      timerRef.current = setInterval(() => setSeconds(x => x + 1), 1000);
    } catch (e) {
      setError(e.name === 'NotAllowedError' ? 'Δεν δόθηκε άδεια στο μικρόφωνο.' : 'Δεν μπόρεσε να ξεκινήσει η εγγραφή.');
    }
  };

  const pauseResume = () => {
    const r = recorderRef.current;
    if (!r) return;
    if (state === 'recording') { r.pause(); setState('paused'); }
    else if (state === 'paused') { r.resume(); setState('recording'); }
  };

  const stop = () => {
    const r = recorderRef.current;
    if (r && ['recording', 'paused'].includes(state)) r.stop();
  };

  const accept = async () => {
    if (!blob || !packId || !consent) return;
    if (seconds < 3) {
      setError('Το δείγμα είναι πολύ μικρό. Ηχογράφησέ το ξανά για τουλάχιστον 3 δευτερόλεπτα.');
      return;
    }
    setUploading(true);
    setError('');
    try {
      const f = new FormData();
      const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('wav') ? 'wav' : 'webm';
      f.append('file', blob, `voice-sample-${index + 1}.${ext}`);
      const result = await uploadFormData(`/voice/packs/${packId}/samples`, f);
      setAccepted(prev => [...prev, result]);
      await reload?.();
      toast.success(`Sample ${index + 1} saved.`);
      resetTake();
      setIndex(i => i + 1);
    } catch (e) {
      setError(e.message || 'Το δείγμα δεν αποθηκεύτηκε.');
    } finally {
      setUploading(false);
    }
  };

  return <div className="grid lg:grid-cols-[1.2fr_.8fr] gap-5">
    <section className="lumina-glass rounded-xl p-5 space-y-4">
      <div>
        <p className="text-xs tracking-[.2em] uppercase text-gold">Personal Voice Capture</p>
        <h2 className="text-white text-xl mt-1">Ηχογράφηση προσωπικής φωνής</h2>
        <p className="text-sm text-white/50 mt-1">Μίλα φυσικά. Δεν χρειάζεται να προσπαθήσεις να ακούγεσαι διαφορετικά.</p>
      </div>

      {!packId && <div className="rounded border border-white/10 p-3 space-y-2">
        <p className="text-xs text-white/60">Δημιούργησε ή διάλεξε Voice Pack</p>
        <div className="flex flex-wrap gap-2">
          <input value={newPackName} onChange={e => setNewPackName(e.target.value)} className="bg-black/40 rounded p-2 text-white" />
          <button onClick={createPack} className="bg-gold text-black rounded px-3">Create My Voice Pack</button>
        </div>
        {packs.length > 0 && <select value={packId} onChange={e => setPackId(e.target.value)} className="bg-black/40 rounded p-2 text-white w-full">
          <option value="">Ή διάλεξε υπάρχον Voice Pack</option>
          {packs.map(p => <option key={p.id} value={p.id}>{p.name} · {p.sample_count || 0} samples</option>)}
        </select>}
      </div>}

      {packId && !complete && <>
        <div className="flex items-center justify-between text-xs text-white/50">
          <span>Sample {index + 1} / {PROMPTS.length}</span>
          <span>{accepted.length} αποθηκευμένα</span>
        </div>
        <div className="h-2 bg-white/10 rounded overflow-hidden"><div className="h-full bg-gold" style={{ width: `${(index / PROMPTS.length) * 100}%` }} /></div>
        <div className="rounded border border-gold/20 bg-gold/5 p-4">
          <p className="text-xs text-gold mb-2">Διάβασε φυσικά:</p>
          <p className="text-white leading-relaxed">{PROMPTS[index]}</p>
        </div>
        <div className="text-sm text-white/50">{seconds}s · {state === 'idle' ? 'έτοιμο' : state}</div>
        {error && <p className="text-red-200 text-sm">{error}</p>}
        <div className="flex flex-wrap gap-2">
          {state === 'idle' && <button onClick={start} className="bg-gold text-black rounded px-4 py-2">Start Recording</button>}
          {['recording','paused'].includes(state) && <button onClick={pauseResume} className="bg-white/10 rounded px-4 py-2">{state === 'recording' ? 'Pause' : 'Resume'}</button>}
          {['recording','paused'].includes(state) && <button onClick={stop} className="bg-white/10 rounded px-4 py-2">Stop</button>}
          {state === 'review' && <button onClick={resetTake} className="bg-white/10 rounded px-4 py-2">Retake</button>}
        </div>
        {state === 'review' && blob && <div className="rounded border border-white/10 p-3 space-y-3">
          <audio controls src={audioUrl} className="w-full" />
          <label className="text-xs text-white/60 flex gap-2 items-center"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /> Η φωνή είναι δική μου και επιτρέπω τη χρήση της.</label>
          <button disabled={!consent || uploading} onClick={accept} className="bg-gold text-black rounded px-4 py-2 disabled:opacity-40">{uploading ? 'Saving…' : 'Accept & Next'}</button>
        </div>}
      </>}

      {complete && <div className="rounded border border-green-500/20 bg-green-500/5 p-4">
        <p className="text-green-300">Η βασική συνεδρία ολοκληρώθηκε.</p>
        <p className="text-sm text-white/50 mt-1">Έχεις αποθηκεύσει {accepted.length} καθοδηγούμενα samples στο Voice Pack.</p>
      </div>}
    </section>

    <section className="lumina-glass rounded-xl p-5 space-y-3">
      <h3 className="text-white">Voice Pack</h3>
      <p className="text-sm text-white/50">{selectedPack ? selectedPack.name : 'Δεν έχει επιλεγεί ακόμη Voice Pack.'}</p>
      {selectedPack && <>
        <div className="rounded bg-black/30 p-3"><p className="text-xs text-white/40">Αποθηκευμένα samples</p><p className="text-2xl text-white">{selectedPack.sample_count || 0}</p></div>
        <div className="rounded bg-black/30 p-3"><p className="text-xs text-white/40">Κατάσταση</p><p className="text-sm text-gold">{selectedPack.readiness_status || 'collecting'}</p></div>
      </>}
      <div className="text-xs text-white/40 space-y-2 pt-2">
        <p>Για καλύτερο αποτέλεσμα: ήσυχο δωμάτιο, ίδιο μικρόφωνο, φυσική ένταση φωνής.</p>
        <p>Το Voice Pack αποθηκεύει τα αυθεντικά δείγματα. Η δημιουργία πραγματικού clone θα ενεργοποιηθεί μόνο όταν συνδεθεί provider που υποστηρίζει voice cloning.</p>
      </div>
    </section>
  </div>;
}
