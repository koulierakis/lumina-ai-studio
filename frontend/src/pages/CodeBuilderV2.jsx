import { useCallback, useEffect, useMemo, useState } from 'react';

const API = '/api/code-builder-v2';

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function StatusBadge({ status }) {
  const label = (status || 'idle').replaceAll('_', ' ');
  return <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.18em] text-zinc-300">{label}</span>;
}

export default function CodeBuilderV2() {
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState('qwen2.5-coder:7b');
  const [task, setTask] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    if (!task?.id) return;
    try {
      const next = await api(`/tasks/${task.id}`);
      setTask(next);
    } catch (err) {
      setError(err.message);
    }
  }, [task?.id]);

  useEffect(() => {
    if (!task?.id || !['queued', 'planning', 'executing', 'validating'].includes(task.status)) return undefined;
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, [task?.id, task?.status, refresh]);

  const canExecute = task?.status === 'awaiting_approval';
  const canCancel = task && !['completed', 'failed', 'cancelled', 'rolled_back'].includes(task.status);
  const canRollback = task?.status === 'completed' && task?.execution?.backup_id;
  const elapsed = useMemo(() => {
    if (!task?.created_at) return null;
    return Math.max(0, Math.floor((Date.now() - new Date(task.created_at).getTime()) / 1000));
  }, [task?.created_at, task?.updated_at]);

  async function createTask(event) {
    event.preventDefault();
    if (prompt.trim().length < 3) return;
    setBusy(true);
    setError('');
    try {
      const created = await api('/tasks', {
        method: 'POST',
        body: JSON.stringify({ prompt: prompt.trim(), model: model.trim() || null, auto_apply: false, timeout_seconds: 300 }),
      });
      setTask(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function action(name) {
    if (!task?.id) return;
    setBusy(true);
    setError('');
    try {
      setTask(await api(`/tasks/${task.id}/${name}`, { method: 'POST' }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 text-zinc-100 sm:px-6 lg:px-8">
      <div className="mb-8 flex flex-col gap-4 border-b border-white/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="mb-2 text-xs uppercase tracking-[0.28em] text-cyan-400">Lumina Developer Studio</p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Code Builder V2</h1>
          <p className="mt-2 max-w-2xl text-sm text-zinc-400">Plan → approval → atomic changes → validation → rollback.</p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={task?.status} />
          {elapsed !== null && <span className="text-xs text-zinc-500">{elapsed}s</span>}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,.95fr)]">
        <section className="rounded-2xl border border-white/10 bg-zinc-950/60 p-5 shadow-2xl shadow-black/20">
          <form onSubmit={createTask} className="space-y-4">
            <div>
              <label className="mb-2 block text-sm text-zinc-300">Τι θέλεις να φτιάξει ή να διορθώσει;</label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={10}
                className="w-full resize-y rounded-xl border border-white/10 bg-black/30 p-4 text-sm leading-6 outline-none ring-0 placeholder:text-zinc-600 focus:border-cyan-500/50"
                placeholder="Π.χ. Δημιούργησε endpoint /health-details και πρόσθεσε tests..."
              />
            </div>
            <div>
              <label className="mb-2 block text-sm text-zinc-300">Model</label>
              <input value={model} onChange={(e) => setModel(e.target.value)} className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm outline-none focus:border-cyan-500/50" />
            </div>
            <button disabled={busy || prompt.trim().length < 3} className="w-full rounded-xl bg-cyan-500 px-4 py-3 font-medium text-black transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-40">
              {busy ? 'Working…' : 'Create plan'}
            </button>
          </form>

          {error && <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}

          {task?.error && <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{task.error}</div>}

          {task && (
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <button disabled={!canExecute || busy} onClick={() => action('execute')} className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200 disabled:opacity-30">Execute</button>
              <button disabled={!canCancel || busy} onClick={() => action('cancel')} className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200 disabled:opacity-30">Cancel</button>
              <button disabled={!canRollback || busy} onClick={() => action('rollback')} className="rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-200 disabled:opacity-30">Rollback</button>
              <button disabled={!task?.id || busy} onClick={refresh} className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-300 disabled:opacity-30">Refresh</button>
            </div>
          )}
        </section>

        <section className="space-y-6">
          <div className="rounded-2xl border border-white/10 bg-zinc-950/60 p-5">
            <h2 className="mb-4 text-sm font-medium uppercase tracking-[0.18em] text-zinc-400">Plan</h2>
            {!task?.plan ? <p className="text-sm text-zinc-600">No plan yet.</p> : (
              <div className="space-y-4">
                <p className="text-sm leading-6 text-zinc-300">{task.plan.summary}</p>
                <div className="space-y-2">
                  {task.plan.changes.map((change, index) => (
                    <div key={`${change.path}-${index}`} className="rounded-xl border border-white/10 bg-black/20 p-3">
                      <div className="flex items-center justify-between gap-3">
                        <code className="break-all text-xs text-cyan-300">{change.path}</code>
                        <span className="text-[10px] uppercase tracking-wider text-zinc-500">{change.operation}</span>
                      </div>
                      <p className="mt-2 text-xs text-zinc-500">{change.reason}</p>
                    </div>
                  ))}
                </div>
                {task.plan.validation_commands?.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-wider text-zinc-500">Validation</p>
                    {task.plan.validation_commands.map((command) => <code key={command} className="mb-2 block rounded-lg bg-black/30 px-3 py-2 text-xs text-zinc-400">{command}</code>)}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-white/10 bg-zinc-950/60 p-5">
            <h2 className="mb-4 text-sm font-medium uppercase tracking-[0.18em] text-zinc-400">Live activity</h2>
            <div className="max-h-80 space-y-3 overflow-auto pr-1">
              {(task?.events || []).slice().reverse().map((event, index) => (
                <div key={`${event.at}-${index}`} className="border-l border-white/10 pl-3">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-zinc-300">{event.phase.replaceAll('_', ' ')}</span>
                    <span className="text-zinc-600">{new Date(event.at).toLocaleTimeString()}</span>
                  </div>
                  <p className="mt-1 text-xs text-zinc-500">{event.message}</p>
                </div>
              ))}
              {!task?.events?.length && <p className="text-sm text-zinc-600">Nothing running.</p>}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
