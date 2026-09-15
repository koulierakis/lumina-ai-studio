import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  CircleAlert,
  Code2,
  FileCode2,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  XCircle,
} from 'lucide-react';
import { apiGet, apiPost } from '../lib/api';

const TERMINAL_PHASES = new Set([
  'completed',
  'failed',
  'cancelled',
  'timed_out',
  'rolled_back',
  'rollback_failed',
]);
const ACTIVE_PHASES = new Set([
  'queued',
  'analyzing',
  'planning',
  'validating',
  'awaiting_approval',
  'approved',
  'applying',
  'verifying',
  'executing',
  'rolling_back',
]);
const LAST_TASK_STORAGE_KEY = 'lumina_code_builder_last_task_id';

function pretty(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function collectDiffs(preparation) {
  const validation = preparation?.patch_validation;
  const results = Array.isArray(validation?.results) ? validation.results : [];
  return results
    .map((item) => ({
      path: item?.path || item?.relative_path || 'proposed change',
      diff: item?.diff || '',
    }))
    .filter((item) => item.diff);
}

function collectPlanFiles(plan) {
  const files = Array.isArray(plan?.files) ? plan.files : [];
  return files.map((file) => ({
    path: file?.path || file?.file_path || 'unknown',
    operation: file?.operation || 'modify',
    summary: file?.summary || file?.rationale || '',
  }));
}

function phaseLabel(phase) {
  return String(phase || 'unknown').replaceAll('_', ' ');
}

function StatusPill({ phase }) {
  const terminal = TERMINAL_PHASES.has(phase);
  const good = phase === 'completed' || phase === 'rolled_back';
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.16em] ${
        good
          ? 'border-emerald-400/25 text-emerald-200'
          : terminal
          ? 'border-red-400/25 text-red-200'
          : 'border-gold/25 text-gold'
      }`}
    >
      {terminal ? (
        good ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleAlert className="h-3.5 w-3.5" />
      ) : (
        <Loader2 className="h-3.5 w-3.5" />
      )}
      {phaseLabel(phase)}
    </span>
  );
}

function ReviewBadge({ review }) {
  const verdict = review?.verdict || review?.status || 'pending';
  const tone =
    verdict === 'pass'
      ? 'border-emerald-400/25 text-emerald-200'
      : verdict === 'block'
      ? 'border-red-400/25 text-red-200'
      : verdict === 'warn'
      ? 'border-amber-300/25 text-amber-100'
      : 'border-white/10 text-white/45';
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] ${tone}`}>
      {verdict}
    </span>
  );
}

