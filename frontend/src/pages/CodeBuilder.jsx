import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft, CheckCircle2, CircleAlert, Code2, FileCode2, Loader2, Mic, MicOff, Play,
  RefreshCw, RotateCcw, ShieldCheck, Sparkles, Volume2, VolumeX, XCircle,
} from 'lucide-react';
import { apiGet, apiPost } from '../lib/api';
import { useVoiceGuidance } from '../lib/useVoiceGuidance';

const TERMINAL_PHASES = new Set(['completed', 'failed', 'cancelled', 'timed_out', 'rolled_back', 'rollback_failed']);
const DRAFT_STORAGE_KEY = 'lumina_code_builder_instruction';
const ENGINE_STORAGE_KEY = 'lumina_code_builder_engine';

function getSpeechRecognition() {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function speechErrorMessage(error) {
  const messages = {
    'not-allowed': 'Microphone permission was denied. You can continue by typing.',
    'service-not-allowed': 'Speech recognition is unavailable. You can continue by typing.',
    'no-speech': 'No speech was detected. Try again when you are ready.',
    network: 'Speech recognition could not reach its service. Try again or type your request.',
    aborted: 'Voice input stopped. Your draft is still available.',
  };
  return messages[error] || 'Voice input is unavailable right now. Your text draft is still available.';
}

function pretty(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function collectDiffs(preparation) {
  const validation = preparation?.patch_validation;
  const results = Array.isArray(validation?.results) ? validation.results : [];
  return results.map((item) => ({ path: item?.path || item?.relative_path || 'proposed change', diff: item?.diff || '' })).filter((item) => item.diff);
}

function collectPlanFiles(plan) {
  const files = Array.isArray(plan?.files) ? plan.files : [];
  return files.map((file) => ({ path: file?.path || file?.file_path || 'unknown', operation: file?.operation || 'modify', summary: file?.summary || file?.rationale || '' }));
}

function phaseLabel(phase) {
  return String(phase || 'unknown').replaceAll('_', ' ');
}

function getProgressPercentage(phase) {
  if (phase === 'completed') return 100;
  if (TERMINAL_PHASES.has(phase)) return 0;
  switch (phase) {
    case 'queued':
      return 5;
    case 'analyzing':
      return 15;
    case 'awaiting_approval':
      return 50;
    case 'approved':
      return 55;
    case 'executing':
      return 70;
    case 'rolling_back':
      return 60;
    default:
      return 0;
  }
}

function StatusPill({ phase }) {
  const terminal = TERMINAL_PHASES.has(phase);
  const good = phase === 'completed' || phase === 'rolled_back';
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.16em] ${good ? 'border-emerald-400/25 text-emerald-200' : terminal ? 'border-red-400/25 text-red-200' : 'border-gold/25 text-gold'}`}>
      {terminal ? (good ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleAlert className="h-3.5 w-3.5" />) : <Loader2 className="h-3.5 w-3.5" />}
      {phaseLabel(phase)}
    </span>
  );
}

function ElapsedTime({ startedAt, createdAt, finishedAt, phase }) {
  const [now, setNow] = useState(() => (typeof window !== 'undefined' ? Date.now() / 1000 : 0));
  const start = startedAt !== null && startedAt !== undefined ? startedAt : createdAt;

  useEffect(() => {
    if (typeof window === 'undefined' || TERMINAL_PHASES.has(phase)) return undefined;
    setNow(Date.now() / 1000);
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  if (start == null) return '';
  const end = finishedAt !== null && finishedAt !== undefined ? finishedAt : now;
  const diff = Math.max(0, end - start);
  const minutes = Math.floor(diff / 60);
  const seconds = Math.floor(diff % 60);
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

function ProgressInfo({ phase }) {
  const percentage = getProgressPercentage(phase);
  if (percentage === 0 && TERMINAL_PHASES.has(phase)) return null;
  const barWidth = `${percentage}%`;
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-2 h-1.5 rounded-full bg-white/10 overflow-hidden shrink-0">
        <span className={`h-full rounded-full bg-gold transition-colors ease-out duration-200 ${percentage > 0 ? '' : 'opacity-0'}`} style={{ width: barWidth }} />
      </span>
      {percentage > 0 && <span className="text-[10px] text-white/45">{percentage}%</span>}
    </div>
  );
}

function ReviewBadge({ review }) {
  const verdict = review?.verdict || review?.status || 'pending';
  const tone = verdict === 'pass' ? 'border-emerald-400/25 text-emerald-200' : verdict === 'block' ? 'border-red-400/25 text-red-200' : verdict === 'warn' ? 'border-amber-300/25 text-amber-100' : 'border-white/10 text-white/45';
  return <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] ${tone}`}>{verdict}</span>;
}

