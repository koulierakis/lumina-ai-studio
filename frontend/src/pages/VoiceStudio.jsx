import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, AudioLines, Download, Loader2, Mic, MicOff, RefreshCw, Sparkles, Volume2, VolumeX,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiGet, fetchMediaBlobUrl, uploadFormData } from '../lib/api';
import { handoffForTarget } from '../platform/studioHandoff';
import { useVoiceGuidance } from '../lib/useVoiceGuidance';

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

  const selectedVoice = useMemo(
    () => LUMINA_VOICES.find((voice) => voice.id === voiceId) || LUMINA_VOICES[0],
    [voiceId]
  );

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
      form.append('voice', effectiveVoice.providerVoice);
      form.append('style', STYLE_TO_BACKEND[style]);
      form.append('output_format', 'mp3');
      form.append('provider', 'edge-tts');
      form.append('title', `${effectiveVoice.name} · ${style}`);

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

  const voiceGuide = useVoiceGuidance({
    onTranscript: (transcript) => {
      setText((prev) => (prev ? `${prev} ${transcript}` : transcript));
    },
  });

  return (
    <div className="h-screen w-full flex flex-col lg:flex-row overflow-hidden bg-ink-950 text-foreground" data-testid="voice-studio-page">
      {/* ─── ΑΡΙΣΤΕΡΗ ΣΤΗΛΗ ΕΛΕΓΧΟΥ (LEFT CONTROL PANEL) ─── */}
      <aside className="w-full lg:w-[420px] lg:min-w-[380px] lg:max-w-[450px] h-full flex flex-col border-r border-white/10 bg-ink-950/95 overflow-y-auto shrink-0 z-20 p-4 sm:p-5 space-y-4">
        {/* Row 1: Back to Home + Tool Badge */}
        <div className="flex items-center justify-between gap-2 border-b border-white/[0.08] pb-3">
          <Link
            to="/studio/dashboard"
            data-testid="voice-back-home"
            className="inline-flex items-center gap-1.5 rounded-lg border border-gold/40 bg-gold/15 px-3 py-1.5 text-xs font-bold text-gold hover:bg-gold hover:text-black transition shadow-sm"
            title="Επιστροφή στην Αρχική Οθόνη"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>← Επιστροφή στην Αρχική</span>
          </Link>
          <span className="flex items-center gap-1.5 text-xs font-semibold text-white/90">
            <AudioLines className="h-4 w-4 text-gold" />
            <span>Voice Studio</span>
          </span>
        </div>

        {/* Row 2: Φωνητική Καθοδήγηση & Φωνητική Υπαγόρευση */}
        <div className="rounded-xl border border-white/10 bg-black/40 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-gold flex items-center gap-1.5">
              <Volume2 className="h-3.5 w-3.5" />
              <span>Φωνητική Καθοδήγηση</span>
            </span>
            <span className="text-[10px] text-white/40">Voice Assistant</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => {
                if (voiceGuide.isSpeaking) {
                  voiceGuide.stopSpeaking();
                } else {
                  voiceGuide.speak('Καλώς ήρθατε στο Voice Studio. Στην αριστερή στήλη μπορείτε να γράψετε αναλυτικά το κείμενο που θέλετε να μετατραπεί σε φυσική ομιλία, ή να πατήσετε το μικρόφωνο για υπαγόρευση. Επιλέξτε φωνή, Ανδρέα ή Αριάδνη, και πατήστε το χρυσό κουμπί Δημιουργία Φωνής. Η ομιλία θα αναπαραχθεί στο κεντρικό παράθυρο.');
                }
              }}
              className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs font-medium transition ${
                voiceGuide.isSpeaking
                  ? 'border-amber-400 bg-amber-400/20 text-amber-200 animate-pulse'
                  : 'border-white/10 bg-white/[0.04] text-white/80 hover:bg-white/10 hover:text-white'
              }`}
              title="Ακούστε οδηγίες χρήσης στα Ελληνικά"
            >
              {voiceGuide.isSpeaking ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5 text-gold" />}
              <span>{voiceGuide.isSpeaking ? 'Διακοπή' : 'Ακρόαση Οδηγιών'}</span>
            </button>
            <button
              type="button"
              onClick={voiceGuide.toggleListening}
              className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs font-medium transition ${
                voiceGuide.isListening
                  ? 'border-red-400 bg-red-400/20 text-red-200 animate-pulse'
                  : 'border-white/10 bg-white/[0.04] text-white/80 hover:bg-white/10 hover:text-white'
              }`}
              title="Φωνητική υπαγόρευση κειμένου"
            >
              {voiceGuide.isListening ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5 text-red-400" />}
              <span>{voiceGuide.isListening ? 'Ακρόαση…' : 'Υπαγόρευση'}</span>
            </button>
          </div>
          {voiceGuide.voiceMessage && (
            <p className="text-[11px] text-amber-300/90 font-mono bg-amber-400/10 rounded-md p-1.5">
              {voiceGuide.voiceMessage}
            </p>
          )}
        </div>

        {/* Row 3: Άνετο Μεγάλο Κουτί Κειμένου / Prompt */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="voice-text" className="text-xs font-semibold text-white/90">
              Κείμενο προς Εκφώνηση / Prompt:
            </label>
            <span className="text-[10px] text-white/40">{text.length}/5000 χαρακτήρες</span>
          </div>
          <div className="relative rounded-xl border border-white/15 bg-black/60 focus-within:border-gold/60 shadow-inner">
            <textarea
              id="voice-text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={7}
              maxLength={5000}
              placeholder="Γράψτε εδώ με άνεση το κείμενο που θέλετε να εκφωνηθεί με φυσική ελληνική φωνή..."
              className="w-full bg-transparent p-3.5 text-sm text-white placeholder:text-white/30 outline-none resize-y leading-relaxed"
            />
          </div>
          {/* Quick template suggestions */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {[
              'Καλώς ήρθατε στο Lumina Studio.',
              'Η επιχείρησή σας είναι έτοιμη για το επόμενο βήμα.',
              'Επαγγελματική παρουσίαση με τεχνητή νοημοσύνη.',
            ].map((tmpl) => (
              <button
                key={tmpl}
                type="button"
                onClick={() => setText((prev) => (prev ? `${prev} ${tmpl}` : tmpl))}
                className="text-[10px] rounded-md border border-white/10 bg-white/[0.03] px-2 py-0.5 text-white/60 hover:text-gold hover:border-gold/30 transition"
              >
                + {tmpl.slice(0, 28)}…
              </button>
            ))}
          </div>
        </div>

        {/* Row 4: Επιλογή Φωνής (Voice) */}
        <div className="space-y-2">
          <span className="text-xs text-white/70 block font-medium">Επιλογή Φωνής:</span>
          <div className="grid grid-cols-2 gap-2">
            {LUMINA_VOICES.map((voice) => {
              const isSel = voice.id === voiceId;
              return (
                <button
                  key={voice.id}
                  type="button"
                  onClick={() => setVoiceId(voice.id)}
                  className={`rounded-xl border p-3 text-left transition ${
                    isSel ? 'border-gold bg-gold/15 text-white shadow' : 'border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/[0.08]'
                  }`}
                >
                  <p className="font-semibold text-xs text-white">{voice.name}</p>
                  <p className="text-[10px] text-white/50">{voice.subtitle.split('·')[0]}</p>
                </button>
              );
            })}
          </div>
        </div>

        {/* Row 5: Επιλογή Ύφους (Style) */}
        <div className="space-y-1.5">
          <span className="text-xs text-white/70 block font-medium">Ύφος Ομιλίας:</span>
          <div className="flex flex-wrap gap-1.5">
            {LUMINA_STYLES.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setStyle(item)}
                className={`rounded-lg px-2.5 py-1 text-xs transition ${
                  style === item ? 'bg-gold text-black font-semibold' : 'bg-white/5 text-white/65 hover:bg-white/10'
                }`}
              >
                {item}
              </button>
            ))}
          </div>
        </div>

        {/* Row 6: Primary Action Button */}
        <div className="pt-2">
          <button
            type="button"
            onClick={generate}
            disabled={busy || !text.trim()}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gold px-4 py-3.5 text-sm font-bold text-black transition hover:bg-gold-soft hover:shadow-lg disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 fill-current" />}
            <span>{busy ? 'Δημιουργία φωνής σε εξέλιξη…' : '⚡ Δημιουργία Φωνής (Generate Voice)'}</span>
          </button>
        </div>
      </aside>

      {/* ─── ΚΕΝΤΡΟ: ΠΑΡΑΘΥΡΟ ΖΩΝΤΑΝΗΣ ΠΡΟΕΠΙΣΚΟΠΗΣΗΣ ΗΧΟΥ (CENTER AUDIO STAGE) ─── */}
      <section className="flex-1 h-full flex flex-col bg-black/70 overflow-hidden">
        {/* Top Header */}
        <div className="flex items-center justify-between border-b border-white/10 bg-white/[0.03] px-4 py-2.5 text-xs shrink-0">
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>LIVE AUDIO STAGE</span>
            </span>
            <span className="text-white/50 text-[11px]">
              Φωνή: {selectedVoice.name} · Ύφος: {style} · el-GR
            </span>
          </div>
          {audioUrl && (
            <span className="text-xs text-emerald-400 font-semibold flex items-center gap-1">
              ✓ Έτοιμο για αναπαραγωγή
            </span>
          )}
        </div>

        {/* Center Stage Body */}
        <div className="flex-1 h-full overflow-y-auto p-4 sm:p-8 flex flex-col justify-center items-center">
          {!job && !audioUrl && (
            <div className="w-full max-w-3xl h-[65vh] rounded-2xl lumina-glass flex items-center justify-center border border-white/10 shadow-2xl">
              <div className="text-center max-w-md px-8">
                <AudioLines strokeWidth={1} className="w-16 h-16 mx-auto text-gold/30 mb-4" />
                <h3 className="font-display text-2xl text-white mb-2">Live Voice Studio Player</h3>
                <p className="text-white/50 text-sm leading-relaxed">
                  Γράψτε ή υπαγορεύστε το κείμενό σας στην αριστερή στήλη και πατήστε <span className="text-gold font-semibold">⚡ Δημιουργία Φωνής</span>. Το ηχητικό αρχείο θα εμφανιστεί εδώ για ζωντανή ακρόαση και λήψη.
                </p>
              </div>
            </div>
          )}

          {job && !audioUrl && (
            <div className="w-full max-w-3xl h-[65vh] rounded-2xl lumina-glass flex flex-col items-center justify-center relative overflow-hidden border border-white/10 shadow-2xl">
              <div
                className="absolute inset-0 opacity-30"
                style={{
                  background: 'radial-gradient(circle at 50% 50%, rgba(212,175,55,0.18) 0%, transparent 60%)',
                }}
              />
              <Loader2 strokeWidth={1.25} className="w-12 h-12 text-gold animate-spin mb-6" />
              <p className="font-display text-2xl text-white mb-1">
                Παραγωγή φυσικής ομιλίας…
              </p>
              <p className="text-white/40 text-sm">Επεξεργασία με {selectedVoice.name} ({style})...</p>
              {job.error && <p className="mt-4 text-sm text-red-300">{job.error}</p>}
            </div>
          )}

          {audioUrl && (
            <div className="w-full max-w-3xl lumina-glass rounded-2xl p-6 sm:p-8 border border-white/15 shadow-2xl space-y-6">
              <div className="flex items-center justify-between border-b border-white/10 pb-4">
                <div>
                  <h3 className="font-display text-xl text-white">{selectedVoice.name}</h3>
                  <p className="text-xs text-gold">{selectedVoice.subtitle} · {style}</p>
                </div>
                <button
                  type="button"
                  onClick={downloadAudio}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gold px-4 py-2 text-xs font-bold text-black hover:bg-gold-soft transition shadow"
                >
                  <Download className="h-4 w-4" />
                  <span>Λήψη MP3</span>
                </button>
              </div>

              <div className="bg-black/50 rounded-xl p-4 border border-white/10">
                <audio controls src={audioUrl} className="w-full" autoPlay />
              </div>

              {text && (
                <div className="rounded-xl border border-white/10 bg-black/30 p-4 space-y-1">
                  <span className="text-[11px] font-semibold text-white/50 uppercase tracking-wider block">Κείμενο Εκφώνησης:</span>
                  <p className="text-sm text-white/80 leading-relaxed font-sans">{text}</p>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={generate}
                  disabled={busy}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/[0.03] px-3.5 py-2 text-xs font-medium text-white/80 hover:bg-white/10 hover:text-white transition"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  <span>Επαναδημιουργία</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