export default function CodeBuilder() {
  const [instruction, setInstruction] = useState('');
  const [task, setTask] = useState(null);
  const [recoveryCandidate, setRecoveryCandidate] = useState(null);
  const [recoveryChecked, setRecoveryChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [comment, setComment] = useState('');

  const rememberTask = useCallback((nextTask) => {
    setTask(nextTask);
    if (nextTask?.task_id) {
      window.localStorage.setItem(LAST_TASK_STORAGE_KEY, nextTask.task_id);
    }
    if (nextTask?.instruction) {
      setInstruction(nextTask.instruction);
    }
  }, []);

  const refresh = useCallback(
    async (taskId = task?.task_id) => {
      if (!taskId) return;
      try {
        const detail = await apiGet(`/code-builder/tasks/${taskId}`, { retry: false });
        rememberTask(detail);
        setError('');
      } catch (err) {
        setError(err?.message || 'Could not refresh Code Builder task.');
      }
    },
    [rememberTask, task?.task_id]
  );

  const findRecoverableTask = useCallback(async () => {
    setRecoveryChecked(false);
    try {
      const rememberedTaskId = window.localStorage.getItem(LAST_TASK_STORAGE_KEY);
      if (rememberedTaskId) {
        try {
          const remembered = await apiGet(`/code-builder/tasks/${rememberedTaskId}`, { retry: false });
          if (ACTIVE_PHASES.has(remembered?.phase)) {
            setRecoveryCandidate(remembered);
            return;
          }
          if (remembered?.phase && TERMINAL_PHASES.has(remembered.phase)) {
            window.localStorage.removeItem(LAST_TASK_STORAGE_KEY);
          }
        } catch {
          window.localStorage.removeItem(LAST_TASK_STORAGE_KEY);
        }
      }

      const response = await apiGet('/code-builder/tasks', {
        params: { limit: 20 },
        retry: false,
      });
      const items = Array.isArray(response?.items) ? response.items : [];
      const active = items.find((item) => ACTIVE_PHASES.has(item?.phase));
      if (active?.task_id) {
        const detail = await apiGet(`/code-builder/tasks/${active.task_id}`, { retry: false });
        setRecoveryCandidate(detail);
      }
    } catch (err) {
      setError(err?.message || 'Could not check for an active Code Builder task.');
    } finally {
      setRecoveryChecked(true);
    }
  }, []);

  useEffect(() => {
    findRecoverableTask();
  }, [findRecoverableTask]);

  useEffect(() => {
    if (!task?.task_id || TERMINAL_PHASES.has(task.phase) || task.phase === 'awaiting_approval') {
      return undefined;
    }
    const timer = window.setInterval(() => refresh(task.task_id), 1500);
    return () => window.clearInterval(timer);
  }, [task?.task_id, task?.phase, refresh]);

  useEffect(() => {
    if (task?.task_id && TERMINAL_PHASES.has(task.phase)) {
      window.localStorage.removeItem(LAST_TASK_STORAGE_KEY);
    }
  }, [task?.task_id, task?.phase]);

  const continueRecoveredTask = async () => {
    if (!recoveryCandidate?.task_id || busy) return;
    setBusy(true);
    setError('');
    try {
      const detail = await apiGet(`/code-builder/tasks/${recoveryCandidate.task_id}`, { retry: false });
      rememberTask(detail);
      setRecoveryCandidate(null);
    } catch (err) {
      setError(err?.message || 'Could not reconnect to the active Code Builder task.');
    } finally {
      setBusy(false);
    }
  };

  const leaveRecoveredTaskRunning = () => {
    if (recoveryCandidate?.task_id) {
      window.localStorage.setItem(LAST_TASK_STORAGE_KEY, recoveryCandidate.task_id);
    }
    setRecoveryCandidate(null);
  };

  const cancelAndResetRecoveredTask = async () => {
    if (!recoveryCandidate?.task_id || busy) return;
    setBusy(true);
    setError('');
    try {
      await apiPost(`/code-builder/tasks/${recoveryCandidate.task_id}/cancel`, {
        reason: 'Cancelled from Code Builder recovery prompt after reconnect.',
      });
      window.localStorage.removeItem(LAST_TASK_STORAGE_KEY);
      setRecoveryCandidate(null);
      setTask(null);
      setInstruction('');
      setComment('');
    } catch (err) {
      setError(err?.responseData?.detail?.message || err?.message || 'Could not cancel the active task.');
    } finally {
      setBusy(false);
    }
  };

  const createTask = async () => {
    const value = instruction.trim();
    if (!value || busy) return;
    if (recoveryCandidate?.task_id) {
      setError('An active Code Builder task already exists. Continue it or cancel and reset it before starting another task.');
      return;
    }
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
      rememberTask(response.task);
    } catch (err) {
      setError(err?.message || 'Could not create Code Builder task.');
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
      rememberTask(response.task);
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
      const response = await apiPost(`/code-builder/tasks/${task.task_id}/rollback`, {
        reason: 'Manual rollback from Code Builder UI.',
        force: false,
      });
      rememberTask(response.task);
    } catch (err) {
      setError(err?.responseData?.detail?.message || err?.message || 'Rollback failed.');
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
  const reviewAllowsApproval = review?.status === 'completed' && ['pass', 'warn'].includes(review?.verdict);
  const reviewBlocked = review?.verdict === 'block';
  const reviewUnavailable = Boolean(review) && !reviewAllowsApproval && !reviewBlocked;
  const canReject = task?.phase === 'awaiting_approval';
  const canApprove = task?.phase === 'awaiting_approval' && Boolean(preparation?.patch) && Boolean(preparation?.patch_validation) && reviewAllowsApproval;
  const canRollback = ['completed', 'failed', 'cancelled', 'timed_out', 'rollback_failed'].includes(task?.phase);

  return (
    <main className="min-h-screen w-full overflow-y-auto" data-testid="code-builder-page">
      <div className="mx-auto max-w-[1500px] p-6 sm:p-10">
        <header className="flex flex-col gap-5 border-b border-white/[0.07] pb-8 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] uppercase tracking-[0.28em] text-gold">Repository-native development</p>
            <h2 className="mt-2 font-display text-4xl tracking-tight text-white sm:text-5xl">Code Builder</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-white/50">Analyze, plan and review proposed repository changes before any production file is written. Approval is the transaction boundary.</p>
          </div>
          {task && (
            <div className="flex items-center gap-2">
              <StatusPill phase={task.phase} />
              <button onClick={() => refresh()} className="rounded-md border border-white/10 p-2 text-white/55 hover:text-white" title="Refresh">
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>
          )}
        </header>

        {!recoveryChecked && !task && (
          <div className="mt-6 flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-4 py-3 text-sm text-white/45" data-testid="code-builder-recovery-checking">
            <Loader2 className="h-4 w-4" />Checking for active Code Builder work…
          </div>
        )}

        {recoveryCandidate && !task && (
          <section className="mt-6 rounded-xl border border-gold/30 bg-gold/[0.05] p-5" data-testid="code-builder-recovery-prompt">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.2em] text-gold">Active task found</p>
                <h3 className="mt-2 font-display text-2xl text-white">Code Builder is still working</h3>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-white/55">
                  A previous task is still in <strong className="font-medium text-white/80">{phaseLabel(recoveryCandidate.phase)}</strong>. Reconnect to the same task, leave it running in the background, or cancel it and reset the workspace.
                </p>
                <p className="mt-3 line-clamp-3 text-xs leading-relaxed text-white/40">{recoveryCandidate.instruction}</p>
              </div>
              <StatusPill phase={recoveryCandidate.phase} />
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              <button data-testid="code-builder-recovery-continue" onClick={continueRecoveredTask} disabled={busy} className="inline-flex items-center gap-2 rounded-md bg-gold px-4 py-2.5 text-xs font-medium text-black disabled:opacity-40">
                <Play className="h-4 w-4" />Continue / open task
              </button>
              <button data-testid="code-builder-recovery-background" onClick={leaveRecoveredTaskRunning} disabled={busy} className="inline-flex items-center gap-2 rounded-md border border-white/10 px-4 py-2.5 text-xs text-white/65 disabled:opacity-40">
                Keep running in background
              </button>
              <button data-testid="code-builder-recovery-reset" onClick={cancelAndResetRecoveredTask} disabled={busy} className="inline-flex items-center gap-2 rounded-md border border-red-400/25 px-4 py-2.5 text-xs text-red-100 disabled:opacity-40">
                <XCircle className="h-4 w-4" />Cancel & reset
              </button>
            </div>
          </section>
        )}

        <section className="mt-8 rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
          <label className="text-[11px] uppercase tracking-[0.2em] text-white/45" htmlFor="code-builder-instruction">Development instruction</label>
          <textarea id="code-builder-instruction" data-testid="code-builder-instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={4} placeholder="Improve Document Studio so that…" className="mt-3 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-sm leading-relaxed text-white outline-none placeholder:text-white/25 focus:border-gold/40" />
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs text-white/40"><ShieldCheck className="h-4 w-4 text-gold" />No production writes before explicit approval.</div>
            <button data-testid="code-builder-create" onClick={createTask} disabled={!instruction.trim() || busy || Boolean(recoveryCandidate)} className="inline-flex items-center gap-2 rounded-md bg-gold px-4 py-2.5 text-xs font-medium text-black disabled:cursor-not-allowed disabled:opacity-40"><Play className="h-4 w-4" />Analyze & prepare</button>
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
            </div>

            <aside className="space-y-6">
              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <h3 className="text-sm font-medium text-white">Approval gate</h3>
                <p className="mt-2 text-xs leading-relaxed text-white/45">Approve only the prepared, validated and reviewed patch shown here. Approval starts the protected backup → apply → verification pipeline.</p>
                {reviewBlocked && <div data-testid="code-builder-review-blocked" className="mt-3 rounded-md border border-red-400/20 bg-red-400/5 px-3 py-2 text-xs leading-relaxed text-red-100">The independent review blocked this change. Revise the task before approval.</div>}
                {reviewUnavailable && <div data-testid="code-builder-review-unavailable" className="mt-3 rounded-md border border-amber-300/20 bg-amber-300/5 px-3 py-2 text-xs leading-relaxed text-amber-100">The independent review did not complete successfully. Approval stays locked until a valid review is available.</div>}
                <textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} placeholder="Optional approval note" className="mt-4 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-none placeholder:text-white/25 focus:border-gold/40" />
                <div className="mt-4 grid grid-cols-2 gap-2"><button data-testid="code-builder-reject" onClick={() => decide('reject')} disabled={!canReject || busy} className="inline-flex items-center justify-center gap-2 rounded-md border border-red-400/20 px-3 py-2.5 text-xs text-red-100 disabled:opacity-30"><XCircle className="h-4 w-4" />Reject</button><button data-testid="code-builder-approve" onClick={() => decide('approve')} disabled={!canApprove || busy} className="inline-flex items-center justify-center gap-2 rounded-md bg-gold px-3 py-2.5 text-xs font-medium text-black disabled:opacity-30"><CheckCircle2 className="h-4 w-4" />Approve & apply</button></div>
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