export default function CodeBuilder() {
  const [instruction, setInstruction] = useState(() => (typeof window !== 'undefined' ? window.localStorage.getItem(DRAFT_STORAGE_KEY) || '' : ''));
  const [task, setTask] = useState(() => {
    try {
      const raw = window.localStorage.getItem('lumina_code_builder_task');
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [comment, setComment] = useState('');
  const [voiceLanguage, setVoiceLanguage] = useState('auto');
  const [voiceState, setVoiceState] = useState('ready');
  const [voiceMessage, setVoiceMessage] = useState('');
  const [modelStatus, setModelStatus] = useState('unknown');
  const [engineStatus, setEngineStatus] = useState({ default: 'native', engines: [{ name: 'native', available: true, experimental: false, safe_mode: true }], openhands_ready: false });
  const [codingEngine, setCodingEngine] = useState(() => (typeof window !== 'undefined' ? window.localStorage.getItem(ENGINE_STORAGE_KEY) || 'native' : 'native'));
  const recognitionRef = useRef(null);
  const voicePrefixRef = useRef('');

  useEffect(() => {
    window.localStorage.setItem(DRAFT_STORAGE_KEY, instruction);
  }, [instruction]);

  useEffect(() => () => recognitionRef.current?.abort(), []);

  const refreshModelStatus = useCallback(async () => {
    try {
      const status = await apiGet('/code-builder/model-status', { retry: false });
      setModelStatus(status.status || 'unavailable');
    } catch {
      setModelStatus('offline');
    }
  }, []);

  useEffect(() => {
    refreshModelStatus();
  }, [refreshModelStatus]);

  const refreshEngineStatus = useCallback(async () => {
    try {
      const status = await apiGet('/code-builder/engines', { retry: false });
      const engines = Array.isArray(status?.engines) && status.engines.length ? status.engines : [{ name: 'native', available: true, experimental: false, safe_mode: true }];
      const normalized = { ...status, default: status?.default || 'native', engines };
      setEngineStatus(normalized);
      setCodingEngine((current) => {
        const option = engines.find((item) => item.name === current);
        return current === 'native' || option?.available ? current : 'native';
      });
    } catch {
      setEngineStatus({ default: 'native', engines: [{ name: 'native', available: true, experimental: false, safe_mode: true }], openhands_ready: false });
      setCodingEngine('native');
    }
  }, []);

  useEffect(() => {
    refreshEngineStatus();
  }, [refreshEngineStatus]);

  useEffect(() => {
    window.localStorage.setItem(ENGINE_STORAGE_KEY, codingEngine);
  }, [codingEngine]);

  const toggleVoice = () => {
    if (voiceState === 'listening') {
      setVoiceState('processing');
      setVoiceMessage('Processing speech…');
      recognitionRef.current?.stop();
      return;
    }

    const Recognition = getSpeechRecognition();
    if (!Recognition) {
      setVoiceState('unavailable');
      setVoiceMessage('Voice input is not supported in this browser. You can continue by typing.');
      return;
    }

    const recognition = new Recognition();
    const language = voiceLanguage === 'auto'
      ? (navigator.language?.toLowerCase().startsWith('el') ? 'el-GR' : 'en-US')
      : voiceLanguage;
    voicePrefixRef.current = instruction.trim() ? `${instruction.trim()}\n` : '';
    recognition.lang = language;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onstart = () => {
      setVoiceState('listening');
      setVoiceMessage('Listening. Nothing will be submitted automatically.');
    };
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results).map((result) => result[0]?.transcript || '').join('');
      setInstruction(`${voicePrefixRef.current}${transcript}`.trimEnd());
      setVoiceState('listening');
    };
    recognition.onerror = (event) => {
      setVoiceState(event.error === 'not-allowed' ? 'denied' : 'error');
      setVoiceMessage(speechErrorMessage(event.error));
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setVoiceState((current) => current === 'processing' || current === 'listening' ? 'ready' : current);
      setVoiceMessage('Draft captured. Review it before submitting.');
    };
    recognitionRef.current = recognition;
    setVoiceState('processing');
    setVoiceMessage('Preparing microphone…');
    try {
      recognition.start();
    } catch {
      recognitionRef.current = null;
      setVoiceState('error');
      setVoiceMessage('Voice input could not start. You can continue by typing.');
    }
  };

  const refresh = useCallback(async (taskId) => {
    const resolvedTaskId = typeof taskId === 'string' ? taskId : task?.task_id;
    if (!resolvedTaskId) return;
    try {
      const detail = await apiGet(`/code-builder/tasks/${resolvedTaskId}`, { retry: false });
      setTask(detail);
      setError('');
    } catch (err) {
      setError(err?.responseData?.detail?.message || err?.message || 'Could not refresh Code Builder task.');
    }
  }, [task?.task_id]);

  useEffect(() => {
    let cancelled = false;
    const restoreTask = async () => {
      try {
        const storedTaskId = window.localStorage.getItem('lumina_code_builder_task_id');
        if (storedTaskId) {
          try {
            const detail = await apiGet(`/code-builder/tasks/${storedTaskId}`, { retry: false });
            if (!cancelled) setTask(detail);
            return;
          } catch {
            window.localStorage.removeItem('lumina_code_builder_task_id');
            window.localStorage.removeItem('lumina_code_builder_task');
          }
        }
        const response = await apiGet('/code-builder/tasks?limit=50', { retry: false });
        const candidate = (response.items || []).find((item) => !TERMINAL_PHASES.has(item.phase)) || response.items?.[0];
        if (candidate && !cancelled) {
          const detail = await apiGet(`/code-builder/tasks/${candidate.task_id}`, { retry: false });
          if (!cancelled) setTask(detail);
        }
      } catch {
        // A disconnected backend should not erase the locally remembered task.
      }
    };
    restoreTask();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!task?.task_id) return;
    window.localStorage.setItem('lumina_code_builder_task_id', task.task_id);
    window.localStorage.setItem('lumina_code_builder_task', JSON.stringify(task));
  }, [task]);

  useEffect(() => {
    if (!task?.task_id || TERMINAL_PHASES.has(task.phase) || task.phase === 'awaiting_approval') return undefined;
    const timer = window.setInterval(() => refresh(task.task_id), 1500);
    return () => window.clearInterval(timer);
  }, [task?.task_id, task?.phase, refresh]);

  const createTask = async () => {
    const value = instruction.trim();
    if (!value || busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await apiPost('/code-builder/tasks', {
        instruction: value,
        require_approval: true,
        auto_start_after_approval: true,
        backup_policy: 'required',
        build_policy: 'required',
        rollback_policy: 'on_any_failure',
        metadata: { coding_engine: codingEngine },
      });
      setTask(response.task);
      setModelStatus(response.task?.review_result?.status === 'unavailable' ? 'unavailable' : 'ready');
    } catch (err) {
      setError(err?.message || 'Could not create Code Builder task.');
      setModelStatus('unavailable');
    } finally {
      setBusy(false);
    }
  };

  const decide = async (decision) => {
    if (!task?.task_id || busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await apiPost(`/code-builder/tasks/${task.task_id}/approve`, {
        decision,
        comment: comment.trim() || null,
        start_immediately: decision === 'approve',
      });
      setTask(response.task);
    } catch (err) {
      setError(err?.responseData?.detail?.message || err?.message || 'Approval action failed.');
    } finally {
      setBusy(false);
    }
  };

  const rollback = async () => {
    if (!task?.task_id || busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await apiPost(`/code-builder/tasks/${task.task_id}/rollback`, { reason: 'Manual rollback from Code Builder UI.', force: false });
      setTask(response.task);
    } catch (err) {
      setError(err?.responseData?.detail?.message || err?.message || 'Rollback failed.');
    } finally {
      setBusy(false);
    }
  };

  const cancelTask = async () => {
    if (!task?.task_id || busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await apiPost(`/code-builder/tasks/${task.task_id}/cancel`, { reason: 'Cancelled from Code Builder UI.' });
      setTask(response);
    } catch (err) {
      setError(err?.responseData?.detail?.message || err?.message || 'Cancellation failed.');
    } finally {
      setBusy(false);
    }
  };

  const [activeTab, setActiveTab] = useState('preview');
  const [previewPath, setPreviewPath] = useState('/studio/dashboard');
  const [viewportMode, setViewportMode] = useState('desktop');
  const [iframeKey, setIframeKey] = useState(1);

  const preparation = task?.preparation_result;
  const review = task?.review_result;
  const plan = preparation?.plan;
  const verification = task?.result?.build_result;
  const planFiles = useMemo(() => collectPlanFiles(plan), [plan]);
  const diffs = useMemo(() => collectDiffs(preparation), [preparation]);
  const canApprove = task?.phase === 'awaiting_approval' && Boolean(preparation?.patch) && Boolean(preparation?.patch_validation) && Boolean(review);
  const canRollback = ['completed', 'failed', 'cancelled', 'timed_out', 'rollback_failed'].includes(task?.phase);
  const voiceLabel = voiceState === 'listening' ? 'Listening…' : voiceState === 'processing' ? 'Processing speech…' : voiceState === 'denied' ? 'Microphone denied' : voiceState === 'unavailable' ? 'Voice unavailable' : voiceState === 'error' ? 'Voice error' : 'Ready';
  const modelLabel = modelStatus === 'ready' ? 'AI model ready' : modelStatus === 'offline' ? 'Ollama offline' : modelStatus === 'not_configured' ? 'Model not configured' : 'AI model unavailable';
  const taskResult = task?.result || {};
  const resultStatus = task?.phase === 'completed' ? 'Task completed' : task?.phase === 'rolled_back' ? 'Task rolled back safely' : task?.phase === 'cancelled' ? 'Task cancelled' : task?.phase === 'timed_out' ? 'Task timed out' : task?.phase === 'rollback_failed' ? 'Task failed and rollback needs attention' : task?.phase === 'failed' ? 'Task failed' : null;

  const voiceGuide = useVoiceGuidance({
    onTranscript: (transcript) => {
      setInstruction((prev) => (prev ? `${prev} ${transcript}` : transcript));
    },
  });

  return (
    <div className="h-screen w-full flex flex-col lg:flex-row overflow-hidden bg-ink-950 text-foreground" data-testid="code-builder-page">
      {/* ─── ΑΡΙΣΤΕΡΗ ΣΤΗΛΗ ΕΡΓΑΛΕΙΟΥ (LEFT CONTROL PANEL - Όλα τα κουμπιά & Prompt εδώ) ─── */}
      <aside className="w-full lg:w-[420px] lg:min-w-[380px] lg:max-w-[450px] h-full flex flex-col border-r border-white/10 bg-ink-950/95 overflow-y-auto shrink-0 z-20 p-4 sm:p-5 space-y-4">
        {/* Row 1: Back to Home + Tool Badge */}
        <div className="flex items-center justify-between gap-2 border-b border-white/[0.08] pb-3">
          <Link
            to="/studio/dashboard"
            data-testid="code-builder-back-home"
            className="inline-flex items-center gap-1.5 rounded-lg border border-gold/40 bg-gold/15 px-3 py-1.5 text-xs font-bold text-gold hover:bg-gold hover:text-black transition shadow-sm"
            title="Επιστροφή στην Αρχική Οθόνη"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>← Επιστροφή στην Αρχική</span>
          </Link>
          <span className="flex items-center gap-1.5 text-xs font-semibold text-white/90">
            <Code2 className="h-4 w-4 text-gold" />
            <span>Google Code Builder</span>
          </span>
        </div>

        {/* Row 2: Model Status & Readiness */}
        <div className="flex flex-wrap items-center justify-between gap-2 bg-white/[0.025] border border-white/[0.07] rounded-xl p-2.5">
          <button
            type="button"
            data-testid="code-builder-model-status"
            onClick={refreshModelStatus}
            title="Recheck Code Builder model"
            className={`inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-0.5 text-xs ${modelStatus === 'ready' ? 'text-emerald-300' : 'text-amber-300'}`}
          >
            <span className="h-2 w-2 rounded-full bg-current" />
            <span>{modelLabel}</span>
            <RefreshCw className="h-3 w-3 opacity-60" />
          </button>
          {task && (
            <div className="flex items-center gap-1.5">
              <StatusPill phase={task.phase} />
              <span data-testid="code-builder-elapsed-time" className="font-mono text-[10px] text-white/50">
                <ElapsedTime startedAt={task.started_at_epoch} createdAt={task.created_at_epoch} finishedAt={task.finished_at_epoch} phase={task.phase} />
              </span>
              <button
                data-testid="code-builder-refresh"
                onClick={() => refresh()}
                title="Refresh task status"
                className="rounded border border-white/10 p-1 text-xs text-white/60 hover:text-white hover:bg-gold/10"
              >
                <RefreshCw className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>

        {/* Row 3: Φωνητική Καθοδήγηση & Φωνητική Υπαγόρευση */}
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
              data-testid="code-builder-voice-help"
              onClick={() => {
                if (voiceGuide.isSpeaking) {
                  voiceGuide.stopSpeaking();
                } else {
                  voiceGuide.speak('Καλώς ήρθατε στον Google Code Builder. Στην αριστερή στήλη μπορείτε να γράψετε αναλυτικά την εντολή σας ή να πατήσετε το μικρόφωνο για φωνητική υπαγόρευση. Στη συνέχεια πατήστε το χρυσό κουμπί για εκτέλεση. Στο κεντρικό παράθυρο παρακολουθείτε ζωντανά την εφαρμογή σας.');
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
              data-testid="code-builder-voice"
              className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs font-medium transition ${
                voiceGuide.isListening
                  ? 'border-red-400 bg-red-400/20 text-red-200 animate-pulse'
                  : 'border-white/10 bg-white/[0.04] text-white/80 hover:bg-white/10 hover:text-white'
              }`}
              title="Φωνητική υπαγόρευση εντολής με μικρόφωνο"
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

        {/* Row 4: Άνετο Μεγάλο Κουτί Prompt */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="code-builder-instruction" className="text-xs font-semibold text-white/90">
              Περιγραφή Εντολής / Prompt:
            </label>
            <span className="text-[10px] text-white/40">{instruction.length} χαρακτήρες</span>
          </div>
          <div className="relative rounded-xl border border-white/15 bg-black/60 focus-within:border-gold/60 shadow-inner">
            <textarea
              id="code-builder-instruction"
              data-testid="code-builder-instruction"
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              rows={6}
              placeholder="Γράψτε εδώ με άνεση τι θέλετε να αλλάξει ή να κατασκευάσει το AI (π.χ. Πρόσθεσε νέα σελίδα, άλλαξε τα χρώματα σε dark mode, κάνε το layout responsive, φτιάξε νέο κουμπί)..."
              className="w-full bg-transparent p-3.5 text-sm text-white placeholder:text-white/30 outline-none resize-y leading-relaxed"
            />
          </div>
          {/* Quick template suggestions */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {[
              'Βελτίωση UI & κουμπιών',
              'Προσθήκη νέου χαρακτηριστικού',
              'Responsive για mobile & tablet',
              'Έλεγχος & διόρθωση σφαλμάτων',
            ].map((tmpl) => (
              <button
                key={tmpl}
                type="button"
                onClick={() => setInstruction((prev) => (prev ? `${prev}\n${tmpl}` : tmpl))}
                className="text-[10px] rounded-md border border-white/10 bg-white/[0.03] px-2 py-0.5 text-white/60 hover:text-gold hover:border-gold/30 transition"
              >
                + {tmpl}
              </button>
            ))}
          </div>
        </div>

        {/* Row 5: AI Engine Select */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-3 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs text-white/60">AI Coding Engine:</span>
            <select
              id="code-builder-engine"
              data-testid="code-builder-engine"
              value={codingEngine}
              onChange={(event) => setCodingEngine(event.target.value)}
              disabled={busy}
              className="rounded-lg border border-white/10 bg-black/60 px-2.5 py-1.5 text-xs text-white outline-none focus:border-gold/40"
            >
              {engineStatus.engines.map((engine) => (
                <option key={engine.name} value={engine.name} disabled={!engine.available}>
                  {engine.name === 'native' ? 'Google Gemini Native' : 'OpenHands'}{engine.experimental ? ' · exp' : ''}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Row 6: Primary Action Buttons */}
        <div className="space-y-2 pt-1">
          <button
            data-testid="code-builder-create"
            onClick={createTask}
            disabled={!instruction.trim() || busy}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gold px-4 py-3 text-sm font-bold text-black transition hover:bg-gold-soft hover:shadow-lg disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
            <span>{busy ? 'Εκτέλεση & Ανάλυση…' : '⚡ Εκτέλεση & Δημιουργία Κώδικα'}</span>
          </button>

          {canApprove && (
            <div className="grid grid-cols-2 gap-2">
              <button
                data-testid="code-builder-approve"
                onClick={() => decide('approve')}
                disabled={!canApprove || busy}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-black transition hover:bg-emerald-400 disabled:opacity-30"
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>Έγκριση</span>
              </button>
              <button
                data-testid="code-builder-reject"
                onClick={() => decide('reject')}
                disabled={!canApprove || busy}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs font-medium text-red-200 transition hover:bg-red-400/20 disabled:opacity-30"
              >
                <XCircle className="h-3.5 w-3.5" />
                <span>Απόρριψη</span>
              </button>
            </div>
          )}

          {task && !TERMINAL_PHASES.has(task.phase) && task.phase !== 'awaiting_approval' && (
            <button
              data-testid="code-builder-cancel"
              onClick={cancelTask}
              disabled={busy}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-red-400/30 px-3 py-2 text-xs text-red-200 disabled:opacity-30"
            >
              <XCircle className="h-3.5 w-3.5" />
              <span>Ακύρωση Εργασίας</span>
            </button>
          )}

          {canRollback && (
            <button
              onClick={rollback}
              disabled={busy}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/15 px-3 py-2 text-xs text-white/70 hover:text-white disabled:opacity-30"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Επαναφορά (Rollback)</span>
            </button>
          )}

          {error && (
            <div className="flex items-center gap-1.5 rounded-lg border border-red-400/30 bg-red-500/10 p-2 text-xs text-red-300">
              <CircleAlert className="h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Row 7: Εναλλαγή Καρτελών Προβολής (Tabs) */}
        <div className="border-t border-white/10 pt-3 space-y-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-white/50 block">
            Προβολή στο Κέντρο:
          </span>
          <div className="grid grid-cols-2 gap-1.5 text-xs">
            <button
              type="button"
              onClick={() => setActiveTab('preview')}
              className={`p-2 rounded-lg text-left transition font-medium ${
                activeTab === 'preview' ? 'bg-gold text-black font-bold shadow' : 'bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white'
              }`}
            >
              🖥️ Live Preview
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('plan')}
              className={`p-2 rounded-lg text-left transition font-medium ${
                activeTab === 'plan' ? 'bg-gold text-black font-bold shadow' : 'bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white'
              }`}
            >
              📄 Diff {diffs.length > 0 && `(${diffs.length})`}
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('review')}
              className={`p-2 rounded-lg text-left transition font-medium ${
                activeTab === 'review' ? 'bg-gold text-black font-bold shadow' : 'bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white'
              }`}
            >
              ✨ AI Review
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('events')}
              className={`p-2 rounded-lg text-left transition font-medium ${
                activeTab === 'events' ? 'bg-gold text-black font-bold shadow' : 'bg-white/[0.03] text-white/70 hover:bg-white/[0.08] hover:text-white'
              }`}
            >
              📜 Events
            </button>
          </div>
        </div>
      </aside>

      {/* ─── ΚΕΝΤΡΟ: ΠΑΡΑΘΥΡΟ ΖΩΝΤΑΝΗΣ ΠΡΟΕΠΙΣΚΟΠΗΣΗΣ (CENTER LIVE PREVIEW & WORKSPACE) ─── */}
      <section className="flex-1 h-full flex flex-col bg-black/60 overflow-hidden">
        {activeTab === 'preview' ? (
          <div className="flex flex-col h-full w-full overflow-hidden">
            {/* Live Preview Top Browser Bar */}
            <div className="flex flex-wrap items-center justify-between border-b border-white/10 bg-white/[0.03] px-4 py-2.5 text-xs gap-2 shrink-0">
              <div className="flex flex-wrap items-center gap-2 flex-1">
                <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span>ΖΩΝΤΑΝΗ ΠΡΟΕΠΙΣΚΟΠΗΣΗ ΕΦΑΡΜΟΓΗΣ (LIVE)</span>
                </span>

                <button
                  type="button"
                  onClick={() => setIframeKey((k) => k + 1)}
                  className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-black/40 px-2.5 py-1 text-white/70 hover:bg-white/10 hover:text-white transition"
                  title="Ανανέωση προεπισκόπησης (Reload)"
                >
                  <RefreshCw className="h-3 w-3" />
                  <span>Reload</span>
                </button>

                {/* Editable URL Bar */}
                <div className="flex items-center gap-1 rounded-md border border-white/10 bg-black/60 px-2.5 py-1 flex-1 max-w-md focus-within:border-gold/50">
                  <span className="text-[10px] text-white/40">URL:</span>
                  <input
                    type="text"
                    value={previewPath}
                    onChange={(e) => setPreviewPath(e.target.value)}
                    placeholder="/studio/dashboard"
                    className="w-full bg-transparent text-[11px] text-gold font-mono outline-none"
                  />
                </div>

                {/* Quick route switcher buttons */}
                <div className="hidden xl:flex items-center gap-1">
                  {[
                    ['/studio/dashboard', 'Hub'],
                    ['/studio/mind', 'Mind'],
                    ['/studio/generate', 'Images'],
                    ['/studio/video-studio', 'Video'],
                    ['/studio/documents', 'Docs'],
                  ].map(([p, label]) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setPreviewPath(p)}
                      className={`px-2 py-0.5 rounded text-[10px] transition ${
                        previewPath === p ? 'bg-gold text-black font-semibold' : 'bg-white/[0.03] text-white/50 hover:text-white'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Viewport switchers & Popout */}
              <div className="flex items-center gap-2">
                <div className="flex items-center rounded-md border border-white/10 bg-black/40 p-0.5 text-[11px]">
                  <button
                    onClick={() => setViewportMode('desktop')}
                    className={`px-2.5 py-0.5 rounded ${viewportMode === 'desktop' ? 'bg-gold text-black font-semibold' : 'text-white/60 hover:text-white'}`}
                  >
                    Desktop
                  </button>
                  <button
                    onClick={() => setViewportMode('tablet')}
                    className={`px-2.5 py-0.5 rounded ${viewportMode === 'tablet' ? 'bg-gold text-black font-semibold' : 'text-white/60 hover:text-white'}`}
                  >
                    Tablet (768px)
                  </button>
                  <button
                    onClick={() => setViewportMode('mobile')}
                    className={`px-2.5 py-0.5 rounded ${viewportMode === 'mobile' ? 'bg-gold text-black font-semibold' : 'text-white/60 hover:text-white'}`}
                  >
                    Mobile (375px)
                  </button>
                </div>

                <a
                  href={previewPath}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 rounded-md border border-gold/30 bg-gold/10 px-2.5 py-1 text-xs text-gold hover:bg-gold hover:text-black transition font-semibold"
                  title="Άνοιγμα σε πλήρη οθόνη σε νέα καρτέλα"
                >
                  <span>Πλήρης Οθόνη ↗</span>
                </a>
              </div>
            </div>

            {/* Live Interactive Iframe */}
            <div className="flex-1 w-full bg-black flex items-center justify-center overflow-auto p-2">
              <iframe
                key={iframeKey}
                src={previewPath}
                title="LUMINA Application Live Preview"
                className={`h-full border-0 rounded bg-background transition-all duration-300 shadow-2xl ${
                  viewportMode === 'desktop' ? 'w-full' : viewportMode === 'tablet' ? 'w-[768px]' : 'w-[375px]'
                }`}
              />
            </div>
          </div>
        ) : (
          <div className="flex-1 w-full overflow-y-auto p-4 lg:p-6">
            <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
              <span className="text-sm font-bold text-white capitalize">
                {activeTab === 'plan' ? 'Πλάνο & Proposed Diff' : activeTab === 'review' ? 'AI Review & Έλεγχος' : 'Live Events'}
              </span>
              <button
                type="button"
                onClick={() => setActiveTab('preview')}
                className="inline-flex items-center gap-1 rounded-md bg-gold/15 border border-gold/40 px-3 py-1 text-xs font-semibold text-gold hover:bg-gold hover:text-black transition"
              >
                ← Επιστροφή στην Ζωντανή Προεπισκόπηση
              </button>
            </div>

        {activeTab === 'plan' && (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.7fr)] max-w-[1700px] mx-auto">
            <div className="space-y-6">
              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <div className="flex items-center gap-2">
                  <Code2 className="h-4 w-4 text-gold" />
                  <h3 className="text-sm font-medium text-white">Implementation plan</h3>
                </div>
                {!plan ? (
                  <p className="mt-4 text-sm text-white/40">
                    {task?.phase === 'awaiting_approval' ? 'No structured plan was returned.' : 'Repository analysis and planning are in progress…'}
                  </p>
                ) : (
                  <>
                    <h4 className="mt-4 font-display text-2xl text-white">{plan.title || 'Prepared implementation'}</h4>
                    <p className="mt-2 text-sm leading-relaxed text-white/55">{plan.summary || plan.objective}</p>
                    <div className="mt-5 space-y-2">
                      {planFiles.map((file) => (
                        <div key={`${file.operation}:${file.path}`} className="rounded-lg border border-white/[0.07] bg-black/15 px-4 py-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <FileCode2 className="h-4 w-4 text-gold" />
                            <code className="text-xs text-white/80">{file.path}</code>
                            <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-white/40">
                              {file.operation}
                            </span>
                          </div>
                          {file.summary && <p className="mt-2 text-xs leading-relaxed text-white/40">{file.summary}</p>}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </section>

              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <FileCode2 className="h-4 w-4 text-gold" />
                    <h3 className="text-sm font-medium text-white">Proposed diff</h3>
                  </div>
                  <span className="text-[11px] text-white/35">{diffs.length} file diff{diffs.length === 1 ? '' : 's'}</span>
                </div>
                {!diffs.length ? (
                  <p className="mt-4 text-sm text-white/40">No validated diff is available yet.</p>
                ) : (
                  <div className="mt-4 space-y-4">
                    {diffs.map((item, index) => (
                      <div key={`${item.path}:${index}`} className="overflow-hidden rounded-lg border border-white/[0.08]">
                        <div className="border-b border-white/[0.07] bg-white/[0.025] px-3 py-2">
                          <code className="text-[11px] text-white/55">{item.path}</code>
                        </div>
                        <pre className="max-h-[520px] overflow-auto bg-black/35 p-4 text-[11px] leading-relaxed text-white/70">
                          <code>{item.diff}</code>
                        </pre>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>

            <aside className="space-y-6">
              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <h3 className="text-sm font-medium text-white">Approval gate</h3>
                <p className="mt-2 text-xs leading-relaxed text-white/45">
                  Approve only the prepared, validated and reviewed patch shown here. Approval starts the protected backup → apply → verification pipeline.
                </p>
                <textarea
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  rows={3}
                  placeholder="Optional approval note"
                  className="mt-4 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-none placeholder:text-white/25 focus:border-gold/40"
                />
                <div className="mt-4 grid grid-cols-2 gap-2">
                  <button
                    data-testid="code-builder-reject"
                    onClick={() => decide('reject')}
                    disabled={!canApprove || busy}
                    className="inline-flex items-center justify-center gap-2 rounded-md border border-red-400/20 px-3 py-2.5 text-xs text-red-100 disabled:opacity-30"
                  >
                    <XCircle className="h-4 w-4" />
                    Reject
                  </button>
                  <button
                    data-testid="code-builder-approve"
                    onClick={() => decide('approve')}
                    disabled={!canApprove || busy}
                    className="inline-flex items-center justify-center gap-2 rounded-md bg-gold px-3 py-2.5 text-xs font-medium text-black disabled:opacity-30"
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Approve & apply
                  </button>
                </div>
              </section>
            </aside>
          </div>
        )}

        {activeTab === 'review' && (
          <div className="space-y-6 max-w-[1700px] mx-auto">
            <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-gold" />
                <h3 className="text-sm font-medium text-white">Validation</h3>
              </div>
              <pre className="mt-4 max-h-72 overflow-auto rounded-lg border border-white/[0.07] bg-black/25 p-4 text-[11px] leading-relaxed text-white/60">
                {pretty(preparation?.patch_validation) || 'Validation results will appear after preparation.'}
              </pre>
            </section>

            <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="code-builder-ai-review">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-gold" />
                  <h3 className="text-sm font-medium text-white">AI review</h3>
                </div>
                {review && <ReviewBadge review={review} />}
              </div>
              <p className="mt-2 text-xs leading-relaxed text-white/40">
                Independent read-only review of the prepared plan, diff and validation.
              </p>
              <pre className="mt-4 max-h-80 overflow-auto rounded-lg border border-white/[0.07] bg-black/25 p-4 text-[11px] leading-relaxed text-white/65">
                {review?.summary || 'AI review will appear before approval becomes available.'}
              </pre>
            </section>

            {(verification || task?.rollback_result) && (
              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="code-builder-verification">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-gold" />
                  <h3 className="text-sm font-medium text-white">Post-apply verification</h3>
                </div>
                {verification && (
                  <>
                    <p className="mt-4 text-[10px] uppercase tracking-[0.16em] text-white/35">Build / tests</p>
                    <pre className="mt-2 max-h-80 overflow-auto rounded-lg border border-white/[0.07] bg-black/25 p-4 text-[11px] leading-relaxed text-white/65">
                      {pretty(verification)}
                    </pre>
                  </>
                )}
                {task?.rollback_result && (
                  <>
                    <p className="mt-4 text-[10px] uppercase tracking-[0.16em] text-white/35">Rollback</p>
                    <pre className="mt-2 max-h-80 overflow-auto rounded-lg border border-white/[0.07] bg-black/25 p-4 text-[11px] leading-relaxed text-white/65">
                      {pretty(task.rollback_result)}
                    </pre>
                  </>
                )}
              </section>
            )}

            {resultStatus && (
              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="code-builder-result-summary">
                <h3 className="font-display text-2xl text-white">{resultStatus}</h3>
                <p className="mt-2 text-base leading-relaxed text-white/65">
                  {task?.phase === 'completed'
                    ? 'The approved changes passed the configured verification pipeline.'
                    : task?.error_message || 'The task lifecycle has ended.'}
                </p>
              </section>
            )}
          </div>
        )}

        {activeTab === 'events' && (
          <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5 max-w-[1700px] mx-auto">
            <h3 className="text-sm font-medium text-white">Execution history</h3>
            <div className="mt-4 max-h-[600px] space-y-3 overflow-auto pr-1">
              {(task?.events || []).length ? (
                [...task.events].reverse().map((event, index) => (
                  <div key={`${event.sequence || index}:${event.timestamp_epoch || index}`} className="border-l border-gold/40 pl-3">
                    <div className="flex flex-wrap gap-2 text-[10px] uppercase tracking-wider text-white/40">
                      <span className="text-gold font-bold">{event.stage || event.type || 'event'}</span>
                      <span>{event.status || ''}</span>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-white/70">{event.message}</p>
                  </div>
                ))
              ) : (
                <p className="text-xs text-white/35">No events yet.</p>
              )}
            </div>
          </section>
        )}
          </div>
        )}
      </section>
    </div>
  );
}