import { useEffect, useMemo, useState } from 'react';
import { AudioLines, Download, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { apiGet, fetchMediaBlobUrl, uploadFormData } from '../lib/api';

export const LUMINA_VOICES = [
  {
    id: 'lumina-male',
    name: 'Ανδρέας',
    subtitle: 'Ανδρική φωνή · Φυσική & Ήρεμη',
    language: 'el-GR',
  },
  {
    id: 'lumina-female',
    name: 'Αριάδνη',
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
  const [text, setText] = useState('');
  const [voiceId, setVoiceId] = useState('lumina-female');
  const [style, setStyle] = useState('Natural');
  const [job, setJob] = useState(null);
  const [audioUrl, setAudioUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [providerReady, setProviderReady] = useState(null);

  const selectedVoice = useMemo(
    () => LUMINA_VOICES.find((voice) => voice.id === voiceId) || LUMINA_VOICES[0],
    [voiceId]
  );

  useEffect(() => {
    let mounted = true;
    apiGet('/voice/providers')
      .then((payload) => {
        if (!mounted) return;
        const edge = (payload?.providers || []).find((item) => item.name === 'edge');
        setProviderReady(Boolean(edge?.available && edge?.configured));
      })
      .catch(() => {
        if (mounted) setProviderReady(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
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

  async function generate(event) {
    event?.preventDefault?.();
    const clean = text.trim();
    if (!clean) {
      toast.error('Γράψε πρώτα το κείμενο που θέλεις να μετατρέψεις σε φωνή.');
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
      form.append('voice', voiceId);
      form.append('style', STYLE_TO_BACKEND[style]);
      form.append('output_format', 'mp3');
      form.append('provider', 'edge');
      form.append('title', `${selectedVoice.name} · ${style}`);

      const created = await uploadFormData('/voice/generate', form);
      setJob(created);
      const completed = await waitForJob(created.id);

      if (!completed.output_media_id) {
        throw new Error('Η δημιουργία ολοκληρώθηκε χωρίς αρχείο ήχου.');
      }

      const url = await fetchMediaBlobUrl(completed.output_media_id);
      setAudioUrl(url);
      toast.success('Η φωνή δημιουργήθηκε.');
    } catch (error) {
      toast.error(error?.message || 'Η δημιουργία φωνής απέτυχε.');
    } finally {
      setBusy(false);
    }
  }

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
            Δημιούργησε φυσική ελληνική ομιλία με τις έτοιμες φωνές του LUMINA.
          </p>
        </header>

        {providerReady === false && (
          <div className="rounded-xl border border-amber-400/20 bg-amber-400/10 p-4 text-sm text-amber-100">
            Ο δωρεάν πάροχος φωνής δεν είναι ακόμη διαθέσιμος στο backend. Θα ενεργοποιηθεί με το νέο deploy.
          </div>
        )}

        <section className="grid gap-6 lg:grid-cols-[1.05fr_.95fr]">
          <div className="lumina-glass rounded-2xl p-5 md:p-6">
            <label className="text-sm text-white/70" htmlFor="voice-text">
              Κείμενο
            </label>
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
                      className={`rounded-xl border p-4 text-left transition ${
                        selected
                          ? 'border-gold bg-gold/10'
                          : 'border-white/10 bg-white/[.03] hover:border-white/20'
                      }`}
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
                    className={`rounded-full px-4 py-2 text-xs transition ${
                      style === item ? 'bg-gold text-black' : 'bg-white/5 text-white/65 hover:bg-white/10'
                    }`}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>

            <button
              type="button"
              onClick={generate}
              disabled={busy || !text.trim()}
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
                    <p className="font-medium">{selectedVoice.name}</p>
                    <p className="text-xs text-white/45">Greek · {style}</p>
                  </div>
                  <audio controls src={audioUrl} className="w-full" />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={downloadAudio}
                      className="flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2 text-sm hover:bg-white/15"
                    >
                      <Download className="h-4 w-4" /> Download MP3
                    </button>
                    <button
                      type="button"
                      onClick={generate}
                      disabled={busy}
                      className="flex items-center gap-2 rounded-lg bg-white/5 px-4 py-2 text-sm text-white/70 hover:bg-white/10 disabled:opacity-40"
                    >
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
