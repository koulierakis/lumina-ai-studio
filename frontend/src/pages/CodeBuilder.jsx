import { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, CircleAlert, Code2, FileCode2, Loader2, Play, RefreshCw, RotateCcw, ShieldCheck, XCircle } from 'lucide-react';
import { apiGet, apiPost } from '../lib/api';

const TERMINAL_PHASES = new Set(['completed', 'failed', 'cancelled', 'timed_out', 'rolled_back', 'rollback_failed']);

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

export default function CodeBuilder() {
  const [instruction, setInstruction] = useState('');
  const [task, setTask] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [comment, setComment] = useState('');

  const refresh = useCallback(async (taskId = task?.task_id) => {
    if (!taskId) return;
    try {
      const detail = await apiGet(`/code-builder/tasks/${taskId}`, { retry: false });
      setTask(detail);
      setError('');
    } catch (err) {
      setError(err?.message || 'Could not refresh Code Builder task.');
    }
  }, [task?.task_id]);

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

  const preparation = task?.preparation_result;
  const plan = preparation?.plan;
  const planFiles = useMemo(() => collectPlanFiles(plan), [plan]);
  const diffs = useMemo(() => collectDiffs(preparation), [preparation]);
  const canApprove = task?.phase === 'awaiting_approval' && Boolean(preparation?.patch) && Boolean(preparation?.patch_validation);
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
          {task && <div className="flex items-center gap-2"><StatusPill phase={task.phase} /><button onClick={() => refresh()} className="rounded-md border border-white/10 p-2 text-white/55 hover:text-white" title="Refresh"><RefreshCw className="h-4 w-4" /></button></div>}
        </header>

        <section className="mt-8 rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
          <label className="text-[11px] uppercase tracking-[0.2em] text-white/45" htmlFor="code-builder-instruction">Development instruction</label>
          <textarea id="code-builder-instruction" data-testid="code-builder-instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={4} placeholder="Improve Document Studio so that…" className="mt-3 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-sm leading-relaxed text-white outline-none placeholder:text-white/25 focus:border-gold/40" />
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs text-white/40"><ShieldCheck className="h-4 w-4 text-gold" />No production writes before explicit approval.</div>
            <button data-testid="code-builder-create" onClick={createTask} disabled={!instruction.trim() || busy} className="inline-flex items-center gap-2 rounded-md bg-gold px-4 py-2.5 text-xs font-medium text-black disabled:cursor-not-allowed disabled:opacity-40"><Play className="h-4 w-4" />Analyze & prepare</button>
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
            </div>

            <aside className="space-y-6">
              <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
                <h3 className="text-sm font-medium text-white">Approval gate</h3>
                <p className="mt-2 text-xs leading-relaxed text-white/45">Approve only the prepared and validated patch shown here. Approval starts the protected backup → apply → verification pipeline.</p>
                <textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} placeholder="Optional approval note" className="mt-4 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-none placeholder:text-white/25 focus:border-gold/40" />
                <div className="mt-4 grid grid-cols-2 gap-2"><button data-testid="code-builder-reject" onClick={() => decide('reject')} disabled={!canApprove || busy} className="inline-flex items-center justify-center gap-2 rounded-md border border-red-400/20 px-3 py-2.5 text-xs text-red-100 disabled:opacity-30"><XCircle className="h-4 w-4" />Reject</button><button data-testid="code-builder-approve" onClick={() => decide('approve')} disabled={!canApprove || busy} className="inline-flex items-center justify-center gap-2 rounded-md bg-gold px-3 py-2.5 text-xs font-medium text-black disabled:opacity-30"><CheckCircle2 className="h-4 w-4" />Approve & apply</button></div>
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
