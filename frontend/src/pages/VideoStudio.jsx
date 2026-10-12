import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Check, Copy, Download, Film, Grid2X2, Heart, List, Loader2, Mic, MicOff, Pencil,
  Play, Plus, Search, Sparkles, Trash2, Upload, Volume2, VolumeX, X,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiDelete, apiGet, apiPatch, apiPost, uploadFormData } from '../lib/api';
import { handoffForTarget } from '../platform/studioHandoff';
import { useVoiceGuidance } from '../lib/useVoiceGuidance';

export const MODES = [
  ['text-to-video', 'Text to Video'], ['image-to-video', 'Image to Video'], ['multi-image', 'Multiple Images'],
  ['variation', 'Variation'], ['extend', 'Extension'], ['interpolation', 'Interpolation'],
];
const ACTIVE = new Set(['queued', 'preparing', 'uploading', 'processing', 'rendering']);
const label = (value) => String(value || '').replaceAll('-', ' ');
const date = (value) => value ? new Date(value).toLocaleString() : '—';
const providerLabel = (value) => value === 'huggingface' ? 'Hugging Face' : value === 'luma' ? 'Luma' : value === 'mock' ? 'Mock' : value || '';

export default function VideoStudio() {
  const location = useLocation();
  const navigate = useNavigate();
  const handoffHandledRef = useRef('');
  const [mode, setMode] = useState('image-to-video');
  const [files, setFiles] = useState([]);
  const [prompt, setPrompt] = useState(''); const [negative, setNegative] = useState('');
  const [duration, setDuration] = useState(5); const [aspect, setAspect] = useState('16:9');
  const [resolution, setResolution] = useState('720p'); const [fps, setFps] = useState(24);
  const [quality, setQuality] = useState('standard'); const [camera, setCamera] = useState('auto');
  const [style, setStyle] = useState('cinematic'); const [seed, setSeed] = useState(''); const [priority, setPriority] = useState(0);
  const [advanced, setAdvanced] = useState(false); const [job, setJob] = useState(null); const [jobs, setJobs] = useState([]);
  const [filters, setFilters] = useState({ search: '', status: '', favorite: false, sort: 'recent' });
  const [view, setView] = useState('grid'); const [loading, setLoading] = useState(true); const [selected, setSelected] = useState(null);
  const [preview, setPreview] = useState(''); const previewRef = useRef('');
  const [providerInfo, setProviderInfo] = useState(null); const [facets, setFacets] = useState({ folders: [], collections: [] });
  const [libraryError, setLibraryError] = useState(''); const [providerError, setProviderError] = useState('');
  const sourceRequired = mode !== 'text-to-video';

  const releasePreview = useCallback(() => { if (previewRef.current) URL.revokeObjectURL(previewRef.current); previewRef.current = ''; setPreview(''); }, []);
  const loadJobs = useCallback(async () => {
    setLoading(true); setLibraryError(''); try { setJobs(await apiGet('/video/jobs', { params: filters })); } catch (e) { setLibraryError(e.message || 'The video library is temporarily unavailable.'); } finally { setLoading(false); }
  }, [filters]);
  const loadPreview = useCallback(async (item) => { if (!item?.output_media_id) return; releasePreview(); try { const blob = await apiGet(`/video/results/${item.id}`, { responseType: 'blob' }); const url = URL.createObjectURL(blob); previewRef.current = url; setPreview(url); } catch (e) { toast.error(e.message); } }, [releasePreview]);
  useEffect(() => { loadJobs(); return releasePreview; }, [loadJobs, releasePreview]);
  useEffect(() => { apiGet('/video/providers').then((data) => setProviderInfo(data)).catch(() => setProviderError('Provider details are unavailable. Generation will use the server default.')); apiGet('/video/library/facets').then(setFacets).catch(() => {}); }, []);
  useEffect(() => { if (!job || !ACTIVE.has(job.status)) return; const timer = setTimeout(async () => { try { const next = await apiGet(`/video/jobs/${job.id}`); setJob(next); if (next.status === 'completed') { await loadPreview(next); loadJobs(); } } catch (e) { toast.error(e.message); } }, 900); return () => clearTimeout(timer); }, [job, loadJobs, loadPreview]);
  function choose(input) { const maximum = capabilities?.max_image_inputs || (mode === 'multi-image' || mode === 'interpolation' ? 8 : 1); const next = [...input].filter((f) => ['image/png','image/jpeg','image/webp'].includes(f.type)).slice(0, maximum); if (!next.length) return toast.error('Use PNG, JPEG, or WebP images.'); setFiles(next); }
  async function generate(e, overrides = {}) { e?.preventDefault?.(); const effectiveMode = overrides.mode || mode; const effectivePrompt = String(overrides.prompt || prompt).trim(); const effectiveDuration = overrides.duration || duration; const effectiveAspect = overrides.aspect || aspect; const capability = capabilities; if (capability && (!capability.modes.includes(effectiveMode) || !capability.durations.includes(effectiveDuration) || !capability.resolutions.includes(resolution) || !capability.aspect_ratios.includes(effectiveAspect))) return toast.error('The active video engine does not support one or more selected settings.'); if (effectiveMode !== 'text-to-video' && !files.length) return toast.error('Add a source image.'); if (!effectivePrompt) return toast.error('Describe the video you want.'); const data = new FormData(); files.forEach((file) => data.append('files', file)); Object.entries({ mode: effectiveMode, prompt: effectivePrompt, negative_prompt: negative, duration_seconds: effectiveDuration, aspect_ratio: effectiveAspect, resolution, fps, quality, camera_motion: camera, style, priority, seed: seed || '' }).forEach(([k,v]) => data.append(k, String(v))); try { const created = await uploadFormData('/video/generate', data); setJob(created); setSelected(created); toast.success('Video job queued.'); loadJobs(); } catch (err) { toast.error(err.message); } }
  async function action(type, item = job) { try { if (type === 'delete' && !window.confirm('Delete this video and its private files?')) return; if (type === 'delete') { await apiDelete(`/video/jobs/${item.id}`); if (job?.id === item.id) { setJob(null); releasePreview(); } } else { const next = await apiPost(`/video/jobs/${item.id}/${type}`); setJob(next); setSelected(next); } loadJobs(); } catch (e) { toast.error(e.message); } }
  async function patch(item, changes) { try { const next = await apiPatch(`/video/jobs/${item.id}`, changes); setJobs((old) => old.map((x) => x.id === next.id ? next : x)); if (selected?.id === next.id) setSelected(next); } catch (e) { toast.error(e.message); } }
  async function open(item) { setJob(item); setSelected(item); if (item.status === 'completed') await loadPreview(item); }
  async function download(item) { try { const blob = await apiGet(`/video/results/${item.id}`, { responseType: 'blob' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${item.title || 'lumina-video'}.${item.output_mime_type === 'image/gif' ? 'gif' : 'mp4'}`; a.click(); URL.revokeObjectURL(url); } catch (e) { toast.error(e.message); } }
  const current = selected || job;
  const capabilities = providerInfo?.providers?.find((item) => item.name === providerInfo.active)?.capabilities;
  const supportedModes = capabilities?.modes || MODES.map(([key]) => key);
  const supportedDurations = capabilities?.durations || [3, 5, 8];
  const supportedAspects = capabilities?.aspect_ratios || ['16:9', '9:16'];
  const supportedResolutions = capabilities?.resolutions || ['720p', '1080p', '4K'];
  useEffect(() => { const handoff = handoffForTarget(location.state, 'video'); if (!handoff || handoffHandledRef.current === handoff.id) return; handoffHandledRef.current = handoff.id; setMode('text-to-video'); setFiles([]); setPrompt(handoff.prompt); if (handoff.options?.duration) setDuration(handoff.options.duration); if (handoff.options?.aspect) setAspect(handoff.options.aspect); generate(null, { mode: 'text-to-video', prompt: handoff.prompt, ...handoff.options }); navigate(location.pathname, { replace: true, state: null }); }, [location.state, location.pathname, navigate]); // eslint-disable-line react-hooks/exhaustive-deps
  const voiceGuide = useVoiceGuidance({
    onTranscript: (transcript) => {
      setPrompt((prev) => (prev ? `${prev} ${transcript}` : transcript));
    },
  });

  return (
    <div className="h-screen w-full flex flex-col lg:flex-row overflow-hidden bg-ink-950 text-foreground" data-testid="video-studio-page">
      {/* ─── ΑΡΙΣΤΕΡΗ ΣΤΗΛΗ ΕΛΕΓΧΟΥ (LEFT CONTROL PANEL) ─── */}
      <aside className="w-full lg:w-[420px] lg:min-w-[380px] lg:max-w-[450px] h-full flex flex-col border-r border-white/10 bg-ink-950/95 overflow-y-auto shrink-0 z-20 p-4 sm:p-5 space-y-4">
        {/* Row 1: Back to Home + Tool Badge */}
        <div className="flex items-center justify-between gap-2 border-b border-white/[0.08] pb-3">
          <Link
            to="/studio/dashboard"
            data-testid="video-back-home"
            className="inline-flex items-center gap-1.5 rounded-lg border border-gold/40 bg-gold/15 px-3 py-1.5 text-xs font-bold text-gold hover:bg-gold hover:text-black transition shadow-sm"
            title="Επιστροφή στην Αρχική Οθόνη"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>← Επιστροφή στην Αρχική</span>
          </Link>
          <span className="flex items-center gap-1.5 text-xs font-semibold text-white/90">
            <Film className="h-4 w-4 text-gold" />
            <span>Video Studio</span>
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
                  voiceGuide.speak('Καλώς ήρθατε στο Video Studio. Στην αριστερή στήλη μπορείτε να γράψετε αναλυτικά την περιγραφή του βίντεο ή να πατήσετε το μικρόφωνο για φωνητική υπαγόρευση. Επιλέξτε διάρκεια, λειτουργία και πατήστε το χρυσό κουμπί Δημιουργία Βίντεο. Το βίντεο θα αναπαραχθεί στο κεντρικό παράθυρο.');
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
              title="Φωνητική υπαγόρευση περιγραφής βίντεο"
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
            <label htmlFor="video-prompt" className="text-xs font-semibold text-white/90">
              Περιγραφή Βίντεο / Prompt:
            </label>
            <span className="text-[10px] text-white/40">{prompt.length} χαρακτήρες</span>
          </div>
          <div className="relative rounded-xl border border-white/15 bg-black/60 focus-within:border-gold/60 shadow-inner">
            <textarea
              id="video-prompt"
              data-testid="video-prompt-input"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={6}
              placeholder="Περιγράψτε με λεπτομέρεια το θέμα, την κίνηση της κάμερας, το φωτισμό (π.χ. cinematic slow motion drone shot gliding above Venetian harbor at sunset, smooth camera movement, reflections on water)..."
              className="w-full bg-transparent p-3.5 text-sm text-white placeholder:text-white/30 outline-none resize-y leading-relaxed"
            />
          </div>
          {/* Quick template chips */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {[
              'Cinematic drone shot, 4k',
              'Slow motion coastal sunset',
              'Smooth camera forward tracking',
              'Studio lighting product orbit',
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

        {/* Row 4: Mode selector */}
        <div className="space-y-1.5">
          <label className="text-xs text-white/60 block font-medium">Λειτουργία Παραγωγής (Mode):</label>
          <div className="grid grid-cols-2 gap-1.5 text-xs">
            {MODES.map(([key, name]) => (
              <button
                key={key}
                type="button"
                onClick={() => { setMode(key); setFiles([]); }}
                className={`p-2 rounded-lg text-left transition font-medium ${
                  mode === key ? 'bg-gold text-black font-bold shadow' : 'bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
        </div>

        {/* Row 5: Διάρκεια (Duration) & Aspect Ratio */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-3 space-y-3">
          <div>
            <span className="text-xs text-white/60 block mb-1.5">Διάρκεια (Δευτερόλεπτα):</span>
            <div className="flex flex-wrap gap-1.5 text-xs">
              {[3, 5, 8, 15, 30].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDuration(d)}
                  className={`px-3 py-1.5 rounded-lg font-semibold transition ${
                    duration === d ? 'bg-gold text-black shadow' : 'bg-white/[0.05] text-white/70 hover:bg-white/10'
                  }`}
                >
                  {d}s
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-white/60 block mb-1">Αναλογία:</span>
              <select
                value={aspect}
                onChange={(e) => setAspect(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-black/60 px-2.5 py-1.5 text-xs text-white outline-none focus:border-gold/40"
              >
                {supportedAspects.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
            <div>
              <span className="text-white/60 block mb-1">Ανάλυση:</span>
              <select
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-black/60 px-2.5 py-1.5 text-xs text-white outline-none focus:border-gold/40"
              >
                {supportedResolutions.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Row 6: Image Upload if Required */}
        {sourceRequired && (
          <div className="rounded-xl border border-dashed border-white/20 p-3 bg-white/[0.02]">
            <label className="flex flex-col items-center justify-center gap-2 cursor-pointer text-center">
              <Upload className="w-6 h-6 text-gold" />
              <span className="text-xs text-white/80 font-medium">
                {files.length ? `${files.length} αρχείο/α επιλεγμένα` : 'Επιλέξτε αρχική εικόνα (PNG/JPG)'}
              </span>
              <input
                className="sr-only"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple={mode === 'multi-image' || mode === 'interpolation'}
                onChange={(e) => choose(e.target.files)}
              />
            </label>
          </div>
        )}

        {/* Row 7: Primary Action Button */}
        <div className="pt-2">
          <button
            onClick={generate}
            data-testid="generate-video-btn"
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gold px-4 py-3.5 text-sm font-bold text-black transition hover:bg-gold-soft hover:shadow-lg shadow"
          >
            <Sparkles className="w-4 h-4 fill-current" />
            <span>🎬 Δημιουργία Βίντεο (Generate)</span>
          </button>
        </div>
      </aside>

      {/* ─── ΚΕΝΤΡΟ: ΠΑΡΑΘΥΡΟ ΖΩΝΤΑΝΗΣ ΠΡΟΕΠΙΣΚΟΠΗΣΗΣ ΒΙΝΤΕΟ (CENTER VIEWPORT) ─── */}
      <section className="flex-1 h-full flex flex-col bg-black/70 overflow-y-auto p-4 sm:p-6 space-y-6">

      {/* ─── FULL-SCREEN CINEMATIC PREVIEW VIEWPORT (Κάτω σε όλη την οθόνη) ─── */}
      <div className="max-w-[1700px] mx-auto p-4 sm:p-6 space-y-6">
        <section className="lumina-glass rounded-xl p-5 border border-white/10 overflow-hidden shadow-2xl">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-gold font-medium">Ζωντανή Προεπισκόπηση Βίντεο</p>
              <h2 className="font-display text-xl sm:text-2xl text-white mt-0.5">{current?.title || current?.prompt || 'Ready when you are'}</h2>
            </div>
            {current?.status === 'completed' && (
              <button
                onClick={() => download(current)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-gold/15 border border-gold/40 px-3 py-1.5 text-xs text-gold hover:bg-gold hover:text-black transition"
              >
                <Download className="w-4 h-4" />
                <span>Download MP4</span>
              </button>
            )}
          </div>

          <div className="min-h-[460px] max-h-[65vh] bg-black/70 rounded-xl flex items-center justify-center overflow-hidden border border-white/10 relative">
            {ACTIVE.has(current?.status) && (
              <div className="w-2/3 max-w-md text-center p-6">
                <Loader2 className="animate-spin text-gold mx-auto mb-4 w-10 h-10" />
                <p className="text-base font-semibold text-white capitalize">{label(current.status)}</p>
                <div className="h-2.5 bg-white/10 rounded-full mt-4 overflow-hidden">
                  <div className="h-full bg-gold rounded-full transition-all duration-300" style={{ width: `${current.progress || 0}%` }} />
                </div>
                <p className="text-xs text-white/50 mt-2.5">{current.progress || 0}% · περίπου {current.estimated_seconds_remaining ?? 'μερικά'} δευτερόλεπτα</p>
                <button onClick={() => action('cancel', current)} className="mt-4 text-xs text-red-300 hover:underline">Ακύρωση εργασίας</button>
              </div>
            )}

            {current?.status === 'completed' && preview && (
              current.output_mime_type === 'image/gif' ? (
                <img src={preview} alt="Generated video" className="max-h-[62vh] max-w-full object-contain" />
              ) : (
                <video src={preview} controls autoPlay loop className="max-h-[62vh] max-w-full rounded-lg shadow-2xl" />
              )
            )}

            {['failed', 'cancelled'].includes(current?.status) && (
              <div className="text-center p-6">
                <p className="text-red-200 text-sm">{current.error || `Job ${current.status}`}</p>
                <button onClick={() => action('retry', current)} className="mt-3 inline-flex items-center gap-1 text-gold text-sm hover:underline">Επανάληψη</button>
              </div>
            )}

            {!current && (
              <div className="text-center p-8 text-white/30">
                <Play className="w-16 h-16 mx-auto mb-3 opacity-40 text-gold" strokeWidth={1} />
                <p className="text-sm">Επιλέξτε διάρκεια και περιγραφή επάνω και ξεκινήστε την παραγωγή.</p>
              </div>
            )}
          </div>

          {current && (
            <p className="text-xs text-white/40 mt-3">
              {label(current.mode)} · {current.duration_seconds}s · {current.resolution} · {current.aspect_ratio} · {current.provider} · {date(current.created_at)}
            </p>
          )}
        </section>

        {/* ─── RECENT CREATIONS & VIDEO LIBRARY ─── */}
        <section className="space-y-4 pt-2">
          <div className="flex flex-wrap gap-3 items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-wider text-white/40">Βιβλιοθήκη Βίντεο</p>
              <h3 className="font-display text-xl text-white">Πρόσφατες Δημιουργίες</h3>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setView('grid')} className={`p-1.5 rounded ${view === 'grid' ? 'text-gold bg-gold/10' : 'text-white/40 hover:text-white'}`}><Grid2X2 className="w-4 h-4" /></button>
              <button onClick={() => setView('list')} className={`p-1.5 rounded ${view === 'list' ? 'text-gold bg-gold/10' : 'text-white/40 hover:text-white'}`}><List className="w-4 h-4" /></button>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <label className="relative">
              <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-white/35" />
              <input
                value={filters.search}
                onChange={(e) => setFilters({ ...filters, search: e.target.value })}
                placeholder="Αναζήτηση βίντεο..."
                className="pl-8 pr-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-white outline-none focus:border-gold/40"
              />
            </label>
            <select
              value={filters.status}
              onChange={(e) => setFilters({ ...filters, status: e.target.value })}
              className="bg-white/5 border border-white/10 rounded-lg text-xs text-white px-2.5 py-1.5 outline-none"
            >
              <option value="">Όλα τα statuses</option>
              {['queued', 'preparing', 'uploading', 'processing', 'rendering', 'completed', 'failed', 'cancelled'].map((x) => (
                <option key={x} value={x}>{x}</option>
              ))}
            </select>
            <button
              onClick={() => setFilters({ ...filters, favorite: !filters.favorite })}
              className={`px-3 py-1.5 rounded-lg text-xs transition ${filters.favorite ? 'bg-gold text-black font-semibold' : 'bg-white/5 text-white/60 hover:text-white'}`}
            >
              Αγαπημένα
            </button>
          </div>

          {loading ? (
            <div className="py-12 text-center text-white/40"><Loader2 className="animate-spin mx-auto w-6 h-6 text-gold" /></div>
          ) : !jobs.length ? (
            <div className="py-12 text-center rounded-xl border border-white/10 bg-white/[0.01] text-xs text-white/40">Δεν υπάρχουν ακόμη βίντεο. Δημιουργήστε το πρώτο σας βίντεο παραπάνω!</div>
          ) : (
            <div className={view === 'grid' ? 'grid md:grid-cols-2 xl:grid-cols-3 gap-3' : 'space-y-2'}>
              {jobs.map((item) => (
                <article key={item.id} className={`border border-white/10 bg-white/[.025] rounded-xl p-4 transition hover:border-gold/30 ${view === 'list' ? 'flex items-center justify-between gap-3' : ''}`}>
                  <div className="min-w-0">
                    <button onClick={() => open(item)} className="text-left text-white text-sm font-medium truncate max-w-full hover:text-gold transition">
                      {item.title || item.prompt}
                    </button>
                    <p className="text-xs text-white/40 mt-1 capitalize">{item.status} · {label(item.mode)} · {item.duration_seconds}s · {item.resolution}</p>
                  </div>
                  <div className="flex gap-2 mt-3">
                    <button onClick={() => patch(item, { favorite: !item.favorite })} title="Favorite" className={item.favorite ? 'text-gold' : 'text-white/40 hover:text-white'}>
                      <Heart className="w-4 h-4" fill={item.favorite ? 'currentColor' : 'none'} />
                    </button>
                    <button onClick={() => { const title = window.prompt('Video title', item.title); if (title !== null) patch(item, { title }); }} title="Rename" className="text-white/40 hover:text-white">
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button onClick={() => action('duplicate', item)} title="Duplicate" className="text-white/40 hover:text-white">
                      <Copy className="w-4 h-4" />
                    </button>
                    {item.status === 'completed' && (
                      <button onClick={() => download(item)} title="Download" className="text-gold hover:text-gold-soft">
                        <Download className="w-4 h-4" />
                      </button>
                    )}
                    <button onClick={() => action('delete', item)} title="Delete" className="text-red-300 hover:text-red-400">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
      </section>
    </div>
  );
}
function Select({label: text,value,onChange,options}) { return <label className="text-xs text-white/60">{text}<select value={value} onChange={(e)=>onChange(typeof options[0]==='number'?Number(e.target.value):e.target.value)} className="mt-1 w-full rounded bg-black/40 border border-white/10 p-2 text-white">{options.map((x)=><option key={x} value={x}>{x}</option>)}</select></label>; }

export function OrganizationActions({ selected, facets = { folders: [], collections: [] }, onPatch, onRefresh }) {
  const create = async (kind) => { const name = window.prompt(`New ${kind} name`); if (!name?.trim()) return; await apiPost('/video/library/organizations', { kind, name: name.trim() }); onRefresh(); };
  const rename = async (item) => { const name = window.prompt(`Rename ${item.kind}`, item.name); if (name?.trim()) { await apiPatch(`/video/library/organizations/${item.id}`, { name: name.trim() }); onRefresh(); } };
  return <div className="flex flex-wrap gap-2"><button type="button" onClick={() => create('folder')}>New folder</button><button type="button" onClick={() => create('collection')}>New collection</button>{(facets.folders || []).map((item) => <button type="button" key={item.id} onClick={() => selected && onPatch(selected, { folder: item.id })}>{item.name}</button>)}{(facets.collections || []).map((item) => <button type="button" key={item.id} onClick={() => selected && onPatch(selected, { collection_ids: [...new Set([...(selected.collection_ids || []), item.id])] })}>{item.name}</button>)}{(facets.folders || []).concat(facets.collections || []).map((item) => <button type="button" key={`rename-${item.id}`} onClick={() => rename(item)}>Rename {item.name}</button>)}</div>;
}
