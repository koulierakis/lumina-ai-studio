import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, CircleAlert, Code2, FileCode2, Loader2, Mic, MicOff, Play, RefreshCw, RotateCcw, ShieldCheck, Sparkles, XCircle } from 'lucide-react';
import { apiGet, apiPost } from '../lib/api';

const TERMINAL_PHASES = new Set(['completed', 'failed', 'cancelled', 'timed_out', 'rolled_back', 'rollback_failed']);
const DRAFT_STORAGE_KEY = 'lumina_code_builder_instruction';

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

  return (
    <main className="min-h-screen w-full overflow-y-auto" data-testid="code-builder-page">
      <div className="mx-auto max-w-[1500px] p-6 sm:p-10">
        <header className="flex flex-col gap-5 border-b border-white/[0.07] pb-8 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-gold">Repository-native development</p>
            <h2 className="mt-2 font-display text-4xl tracking-tight text-white sm:text-5xl">Code Builder</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-white/50">Analyze, plan and review proposed repository changes before any production file is written. Approval is the transaction boundary.</p>
          </div>
          {task && (
    <div className="flex items-center gap-2">
      <StatusPill phase={task.phase} />
      <ProgressInfo phase={task.phase} />
      <ElapsedTime startedAt={task.started_at_epoch} createdAt={task.created_at_epoch} finishedAt={task.finished_at_epoch} phase={task.phase} />
      <button data-testid="code-builder-refresh" onClick={() => refresh()} title="Refresh task status" className="inline-flex items-center gap-2 rounded-border px-2 py-1 text-xs text-white/60 hover:text-white hover:bg-gold/10">
        <RefreshCw className="h-3.5 w-3.5" />
      </button>
    </div>
  )}
        </header>

        <section className="mt-8 rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="text-base font-semibold text-white" htmlFor="code-builder-instruction">Development instruction</label>
            <button type="button" data-testid="code-builder-model-status" onClick={refreshModelStatus} title="Recheck Code Builder model" className={`inline-flex items-center gap-2 text-sm ${modelStatus === 'ready' ? 'text-emerald-200' : 'text-amber-200'}`}><span className="h-2 w-2 rounded-full bg-current" />{modelLabel}<RefreshCw className="h-3.5 w-3.5" /></button>
          </div>
          <div className="mt-3 rounded-lg border border-white/10 bg-black/20 focus-within:border-gold/40">
            <textarea id="code-builder-instruction" data-testid="code-builder-instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); createTask(); } }} rows={5} placeholder="Describe the change you want LUMINA to prepare…" className="w-full resize-y bg-transparent px-4 py-4 text-base leading-relaxed text-white outline-none placeholder:text-white/30" />
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] px-4 py-3">
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" data-testid="code-builder-voice" onClick={toggleVoice} aria-pressed={voiceState === 'listening'} title="Dictate development instruction" className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm font-semibold transition ${voiceState === 'listening' ? 'border-red-300/40 bg-red-400/10 text-red-100' : 'border-white/10 bg-white/[0.05] text-white/75 hover:border-gold/40 hover:text-white'}`}>{voiceState === 'listening' ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}{voiceLabel}</button>
                <label className="flex items-center gap-2 text-sm text-white/55" htmlFor="code-builder-voice-language"><span className="sr-only">Voice language</span><select id="code-builder-voice-language" data-testid="code-builder-voice-language" value={voiceLanguage} onChange={(event) => setVoiceLanguage(event.target.value)} className="rounded-md border border-white/10 bg-white/[0.05] px-2 py-2 text-sm text-white outline-none focus:border-gold/40"><option value="auto">Auto language</option><option value="el-GR">Greek</option><option value="en-US">English</option></select></label>
              </div>
              <span className="text-sm text-white/45">Review before running</span>
            </div>
          </div>
          {voiceMessage && <p data-testid="code-builder-voice-status" className="mt-2 text-sm text-white/55">{voiceMessage}</p>}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm text-white/55"><ShieldCheck className="h-4 w-4 text-gold" />No production writes before explicit approval.</div>
            <button data-testid="code-builder-create" onClick={createTask} disabled={!instruction.trim() || busy} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-gold px-5 py-2.5 text-sm font-bold text-black disabled:cursor-not-allowed disabled:opacity-40"><Play className="h-4 w-4" />{busy ? 'Preparing…' : 'Analyze & prepare'}</button>
          </div>
        </section>

        {error && <div className="mt-5 flex items-start gap-2 rounded-lg border border-red-400/20 bg-red-400/5 px-4 py-3 text-sm text-red-100"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}

        {task && (
          <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.7fr)]">
            <div className="space-y-6">
              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <div className="flex items-center gap-2"><Code2 className="h-4 w-4 text-gold" /><h3 className="text-sm font-medium text-white">Implementation plan</h3></div>
                {!plan ? <p className="mt-4 text-sm text-white/40">{task.phase === 'awaiting_approval' ? 'No structured plan was returned.' : 'Repository analysis and planning are in progress…'}</p> : <>
                  <h4 className="mt-4 font-display text-2xl text-white">{plan.title || 'Prepared implementation'}</h4>
                  <p className="mt-2 text-sm leading-relaxed text-white/55">{plan.summary || plan.objective}</p>
                  <div className="mt-5 space-y-2">{planFiles.map((file) => <div key={`${file.operation}:${file.path}`} className="rounded-lg border border-white/[0.07] bg-black/15 px-4 py-3"><div className="flex flex-wrap items-center gap-2"><FileCode2 className="h-4 w-4 text-gold" /><code className="text-xs text-white/80">{file.path}</code><span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-white/40">{file.operation}</span></div>{file.summary && <p className="mt-2 text-xs leading-relaxed text-white/40">{file.summary}</p>}</div>)}</div>
                </>}
              </section>

              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><FileCode2 className="h-4 w-4 text-gold" /><h3 className="text-sm font-medium text-white">Proposed diff</h3></div><span className="text-[11px] text-white/35">{diffs.length} file diff{diffs.length === 1 ? '' : 's'}</span></div>
                {!diffs.length ? <p className="mt-4 text-sm text-white/40">No validated diff is available yet.</p> : <div className="mt-4 space-y-4">{diffs.map((item, index) => <div key={`${item.path}:${index}`} className="overflow-hidden rounded-lg border border-white/[0.08]"><div className="border-b border-white/[0.07] bg-white/[0.025] px-3 py-2"><code className="text-[11px] text-white/55">{item.path}</code></div><pre className="max-h-[520px] overflow-auto bg-black/35 p-4 text-[11px] leading-relaxed text-white/70"><code>{item.diff}</code></pre></div>)}</div>}
              </section>

              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-gold" /><h3 className="text-sm font-medium text-white">Validation</h3></div>
                <pre className="mt-4 max-h-72 overflow-auto rounded-lg border border-white/[0.07] bg-black/25 p-4 text-[11px] leading-relaxed text-white/60">{pretty(preparation?.patch_validation) || 'Validation results will appear after preparation.'}</pre>
              </section>

              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="code-builder-ai-review">
                <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-gold" /><h3 className="text-sm font-medium text-white">AI review</h3></div>{review && <ReviewBadge review={review} />}</div>
                <p className="mt-2 text-xs leading-relaxed text-white/40">Independent read-only review of the prepared plan, diff and validation. The reviewer cannot write files and does not replace your approval decision.</p>
                <pre className="mt-4 max-h-80 overflow-auto rounded-lg border border-white/[0.07] bg-black/25 p-4 text-[11px] leading-relaxed text-white/65">{review?.summary || 'AI review will appear before approval becomes available.'}</pre>
                {review?.model && <p className="mt-2 text-[10px] uppercase tracking-[0.16em] text-white/30">Model: {review.model}</p>}
              </section>

              {(verification || task?.rollback_result) && <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="code-builder-verification">
                <div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-gold" /><h3 className="text-sm font-medium text-white">Post-apply verification</h3></div>
                <p className="mt-2 text-xs leading-relaxed text-white/40">Results produced only after the approved patch is applied. Rollback information is preserved when verification fails.</p>
                {verification && <><p className="mt-4 text-[10px] uppercase tracking-[0.16em] text-white/35">Build / tests</p><pre className="mt-2 max-h-80 overflow-auto rounded-lg border border-white/[0.07] bg-black/25 p-4 text-[11px] leading-relaxed text-white/65">{pretty(verification)}</pre></>}
                {task?.rollback_result && <><p className="mt-4 text-[10px] uppercase tracking-[0.16em] text-white/35">Rollback</p><pre className="mt-2 max-h-80 overflow-auto rounded-lg border border-white/[0.07] bg-black/25 p-4 text-[11px] leading-relaxed text-white/65">{pretty(task.rollback_result)}</pre></>}
              </section>}

              {resultStatus && <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5" data-testid="code-builder-result-summary">
                <h3 className="font-display text-2xl text-white">{resultStatus}</h3>
                <p className="mt-2 text-base leading-relaxed text-white/65">{task.phase === 'completed' ? 'The approved changes passed the configured verification pipeline.' : task.error_message || 'The task lifecycle has ended. Review the details below for the final outcome.'}</p>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg bg-white/[0.035] p-4"><p className="text-sm font-semibold text-white">Files changed</p><p className="mt-1 text-base text-white/70">{task.changed_paths?.length || taskResult.changed_paths?.length || 'None reported'}</p></div>
                  <div className="rounded-lg bg-white/[0.035] p-4"><p className="text-sm font-semibold text-white">Validation</p><p className="mt-1 text-base text-white/70">{verification?.success === true ? 'Passed' : verification ? 'Needs attention' : 'Not run'}</p></div>
                </div>
                <details className="mt-5 rounded-lg border border-white/[0.07] bg-black/20 p-4"><summary className="cursor-pointer text-base font-semibold text-white/80">View technical details</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm leading-relaxed text-white/60">{pretty(taskResult) || pretty(task.rollback_result) || 'No additional result details.'}</pre></details>
              </section>}
            </div>

            <aside className="space-y-6">
              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <h3 className="text-sm font-medium text-white">Approval gate</h3>
                <p className="mt-2 text-xs leading-relaxed text-white/45">Approve only the prepared, validated and reviewed patch shown here. Approval starts the protected backup → apply → verification pipeline.</p>
                <textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} placeholder="Optional approval note" className="mt-4 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-none placeholder:text-white/25 focus:border-gold/40" />
                <div className="mt-4 grid grid-cols-2 gap-2"><button data-testid="code-builder-reject" onClick={() => decide('reject')} disabled={!canApprove || busy} className="inline-flex items-center justify-center gap-2 rounded-md border border-red-400/20 px-3 py-2.5 text-xs text-red-100 disabled:opacity-30"><XCircle className="h-4 w-4" />Reject</button><button data-testid="code-builder-approve" onClick={() => decide('approve')} disabled={!canApprove || busy} className="inline-flex items-center justify-center gap-2 rounded-md bg-gold px-3 py-2.5 text-xs font-medium text-black disabled:opacity-30"><CheckCircle2 className="h-4 w-4" />Approve & apply</button></div>
                {!TERMINAL_PHASES.has(task.phase) && task.phase !== 'awaiting_approval' && <button data-testid="code-builder-cancel" onClick={cancelTask} disabled={busy} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-red-400/20 px-3 py-2.5 text-xs text-red-100 hover:border-red-400/40 disabled:opacity-30"><XCircle className="h-4 w-4" />Cancel task</button>}
                {canRollback && <button onClick={rollback} disabled={busy} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-white/10 px-3 py-2.5 text-xs text-white/65 hover:text-white disabled:opacity-30"><RotateCcw className="h-4 w-4" />Rollback</button>}
              </section>

              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <h3 className="text-sm font-medium text-white">Execution history</h3>
                <div className="mt-4 max-h-[560px] space-y-3 overflow-auto pr-1">{(task.events || []).length ? [...task.events].reverse().map((event, index) => <div key={`${event.sequence || index}:${event.timestamp_epoch || index}`} className="border-l border-white/10 pl-3"><div className="flex flex-wrap gap-2 text-[10px] uppercase tracking-wider text-white/30"><span>{event.stage || 'event'}</span><span>{event.status || ''}</span></div><p className="mt-1 text-xs leading-relaxed text-white/55">{event.message}</p></div>) : <p className="text-xs text-white/35">No events yet.</p>}</div>
              </section>
            </aside>
          </div>
        )}
      </div>
    </main>
  );
}