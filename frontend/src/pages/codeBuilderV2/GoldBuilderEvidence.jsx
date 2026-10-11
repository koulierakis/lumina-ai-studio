import { useEffect, useState } from 'react';
import { ACTIVE, gb } from './goldBuilderApi';

const box = 'rounded-2xl border border-white/10 bg-zinc-950/60 p-5';
const h2 = 'mb-4 text-sm font-medium uppercase tracking-[0.18em] text-zinc-400';
const tone = { pass: 'text-emerald-300', passed: 'text-emerald-300', fail: 'text-red-300', failed: 'text-red-300', not_configured: 'text-zinc-500', not_applicable: 'text-zinc-500' };

function Header({ job }) {
  const providers = [...new Set((job.logs || []).filter((l) => l.phase === 'provider').map((l) => (l.message.match(/Contacting (\S+?)…/) || [])[1]).filter(Boolean))];
  return (
    <div className={box} data-testid="gb-job-header">
      <div className="flex flex-wrap items-center gap-3">
        <span data-testid="gb-job-status" className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.18em] text-zinc-200">{job.status}</span>
        <span data-testid="gb-job-progress" className="text-xs text-zinc-500">{job.progress}%</span>
        <code className="text-[11px] text-zinc-600">{job.id}</code>
      </div>
      {job.plan && <p className="mt-3 text-sm text-zinc-300">{job.plan.app_name} · stack <code>{job.plan.stack_id}</code> · {job.plan.tasks.length} planned task(s)</p>}
      <p data-testid="gb-providers-used" className="mt-2 text-xs text-zinc-500">Providers contacted: {providers.join(' → ') || '—'}</p>
      {job.error && <div data-testid="gb-job-error" className="mt-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200 whitespace-pre-wrap">{job.error}</div>}
    </div>
  );
}

function Gates({ job }) {
  const gates = job.gates || [];
  const repairs = job.repair_history || [];
  return (
    <div className={box} data-testid="gb-gates">
      <h2 className={h2}>Stages &amp; gates</h2>
      {!gates.length && <p className="text-sm text-zinc-600">No gate results yet.</p>}
      {gates.map((g) => (
        <div key={g.name} className="flex justify-between gap-3 border-b border-white/5 py-1 text-xs">
          <span className="text-zinc-300">{g.name}</span>
          <span className={tone[String(g.status).toLowerCase()] || 'text-amber-300'} title={g.detail || ''}>{g.status}{g.blocking ? ' · blocking' : ''}</span>
        </div>
      ))}
      {repairs.length > 0 && <p data-testid="gb-repair-count" className="mt-3 text-xs text-amber-200">Repair attempts: {repairs.length} · resolved: {repairs.filter((r) => r.resolved).length}</p>}
    </div>
  );
}

function Verification({ job }) {
  const v = job.verification;
  if (!v) return null;
  return (
    <div className={box} data-testid="gb-verification">
      <h2 className={h2}>Browser verification (Playwright)</h2>
      <p data-testid="gb-verification-result" className={v.passed ? 'text-sm text-emerald-300' : 'text-sm text-red-300'}>{v.passed ? 'PASSED' : 'FAILED'} · HTTP {v.http_status ?? '—'} · {v.title || ''}</p>
      {v.error && <p className="mt-2 text-xs text-red-300">{v.error}</p>}
      <div className="mt-3 max-h-48 overflow-auto text-xs">
        {(v.steps || []).map((s) => <div key={s.index} className={s.ok ? 'text-zinc-400' : 'text-red-300'}>{s.ok ? '✓' : '✗'} {s.action} {JSON.stringify(s.args)} {s.error || ''}</div>)}
      </div>
    </div>
  );
}

function Preview({ job }) {
  const [url, setUrl] = useState('');
  const [shot, setShot] = useState('');
  const [msg, setMsg] = useState('');
  const terminal = !ACTIVE.includes(job.status) && job.status !== 'pending';
  useEffect(() => {
    if (!terminal || !job.verification) return undefined;
    let objectUrl = '';
    gb.blob(`/jobs/${job.id}/screenshot`).then((b) => { objectUrl = URL.createObjectURL(b); setShot(objectUrl); }).catch(() => setShot(''));
    return () => objectUrl && URL.revokeObjectURL(objectUrl);
  }, [terminal, job.id, job.verification, job.updated_at]);
  const open = async () => {
    setMsg('');
    try {
      await gb.session();
      const info = (await gb.preview(job.id)).running ? await gb.preview(job.id) : await gb.startPreview(job.id);
      setUrl(`${info.proxy_url}?t=${Date.now()}`);
    } catch (err) { setMsg(err.message); }
  };
  return (
    <div className={box} data-testid="gb-preview">
      <div className="mb-4 flex items-center justify-between"><h2 className={h2.replace('mb-4 ', '')}>Live preview</h2>
        <button data-testid="gb-open-preview-btn" disabled={!terminal || !job.plan} onClick={open} className="rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-xs text-zinc-200 disabled:opacity-30">Open preview</button></div>
      {msg && <p data-testid="gb-preview-error" className="text-xs text-red-300">{msg}</p>}
      {url && <iframe data-testid="gb-preview-iframe" title="Gold Builder preview" src={url} className="h-[520px] w-full rounded-xl border border-white/10 bg-white" />}
      {shot && <img data-testid="gb-screenshot" alt="Verifier screenshot" src={shot} className="mt-3 w-full rounded-xl border border-white/10" />}
    </div>
  );
}

function Logs({ job }) {
  return (
    <div className={box} data-testid="gb-live-logs">
      <h2 className={h2}>Live activity ({job.logs?.length || 0})</h2>
      <div className="max-h-80 space-y-2 overflow-auto pr-1 font-mono text-[11px]">
        {(job.logs || []).slice().reverse().map((l, i) => (
          <div key={`${l.ts}-${i}`} className={l.level === 'error' ? 'text-red-300' : l.level === 'warn' ? 'text-amber-200' : 'text-zinc-400'}>
            <span className="text-zinc-600">{new Date(l.ts).toLocaleTimeString()} </span><span className="text-zinc-200">[{l.phase}]</span> {l.message}
          </div>
        ))}
      </div>
    </div>
  );
}

function Files({ job }) {
  return (
    <div className={box} data-testid="gb-files">
      <h2 className={h2}>Generated files ({job.files?.length || 0})</h2>
      {(job.files || []).map((f) => <code key={f.path} className="block text-xs text-amber-200">{f.path}</code>)}
    </div>
  );
}

export function JobEvidence({ job }) {
  return (<><Header job={job} /><Preview job={job} /><Verification job={job} /><Gates job={job} /><Files job={job} /><Logs job={job} /></>);
}
