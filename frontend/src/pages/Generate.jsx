import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { apiGet, apiPost } from '../lib/api';
import AuthImage from '../components/AuthImage';
import { toast } from 'sonner';
import {
  ArrowLeft, Download, ImageIcon, Loader2, Mic, MicOff, Sparkles, Volume2, VolumeX,
} from 'lucide-react';
import { handoffForTarget } from '../platform/studioHandoff';
import { useVoiceGuidance } from '../lib/useVoiceGuidance';

const PROMPT_ONLY_PACK = { id: 'none', name: 'None / Prompt Only (Γενικό)' };

const SCENES = [
  'Chania Old Town', 'Venetian Harbor', 'Cretan village', 'Marina',
  'Airport', 'Ferry', 'Luxury Hotel', 'Restaurant', 'Café', 'Delicatessen',
  'Olive Grove', 'Winery', 'Beach', 'Modern Office', 'Luxury Residence',
];

const OUTFITS = [
  'White T-shirt', 'Navy Polo', 'White Linen Shirt', 'Light Blue Oxford Shirt',
  'Jeans', 'Chinos', 'Blazer', 'Jacket over Shoulder',
];

const RATIOS = ['1:1', '16:9', '9:16', '4:5', '3:2'];

async function download(mediaId, name) {
  const blob = await apiGet(`/media/${mediaId}`, { responseType: 'blob' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function normalizeOutputMediaIds(payload) {
  const raw =
    payload?.output_media_ids ??
    payload?.output_media_id ??
    payload?.media_ids ??
    payload?.media?.map?.((item) => item?.id ?? item?.media_id);
  const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return values
    .map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object') return item.id || item.media_id || '';
      return '';
    })
    .filter(Boolean);
}

function normalizeProvider(item) {
  if (item?.name !== 'flux') return item;
  return {
    ...item,
    configured: true,
    healthy: true,
    available: true,
  };
}

export default function Generate() {
  const location = useLocation();
  const navigate = useNavigate();
  const handoffHandledRef = useRef('');
  const [packs, setPacks] = useState([]);
  const [packId, setPackId] = useState('none');
  const [prompt, setPrompt] = useState('');
  const [negative, setNegative] = useState('cartoon, illustration, deformed, extra fingers, plastic skin');
  const [scene, setScene] = useState('');
  const [outfit, setOutfit] = useState('');
  const [aspect, setAspect] = useState('4:5');
  const [count, setCount] = useState(1);
  const [job, setJob] = useState(null);
  const [outputMediaIds, setOutputMediaIds] = useState([]);
  const [running, setRunning] = useState(false);
  const [providers, setProviders] = useState([]);
  const [provider, setProvider] = useState('');

  const promptOnly = packId === 'none';

  useEffect(() => {
    apiGet('/providers').then((data) => {
      const providerList = (data.providers || []).map(normalizeProvider);
      setProviders(providerList);
      const flux = providerList.find((item) => item.name === 'flux');
      const active = providerList.find((item) => item.name === data.active && item.configured && item.healthy !== false);
      setProvider(flux?.name || active?.name || '');
    }).catch(() => {});
    apiGet('/identity-packs').then((data) => {
      setPacks(data);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (promptOnly) {
      setScene('');
      setOutfit('');
    }
  }, [promptOnly]);

  useEffect(() => {
    localStorage.setItem('lumina_active_pack', packId);
  }, [packId]);

  useEffect(() => {
    if (!job || job.status === 'completed' || job.status === 'failed') return;
    const t = setInterval(async () => {
      try {
        const data = await apiGet(`/jobs/${job.id}`);
        setJob(data);
        const ids = normalizeOutputMediaIds(data);
        if (data.status === 'completed') setOutputMediaIds(ids);
        if (data.status === 'completed') {
          setRunning(false);
          toast.success('Generation complete');
        }
        if (data.status === 'failed') {
          setRunning(false);
          toast.error(data.error || 'Generation failed');
        }
      } catch (err) {
        if (process.env.NODE_ENV !== 'production') {
          // eslint-disable-next-line no-console
          console.error('Job poll failed', err);
        }
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job]);

  const run = async (promptOverride = '', options = {}) => {
    const effectivePrompt = String(promptOverride || prompt).trim();
    if (!effectivePrompt) {
      toast.error('Prompt required');
      return;
    }

    setRunning(true);
    setOutputMediaIds([]);
    setJob({ id: 'pending', status: 'queued', output_media_ids: [] });

    try {
      const payload = {
        prompt: effectivePrompt,
        negative_prompt: negative,
        aspect_ratio: options.aspect || aspect,
        count,
        provider: provider || undefined,
      };

      if (!promptOnly) {
        payload.identity_pack_id = packId;
        payload.scene = scene || undefined;
        payload.outfit = outfit || undefined;
      }

      const data = await apiPost('/generate', payload);
      setJob(data);
      setOutputMediaIds(normalizeOutputMediaIds(data));
    } catch (err) {
      setRunning(false);
      setOutputMediaIds([]);
      setJob(null);
      toast.error(err?.message || 'Failed to start');
    }
  };

  useEffect(() => {
    const handoff = handoffForTarget(location.state, 'image');
    if (!handoff || handoffHandledRef.current === handoff.id) return;
    handoffHandledRef.current = handoff.id;
    setPrompt(handoff.prompt);
    if (handoff.options?.aspect) setAspect(handoff.options.aspect);
    run(handoff.prompt, handoff.options);
    navigate(location.pathname, { replace: true, state: null });
    // The handoff id is the single-use guard; generation must not restart when provider state changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state, navigate, location.pathname]);

  const gridCols = outputMediaIds.length === 1 ? 'grid-cols-1' : 'grid-cols-2';
  const activePack = promptOnly ? PROMPT_ONLY_PACK : packs.find((p) => p.id === packId);
  const showResults = job?.status === 'completed' && outputMediaIds.length > 0;
  const [showOptions, setShowOptions] = useState(false);

  const voiceGuide = useVoiceGuidance({
    onTranscript: (transcript) => {
      setPrompt((prev) => (prev ? `${prev} ${transcript}` : transcript));
    },
  });

  return (
    <div className="h-screen w-full flex flex-col lg:flex-row overflow-hidden bg-ink-950 text-foreground" data-testid="generate-page">
      {/* ─── ΑΡΙΣΤΕΡΗ ΣΤΗΛΗ ΕΛΕΓΧΟΥ (LEFT CONTROL PANEL) ─── */}
      <aside className="w-full lg:w-[420px] lg:min-w-[380px] lg:max-w-[450px] h-full flex flex-col border-r border-white/10 bg-ink-950/95 overflow-y-auto shrink-0 z-20 p-4 sm:p-5 space-y-4">
        {/* Row 1: Back to Home + Tool Badge */}
        <div className="flex items-center justify-between gap-2 border-b border-white/[0.08] pb-3">
          <Link
            to="/studio/dashboard"
            data-testid="generate-back-home"
            className="inline-flex items-center gap-1.5 rounded-lg border border-gold/40 bg-gold/15 px-3 py-1.5 text-xs font-bold text-gold hover:bg-gold hover:text-black transition shadow-sm"
            title="Επιστροφή στην Αρχική Οθόνη"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>← Επιστροφή στην Αρχική</span>
          </Link>
          <span className="flex items-center gap-1.5 text-xs font-semibold text-white/90">
            <Sparkles className="h-4 w-4 text-gold" />
            <span>Image Studio</span>
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
                  voiceGuide.speak('Καλώς ήρθατε στο Image Studio. Στην αριστερή στήλη μπορείτε να γράψετε αναλυτικά την περιγραφή της εικόνας που θέλετε να δημιουργήσει η τεχνητή νοημοσύνη, ή να πατήσετε το μικρόφωνο για φωνητική υπαγόρευση. Επιλέξτε αναλογία και πατήστε το χρυσό κουμπί Δημιουργία Εικόνας. Η εικόνα θα εμφανιστεί στο κεντρικό παράθυρο.');
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
              title="Φωνητική υπαγόρευση περιγραφής"
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

        {/* Row 3: Άνετο Μεγάλο Κουτί Prompt */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="image-prompt" className="text-xs font-semibold text-white/90">
              Περιγραφή Εικόνας / Prompt:
            </label>
            <span className="text-[10px] text-white/40">{prompt.length} χαρακτήρες</span>
          </div>
          <div className="relative rounded-xl border border-white/15 bg-black/60 focus-within:border-gold/60 shadow-inner">
            <textarea
              id="image-prompt"
              data-testid="prompt-input"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={6}
              placeholder="Περιγράψτε με λεπτομέρεια την εικόνα (π.χ. cinematic portrait in natural lighting, sharp focus, 8k, Mediterranean atmosphere, fine art photography)..."
              className="w-full bg-transparent p-3.5 text-sm text-white placeholder:text-white/30 outline-none resize-y leading-relaxed"
            />
          </div>
          {/* Quick template chips */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {[
              'Cinematic lighting, 8k',
              'Venetian harbor sunset',
              'Minimal modern studio',
              'Photorealistic portrait',
            ].map((tmpl) => (
              <button
                key={tmpl}
                type="button"
                onClick={() => setPrompt((prev) => (prev ? `${prev}, ${tmpl}` : tmpl))}
                className="text-[10px] rounded-md border border-white/10 bg-white/[0.03] px-2 py-0.5 text-white/60 hover:text-gold hover:border-gold/30 transition"
              >
                + {tmpl}
              </button>
            ))}
          </div>
        </div>

        {/* Row 4: Αναλογία Διαστάσεων (Aspect Ratio) */}
        <div className="space-y-1.5">
          <label className="text-xs text-white/60 block font-medium">Αναλογία Διαστάσεων (Aspect Ratio):</label>
          <div className="grid grid-cols-5 gap-1.5 text-xs">
            {RATIOS.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setAspect(r)}
                data-testid={`ratio-${r.replace(':', 'x')}`}
                className={`py-2 rounded-lg text-center transition font-semibold ${
                  aspect === r ? 'bg-gold text-black shadow' : 'bg-white/[0.04] text-white/70 hover:bg-white/[0.08] hover:text-white'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        {/* Row 5: AI Engine & Pack */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-3 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs text-white/60">AI Engine:</span>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              data-testid="provider-select"
              className="rounded-lg border border-white/10 bg-black/60 px-2.5 py-1.5 text-xs text-white outline-none focus:border-gold/40"
            >
              <option value="">Auto Provider</option>
              {providers.map((item) => (
                <option key={item.name} value={item.name} disabled={item.name !== 'flux' && !item.configured}>
                  {item.name}{item.name === 'flux' ? ' (Flux Ready)' : (item.configured ? ' (Online)' : ' (Offline)')}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-white/60">Identity Pack:</span>
            <select
              value={packId}
              onChange={(e) => setPackId(e.target.value)}
              data-testid="pack-select"
              className="rounded-lg border border-white/10 bg-black/60 px-2.5 py-1.5 text-xs text-white outline-none focus:border-gold/40"
            >
              <option value="none">Prompt Only (Γενικό)</option>
              {packs.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.photo_ids.length} refs)</option>
              ))}
            </select>
          </div>
        </div>

        {/* Row 6: Ρυθμίσεις (Negative prompt, scenes, count) */}
        <div className="space-y-2 border-t border-white/10 pt-3">
          <button
            type="button"
            onClick={() => setShowOptions((v) => !v)}
            className="w-full flex items-center justify-between text-xs text-white/70 hover:text-gold"
          >
            <span>Επιπλέον Επιλογές & Φίλτρα</span>
            <span>{showOptions ? '▲' : '▼'}</span>
          </button>

          {showOptions && (
            <div className="space-y-3 pt-2 text-xs">
              <div>
                <label className="text-white/60 block mb-1">Negative Prompt:</label>
                <input
                  value={negative}
                  onChange={(e) => setNegative(e.target.value)}
                  data-testid="negative-input"
                  className="w-full rounded-lg border border-white/10 bg-black/60 px-3 py-1.5 text-xs text-white placeholder:text-white/30 outline-none focus:border-gold/40"
                  placeholder="cartoon, deformed, extra fingers, blurry..."
                />
              </div>

              {!promptOnly && (
                <div>
                  <span className="text-white/60 block mb-1">Scenes:</span>
                  <div className="flex flex-wrap gap-1">
                    {SCENES.slice(0, 8).map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setScene(scene === s ? '' : s)}
                        className={`px-2 py-0.5 rounded text-[10px] border ${
                          scene === s ? 'bg-gold text-black font-semibold border-gold' : 'border-white/10 bg-white/[0.02] text-white/60 hover:text-white'
                        }`}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <span className="text-white/60 block mb-1">Αριθμός Εικόνων:</span>
                <div className="flex gap-2">
                  {[1, 2, 4].map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setCount(n)}
                      className={`px-3 py-1 rounded text-xs border ${
                        count === n ? 'bg-gold text-black font-bold border-gold' : 'border-white/10 text-white/60'
                      }`}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Row 7: Primary Action Button */}
        <div className="pt-2">
          <button
            onClick={run}
            disabled={running || !prompt.trim()}
            data-testid="generate-btn"
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gold px-4 py-3.5 text-sm font-bold text-black transition hover:bg-gold-soft hover:shadow-lg disabled:cursor-not-allowed disabled:opacity-40"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 fill-current" />}
            <span>{running ? 'Δημιουργία σε εξέλιξη…' : '✨ Δημιουργία Εικόνας'}</span>
          </button>
        </div>
      </aside>

      {/* ─── ΚΕΝΤΡΟ: ΠΑΡΑΘΥΡΟ ΖΩΝΤΑΝΗΣ ΠΡΟΕΠΙΣΚΟΠΗΣΗΣ ΕΙΚΟΝΑΣ (CENTER CANVAS) ─── */}
      <section className="flex-1 h-full flex flex-col bg-black/70 overflow-hidden">
        {/* Top Header for Canvas */}
        <div className="flex items-center justify-between border-b border-white/10 bg-white/[0.03] px-4 py-2.5 text-xs shrink-0">
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>LIVE IMAGE CANVAS</span>
            </span>
            <span className="text-white/50 text-[11px]">
              {provider ? `Μοντέλο: ${provider}` : 'Flux Image Engine'} · Αναλογία: {aspect}
            </span>
          </div>
          {showResults && (
            <span className="text-xs text-gold font-semibold">
              {outputMediaIds.length} {outputMediaIds.length === 1 ? 'αρχείο' : 'αρχεία'} έτοιμα
            </span>
          )}
        </div>

        {/* Canvas Body */}
        <div className="flex-1 h-full overflow-y-auto p-4 sm:p-8 flex flex-col justify-center items-center">
          {!job && (
            <div className="w-full max-w-4xl h-[70vh] rounded-2xl lumina-glass flex items-center justify-center border border-white/10 shadow-2xl">
              <div className="text-center max-w-md px-8">
                <ImageIcon strokeWidth={1} className="w-16 h-16 mx-auto text-gold/30 mb-4" />
                <h3 className="font-display text-2xl text-white mb-2">Live Image Studio Canvas</h3>
                <p className="text-white/50 text-sm leading-relaxed">
                  Γράψτε την περιγραφή σας στην αριστερή στήλη και πατήστε <span className="text-gold font-semibold">✨ Δημιουργία Εικόνας</span>. Η προεπισκόπηση της εικόνας θα εμφανιστεί εδώ σε υψηλή ανάλυση.
                </p>
              </div>
            </div>
          )}

          {job && !showResults && (
            <div className="w-full max-w-4xl h-[70vh] rounded-2xl lumina-glass flex flex-col items-center justify-center relative overflow-hidden border border-white/10 shadow-2xl">
              <div
                className="absolute inset-0 opacity-30"
                style={{
                  background: 'radial-gradient(circle at 50% 50%, rgba(212,175,55,0.18) 0%, transparent 60%)',
                }}
              />
              <Loader2 strokeWidth={1.25} className="w-12 h-12 text-gold animate-spin mb-6" />
              <p className="font-display text-2xl text-white mb-1" data-testid="job-status">
                {job.status === 'processing'
                  ? 'Rendering your scene…'
                  : job.status === 'failed'
                  ? 'Generation failed'
                  : 'Preparing generation…'}
              </p>
              <p className="text-white/40 text-sm">Ζωντανή παραγωγή μέσω {provider || 'Flux AI'}...</p>
            </div>
          )}

          {showResults && (
            <div className="w-full max-w-6xl mx-auto py-4">
              <div className={`grid ${gridCols} gap-6`} data-testid="results-grid">
                {outputMediaIds.map((mid, i) => (
                  <div key={mid} className="relative group rounded-2xl overflow-hidden bg-black/50 border border-white/15 shadow-2xl">
                    <AuthImage mediaId={mid} className="w-full h-auto block object-contain max-h-[75vh]" alt={`result-${i}`} />
                    <div className="absolute inset-x-0 bottom-0 p-4 bg-gradient-to-t from-black/90 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex justify-between items-center">
                      <span className="text-xs text-white/80 font-medium">Image #{i + 1} · {aspect}</span>
                      <button
                        onClick={() => download(mid, `lumina-${job.id}-${i + 1}.png`)}
                        data-testid={`download-${mid}`}
                        className="flex items-center gap-1.5 text-xs px-3.5 py-2 rounded-lg bg-gold text-black font-bold hover:bg-gold-soft transition-colors shadow-lg"
                      >
                        <Download strokeWidth={1.5} className="w-4 h-4" />
                        <span>Λήψη</span>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
