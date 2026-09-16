import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AudioLines, Download, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { apiGet, apiPost, fetchMediaBlobUrl, uploadFormData } from '../lib/api';
import { handoffForTarget } from '../platform/studioHandoff';

export const LUMINA_VOICES = [
  {
    id: 'andreas',
    name: 'Ανδρέας',
    providerVoice: 'el-GR-NestorasNeural',
    subtitle: 'Ανδρική φωνή · Φυσική & Ήρεμη',
    language: 'el-GR',
  },
  {
    id: 'ariadni',
    name: 'Αριάδνη',
    providerVoice: 'el-GR-AthinaNeural',
    subtitle: 'Γυναικεία φωνή · Φυσική & Ήρεμη',
    language: 'el-GR',
  },
];

export const LUMINA_STYLES = ['Natural', 'Calm', 'Warm', 'Confident', 'Energetic'];

const STYLE_TO_BACKEND = {
  Natural: 'podcast',
  Calm: 'calm',
  Warm: 'audiobook',
  Confident: 'corporate',
  Energetic: 'energetic',
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export default function VoiceStudio() {
  const location = useLocation();
  const navigate = useNavigate();
  const handoffHandledRef = useRef('');
  const [text, setText] = useState('');
  const [voiceId, setVoiceId] = useState('ariadni');
  const [style, setStyle] = useState('Natural');
  const [job, setJob] = useState(null);
  const [audioUrl, setAudioUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [providerReady, setProviderReady] = useState(null);
  const [voicePacks, setVoicePacks] = useState([]);
  const [packName, setPackName] = useState('Γιάννης');
  const [consent, setConsent] = useState(false);
  const [packBusy, setPackBusy] = useState(false);
  const [resultVoice, setResultVoice] = useState('');

  const selectedVoice = useMemo(
    () => voicePacks.find((pack) => `pack:${pack.id}` === voiceId)
      ? { name: voicePacks.find((pack) => `pack:${pack.id}` === voiceId).name, providerVoice: 'el-GR-NestorasNeural' }
      : LUMINA_VOICES.find((voice) => voice.id === voiceId) || LUMINA_VOICES[0],
    [voiceId, voicePacks]
  );

  useEffect(() => {
    apiGet('/voice/packs').then(setVoicePacks).catch(() => toast.error('Δεν φορτώθηκαν οι προσωπικές φωνές.'));
  }, []);

  async function createPack() {
    if (!packName.trim() || !consent) return;
    setPackBusy(true);
    try {
      const pack = await apiPost('/voice/packs', {
        name: packName.trim(), language: 'el-GR', consent_confirmed: true,
        ownership_declaration: 'Έχω δικαίωμα χρήσης και συναίνεση για το δείγμα φωνής.',
      });
      setVoicePacks((items) => [pack, ...items]);
      setVoiceId(`pack:${pack.id}`);
      toast.success('Η προσωπική φωνή δημιουργήθηκε. Πρόσθεσε δείγμα ήχου.');
    } catch (error) { toast.error(error?.message || 'Αποτυχία δημιουργίας φωνής.'); }
    finally { setPackBusy(false); }
  }

  async function uploadSample(packId, file) {
    if (!file) return;
    setPackBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const result = await uploadFormData(`/voice/packs/${packId}/samples`, form);
      setVoicePacks((items) => items.map((item) => item.id === packId ? result.pack : item));
      toast.success('Το δείγμα φωνής αποθηκεύτηκε.');
    } catch (error) { toast.error(error?.message || 'Αποτυχία μεταφόρτωσης δείγματος.'); }
    finally { setPackBusy(false); }
  }

  useEffect(() => {
    let mounted = true;
    apiGet('/voice/providers')
      .then((payload) => {
        if (!mounted) return;
        const edge = (payload?.providers || []).find((item) => item.name === 'edge-tts');
        setProviderReady(Boolean(edge?.available && edge?.configured));
      })
      .catch(() => {
        if (mounted) setProviderReady(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl]);

  async function waitForJob(jobId) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const jobs = await apiGet('/voice/jobs');
      const current = jobs.find((item) => item.id === jobId);
      if (current) {
        setJob(current);
        if (current.status === 'completed') return current;
        if (current.status === 'failed' || current.status === 'cancelled') {
          throw new Error(current.error || 'Voice generation failed.');
        }
      }
      await sleep(1000);
    }
    throw new Error('Voice generation timed out.');
  }

  async function generate(event, textOverride = '', options = {}) {
    event?.preventDefault?.();
    const clean = String(textOverride || text).trim();
    const effectiveVoice = LUMINA_VOICES.find((voice) => voice.id === options.voiceId) || selectedVoice;
    const selectedPack = voicePacks.find((pack) => `pack:${pack.id}` === (options.voiceId || voiceId));
    if (!clean) {
      toast.error('Γράψε πρώτα το κείμενο που θέλεις να μετατρέψεις σε φωνή.');
      return;
    }
    if (selectedPack && !selectedPack.sample_count) {
      toast.error('Πρόσθεσε πρώτα δείγμα στη προσωπική φωνή.');
      return;
    }

    setBusy(true);
    setJob(null);
    if (audioUrl) {
      URL.revokeObjectURL(audioUrl);
      setAudioUrl('');
    }

    try {
      const form = new FormData();
      form.append('text', clean);
      form.append('mode', 'text-to-speech');
      form.append('voice', effectiveVoice.providerVoice);
      form.append('style', STYLE_TO_BACKEND[style]);
      form.append('output_format', 'mp3');
      form.append('provider', 'edge-tts');
      if (selectedPack) form.append('voice_pack_id', selectedPack.id);
      form.append('title', `${effectiveVoice.name} · ${style}`);

      const created = await uploadFormData('/voice/generate', form);
      setJob(created);
      const completed = await waitForJob(created.id);

      if (selectedPack && completed.metadata?.tone_conversion_applied !== true) {
        throw new Error('Η κλωνοποίηση φωνής δεν ολοκληρώθηκε. Δεν θα εμφανιστεί η βασική φωνή ως προσωπική.');
      }

      if (!completed.output_media_id) {
        throw new Error('Η δημιουργία ολοκληρώθηκε χωρίς αρχείο ήχου.');
      }

      const url = await fetchMediaBlobUrl(completed.output_media_id);
      setAudioUrl(url);
      setResultVoice(effectiveVoice.name);
      toast.success('Η φωνή δημιουργήθηκε.');
    } catch (error) {
      toast.error(error?.message || 'Η δημιουργία φωνής απέτυχε.');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const handoff = handoffForTarget(location.state, 'voice');
    if (!handoff || handoffHandledRef.current === handoff.id) return;
    handoffHandledRef.current = handoff.id;
    setText(handoff.prompt);
    if (handoff.options?.voiceId) setVoiceId(handoff.options.voiceId);
    generate(null, handoff.prompt, handoff.options);
    navigate(location.pathname, { replace: true, state: null });
    // The handoff id prevents StrictMode or status refreshes from creating duplicates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state, navigate, location.pathname]);

  function downloadAudio() {
    if (!audioUrl) return;
    const anchor = document.createElement('a');
    anchor.href = audioUrl;
    anchor.download = `${voiceId}-${style.toLowerCase()}.mp3`;
    anchor.click();
  }

  return (
    <main className="h-full overflow-y-auto bg-ink-950 text-white">
      <div className="mx-auto max-w-6xl space-y-6 p-5 md:p-8 lg:p-10">
        <header>
          <p className="flex items-center gap-2 text-xs uppercase tracking-[.25em] text-gold">
            <AudioLines className="h-4 w-4" /> LUMINA Sound
          </p>
          <h1 className="mt-2 font-display text-4xl">Voice Studio</h1>
          <p className="mt-2 max-w-2xl text-sm text-white/55">
            Δημιούργησε ελληνική ομιλία με έτοιμη ή προσωπική φωνή.
          </p>
        </header>

        {providerReady === false && (
          <div className="rounded-xl border border-amber-400/20 bg-amber-400/10 p-4 text-sm text-amber-100">
            Ο δωρεάν πάροχος φωνής δεν είναι διαθέσιμος αυτή τη στιγμή.
          </div>
        )}

        <section className="grid gap-6 lg:grid-cols-[1.05fr_.95fr]">
          <div className="lumina-glass rounded-2xl p-5 md:p-6">
            <label className="text-sm text-white/70" htmlFor="voice-text">Κείμενο</label>
            <textarea
              id="voice-text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Γράψε το κείμενο που θέλεις να μετατρέψεις σε φωνή..."
              rows={10}
              maxLength={5000}
              className="mt-2 block w-full resize-y rounded-xl border border-white/10 bg-black/35 p-4 text-base text-white outline-none transition focus:border-gold/60"
            />
            <div className="mt-2 flex justify-between text-xs text-white/35">
              <span>Greek · el-GR</span>
              <span>{text.length}/5000</span>
            </div>

            <div className="mt-6">
              <p className="mb-3 text-sm text-white/70">Φωνή</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {LUMINA_VOICES.map((voice) => {
                  const selected = voice.id === voiceId;
                  return (
                    <button
                      key={voice.id}
                      type="button"
                      onClick={() => setVoiceId(voice.id)}
                      className={`rounded-xl border p-4 text-left transition ${selected ? 'border-gold bg-gold/10' : 'border-white/10 bg-white/[.03] hover:border-white/20'}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="font-medium text-white">{voice.name}</p>
                          <p className="mt-1 text-xs text-white/45">{voice.subtitle}</p>
                        </div>
                        <div className={`h-3 w-3 rounded-full ${selected ? 'bg-gold' : 'bg-white/15'}`} />
                      </div>
                    </button>
                  );
                })}
                {voicePacks.map((pack) => (
                  <button key={pack.id} type="button" onClick={() => setVoiceId(`pack:${pack.id}`)}
                    className={`rounded-xl border p-4 text-left ${voiceId === `pack:${pack.id}` ? 'border-gold bg-gold/10' : 'border-white/10 bg-white/[.03]'}`}>
                    <p className="font-medium">{pack.name}</p>
                    <p className="text-xs text-white/45">Προσωπική φωνή · {pack.sample_count || 0} δείγματα</p>
                  </button>
                ))}
              </div>
              {voiceId.startsWith('pack:') && !voicePacks.find((pack) => `pack:${pack.id}` === voiceId)?.sample_count && (
                <label className="mt-3 block text-sm text-white/70">Δείγμα φωνής (WAV ή MP3)
                  <input type="file" accept="audio/wav,audio/x-wav,audio/mpeg,audio/mp4,audio/ogg,audio/webm" disabled={packBusy}
                    onChange={(event) => uploadSample(voiceId.slice(5), event.target.files?.[0])} className="mt-2 block w-full text-xs" />
                </label>
              )}
              <div className="mt-4 rounded-xl border border-white/10 p-4">
                <p className="text-sm">Νέα προσωπική φωνή</p>
                <input aria-label="Όνομα προσωπικής φωνής" value={packName} onChange={(event) => setPackName(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-white/10 bg-black/30 p-2 text-sm" />
                <label className="mt-3 flex gap-2 text-xs text-white/65">
                  <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                  Έχω δικαίωμα χρήσης και συναίνεση για αυτή τη φωνή.
                </label>
                <button type="button" onClick={createPack} disabled={packBusy || !consent || !packName.trim()}
                  className="mt-3 rounded-lg bg-white/10 px-3 py-2 text-sm disabled:opacity-40">Δημιουργία προσωπικής φωνής</button>
              </div>
            </div>

            <div className="mt-6">
              <p className="mb-3 text-sm text-white/70">Ύφος</p>
              <div className="flex flex-wrap gap-2">
                {LUMINA_STYLES.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setStyle(item)}
                    className={`rounded-full px-4 py-2 text-xs transition ${style === item ? 'bg-gold text-black' : 'bg-white/5 text-white/65 hover:bg-white/10'}`}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>

            <button
              type="button"
              onClick={generate}
              disabled={busy || !text.trim() || (voiceId.startsWith('pack:') && !voicePacks.find((pack) => `pack:${pack.id}` === voiceId)?.sample_count)}
              className="mt-7 flex w-full items-center justify-center gap-2 rounded-xl bg-gold px-5 py-3 font-medium text-black transition disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {busy ? 'Δημιουργία φωνής...' : 'Generate Voice'}
            </button>
          </div>

          <div className="lumina-glass rounded-2xl p-5 md:p-6">
            <p className="text-sm text-white/70">Αποτέλεσμα</p>
            <div className="mt-4 min-h-[280px] rounded-xl border border-white/10 bg-black/25 p-5">
              {!job && !audioUrl && (
                <div className="flex min-h-[230px] flex-col items-center justify-center text-center text-white/35">
                  <AudioLines className="mb-3 h-9 w-9" />
                  <p>Η παραγόμενη φωνή θα εμφανιστεί εδώ.</p>
                </div>
              )}

              {job && !audioUrl && (
                <div className="flex min-h-[230px] flex-col items-center justify-center text-center">
                  {busy && <Loader2 className="mb-3 h-8 w-8 animate-spin text-gold" />}
                  <p className="text-sm text-white/70">{job.status}</p>
                  <p className="mt-1 text-xs text-white/35">Progress: {job.progress || 0}%</p>
                  {job.error && <p className="mt-3 text-sm text-red-200">{job.error}</p>}
                </div>
              )}

              {audioUrl && (
                <div className="space-y-5">
                  <div>
                    <p className="font-medium">{resultVoice}</p>
                    <p className="text-xs text-white/45">Greek · {style}</p>
                  </div>
                  <audio controls src={audioUrl} className="w-full" />
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={downloadAudio} className="flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2 text-sm hover:bg-white/15">
                      <Download className="h-4 w-4" /> Download MP3
                    </button>
                    <button type="button" onClick={generate} disabled={busy} className="flex items-center gap-2 rounded-lg bg-white/5 px-4 py-2 text-sm text-white/70 hover:bg-white/10 disabled:opacity-40">
                      <RefreshCw className="h-4 w-4" /> Regenerate
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
