import { useEffect, useMemo, useRef, useState } from 'react';
import { Mic, Square, RotateCcw, Play, Sparkles, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { apiGet, apiPost, uploadFormData } from '../lib/api';

const RECORDING_TEXT = `Καλησπέρα. Η φωνή μου είναι φυσική, καθαρή και σταθερή. Μιλάω με τον δικό μου καθημερινό τρόπο, χωρίς να προσπαθώ να αλλάξω τον τόνο ή την προφορά μου. Θέλω το Lumina να μάθει τη χροιά, τον ρυθμό, την άρθρωση και τον φυσικό τρόπο με τον οποίο εκφράζομαι. Σε μια επαγγελματική συζήτηση μπορώ να μιλήσω ήρεμα και σοβαρά. Σε μια πιο προσωπική στιγμή μπορώ να είμαι ζεστός και φιλικός. Όταν χρειάζεται, μπορώ να δώσω έμφαση, ενέργεια και αποφασιστικότητα στα λόγια μου. Στόχος αυτής της ηχογράφησης είναι να δημιουργηθεί ένα σταθερό προσωπικό μοντέλο φωνής, το οποίο θα χρησιμοποιώ αργότερα για διαφορετικά κείμενα και διαφορετικά ύφη ομιλίας.`;

const active = status => ['queued', 'preparing', 'processing'].includes(status);

function Card({ children, className = '' }) {
  return <section className={`lumina-glass rounded-xl p-5 ${className}`}>{children}</section>;
}

export default function PersonalVoiceStudio({ packs = [], reload }) {
  const savedVoice = useMemo(
    () => packs.find(p => p.provider === 'elevenlabs' && p.provider_voice_id && p.readiness_status === 'ready'),
    [packs],
  );
  const [state, setState] = useState('idle');
  const [seconds, setSeconds] = useState(0);
  const [blob, setBlob] = useState(null);
  const [blobUrl, setBlobUrl] = useState('');
  const [consent, setConsent] = useState(false);
  const [creating, setCreating] = useState(false);
  const [text, setText] = useState('');
  const [stylePrompt, setStylePrompt] = useState('Ήρεμα, φυσικά και επαγγελματικά, με καθαρή άρθρωση.');
  const [job, setJob] = useState(null);
  const [audioUrl, setAudioUrl] = useState('');
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);

  useEffect(() => () => {
    clearInterval(timerRef.current);
    streamRef.current?.getTracks?.().forEach(track => track.stop());
  }, []);
  useEffect(() => {
    if (!blob) { setBlobUrl(''); return undefined; }
    const url = URL.createObjectURL(blob);
    setBlobUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob]);
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);
  useEffect(() => {
    if (!job?.id || !active(job.status)) return undefined;
    const timer = setTimeout(async () => {
      try {
        const jobs = await apiGet('/voice/jobs');
        const next = jobs.find(item => item.id === job.id);
        if (!next) return;
        setJob(next);
        if (next.status === 'completed') {
          const output = await apiGet(`/voice/results/${next.id}`, { responseType: 'blob' });
          if (audioUrl) URL.revokeObjectURL(audioUrl);
          setAudioUrl(URL.createObjectURL(output));
        } else if (next.status === 'failed') {
          toast.error(next.error || 'Η δημιουργία της φωνής απέτυχε.');
        }
      } catch (error) {
        toast.error(error.message || 'Δεν ήταν δυνατή η ανάκτηση του αποτελέσματος.');
      }
    }, 900);
    return () => clearTimeout(timer);
  }, [job, audioUrl]);

  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      toast.error('Ο browser δεν υποστηρίζει εγγραφή μικροφώνου.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = event => { if (event.data?.size) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop());
        streamRef.current = null;
        clearInterval(timerRef.current);
        setBlob(new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' }));
        setState('stopped');
      };
      recorder.start();
      setBlob(null);
      setSeconds(0);
      setState('recording');
      timerRef.current = setInterval(() => setSeconds(value => value + 1), 1000);
    } catch (error) {
      toast.error(error.name === 'NotAllowedError' ? 'Χρειάζεται άδεια για το μικρόφωνο.' : 'Δεν μπόρεσε να ξεκινήσει η εγγραφή.');
    }
  };

  const stopRecording = () => {
    if (recorderRef.current && recorderRef.current.state !== 'inactive') recorderRef.current.stop();
  };

  const resetRecording = () => {
    if (recorderRef.current && recorderRef.current.state !== 'inactive') recorderRef.current.stop();
    clearInterval(timerRef.current);
    streamRef.current?.getTracks?.().forEach(track => track.stop());
    streamRef.current = null;
    setBlob(null);
    setSeconds(0);
    setState('idle');
  };

  const createMyVoice = async () => {
    if (!blob || !consent) return;
    if (seconds < 45) {
      toast.error('Η ηχογράφηση είναι πολύ μικρή. Στόχευσε περίπου στο 1 λεπτό.');
      return;
    }
    setCreating(true);
    try {
      let pack = packs.find(p => p.name === 'My Voice' && p.provider === 'elevenlabs' && !p.provider_voice_id);
      if (!pack) {
        pack = await apiPost('/voice/packs', {
          name: 'My Voice',
          description: 'Personal voice model recorded in LUMINA.',
          language: 'el',
          accent: 'Greek',
          gender: 'male',
          provider: 'elevenlabs',
          consent_confirmed: true,
          ownership_declaration: 'I confirm that this is my own voice and I consent to creating and using this voice model.',
          tags: ['personal-voice', 'greek'],
        });
      }
      const form = new FormData();
      const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('wav') ? 'wav' : 'webm';
      form.append('file', blob, `my-voice.${ext}`);
      await uploadFormData(`/voice/packs/${pack.id}/samples`, form);
      const cloned = await apiPost(`/voice/packs/${pack.id}/clone`, {});
      toast.success(cloned.readiness_status === 'ready' ? 'Η φωνή σου αποθηκεύτηκε ως My Voice.' : 'Η φωνή στάλθηκε για επαλήθευση.');
      await reload?.();
      setBlob(null);
      setSeconds(0);
      setState('idle');
    } catch (error) {
      toast.error(error.message || 'Δεν μπόρεσε να δημιουργηθεί το My Voice.');
    } finally {
      setCreating(false);
    }
  };

  const generate = async event => {
    event.preventDefault();
    if (!savedVoice) { toast.error('Πρώτα δημιούργησε το My Voice.'); return; }
    if (audioUrl) { URL.revokeObjectURL(audioUrl); setAudioUrl(''); }
    const form = new FormData();
    form.append('pack_id', savedVoice.id);
    form.append('text', text);
    form.append('style_prompt', stylePrompt);
    try {
      setJob(await uploadFormData('/voice/generate-personal', form));
    } catch (error) {
      toast.error(error.message || 'Δεν μπόρεσε να ξεκινήσει η παραγωγή.');
    }
  };

  return <div className="space-y-5">
    <div className="grid lg:grid-cols-2 gap-5">
      <Card>
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-gold text-xs uppercase tracking-[.18em]">Personal Voice</p>
            <h2 className="text-white text-xl mt-1">Record My Voice</h2>
          </div>
          {savedVoice && <span className="flex items-center gap-1 text-green-300 text-xs"><CheckCircle2 className="w-4"/> My Voice ready</span>}
        </div>
        <p className="text-white/50 text-sm mt-3">Διάβασε φυσικά το παρακάτω κείμενο μία φορά. Στόχος: περίπου 1 λεπτό, χωρίς μουσική ή θόρυβο.</p>
        <div className="mt-4 rounded-lg border border-white/10 bg-black/30 p-4 text-white/80 leading-7 text-sm">{RECORDING_TEXT}</div>
        <div className="mt-4 flex items-center gap-3 flex-wrap">
          {state !== 'recording' ? <button onClick={startRecording} className="bg-gold text-black rounded px-4 py-2 text-sm flex items-center gap-2"><Mic className="w-4"/>Start recording</button> : <button onClick={stopRecording} className="bg-red-500/90 text-white rounded px-4 py-2 text-sm flex items-center gap-2"><Square className="w-4"/>Stop</button>}
          <button onClick={resetRecording} className="bg-white/5 text-white/70 rounded px-4 py-2 text-sm flex items-center gap-2"><RotateCcw className="w-4"/>Retake</button>
          <span className="text-white/60 text-sm tabular-nums">{seconds}s</span>
        </div>
        {blobUrl && <div className="mt-4">
          <p className="text-white/60 text-xs mb-2 flex items-center gap-2"><Play className="w-4"/>Άκουσε την ηχογράφηση πριν την αποθηκεύσεις.</p>
          <audio controls src={blobUrl} className="w-full" />
          <label className="mt-4 flex items-start gap-2 text-xs text-white/65"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} className="mt-0.5"/><span>Επιβεβαιώνω ότι είναι η δική μου φωνή και επιτρέπω τη δημιουργία και χρήση του προσωπικού μου μοντέλου φωνής.</span></label>
          <button disabled={!consent || creating} onClick={createMyVoice} className="mt-4 bg-gold text-black rounded px-4 py-2 text-sm disabled:opacity-40">{creating ? 'Creating My Voice…' : 'Create My Voice'}</button>
        </div>}
      </Card>

      <Card>
        <p className="text-gold text-xs uppercase tracking-[.18em]">Saved model</p>
        <h2 className="text-white text-xl mt-1">My Voice</h2>
        {savedVoice ? <div className="mt-4 space-y-2">
          <p className="text-green-300 text-sm">Η προσωπική φωνή είναι έτοιμη.</p>
          <p className="text-white/50 text-xs">Provider: ElevenLabs · Voice Pack: {savedVoice.name}</p>
          <p className="text-white/45 text-xs">Δεν χρειάζεται νέα ηχογράφηση για κάθε κείμενο. Το ίδιο μοντέλο χρησιμοποιείται μέχρι να επιλέξεις να το αντικαταστήσεις.</p>
        </div> : <div className="mt-4 rounded-lg border border-gold/20 bg-gold/5 p-4"><p className="text-white/70 text-sm">Δεν έχει δημιουργηθεί ακόμη προσωπικό μοντέλο. Κάνε μία καθαρή ηχογράφηση και πάτησε Create My Voice.</p></div>}
      </Card>
    </div>

    <div className="grid lg:grid-cols-2 gap-5">
      <Card>
        <p className="text-gold text-xs uppercase tracking-[.18em]">Generate</p>
        <h2 className="text-white text-xl mt-1">Speak with My Voice</h2>
        <form onSubmit={generate} className="mt-4 space-y-4">
          <label className="block text-xs text-white/60">Κείμενο<textarea required value={text} onChange={e => setText(e.target.value)} rows="7" className="mt-2 block w-full rounded bg-black/40 p-3 text-white" placeholder="Γράψε οποιοδήποτε ελληνικό κείμενο…"/></label>
          <label className="block text-xs text-white/60">Style Prompt<textarea value={stylePrompt} onChange={e => setStylePrompt(e.target.value)} rows="3" className="mt-2 block w-full rounded bg-black/40 p-3 text-white" placeholder="π.χ. Ήρεμα και σοβαρά, λίγο πιο αργά, σαν επαγγελματική παρουσίαση."/></label>
          <div className="flex gap-2 flex-wrap">{['Ήρεμα και φυσικά','Επαγγελματικά και σοβαρά','Δυναμικά και με ενέργεια','Ζεστά και συναισθηματικά'].map(value => <button type="button" key={value} onClick={() => setStylePrompt(value)} className="text-xs px-3 py-1.5 rounded bg-white/5 text-white/60">{value}</button>)}</div>
          <button disabled={!savedVoice || active(job?.status)} className="bg-gold text-black rounded px-4 py-2 text-sm disabled:opacity-40 flex items-center gap-2"><Sparkles className="w-4"/>{active(job?.status) ? 'Creating…' : 'Generate with My Voice'}</button>
        </form>
      </Card>
      <Card>
        <p className="text-white/50 text-sm">{job ? `Job ${job.status}` : 'Το αποτέλεσμα με τη δική σου φωνή θα εμφανιστεί εδώ.'}</p>
        {audioUrl && <audio controls autoPlay src={audioUrl} className="w-full mt-4"/>}
        {job?.status === 'completed' && <p className="text-green-300 text-xs mt-3">Το κείμενο δημιουργήθηκε με το My Voice.</p>}
        {job?.status === 'failed' && <p className="text-red-200 text-xs mt-3">{job.error || 'Η παραγωγή απέτυχε.'}</p>}
      </Card>
    </div>
  </div>;
}
