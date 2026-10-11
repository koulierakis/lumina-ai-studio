import { useCallback, useEffect, useState } from 'react';
import { ACTIVE, gb } from './goldBuilderApi';
import { JobEvidence } from './GoldBuilderEvidence';

const LAST_JOB_KEY = 'lumina_gb_last_job';
const box = 'rounded-2xl border border-white/10 bg-zinc-950/60 p-5';
const input = 'w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm outline-none focus:border-amber-400/50';
const btn = 'rounded-lg border px-3 py-2 text-sm disabled:opacity-30';

function useJobPolling(jobId, setJob, setError) {
  useEffect(() => {
    if (!jobId) return undefined;
    let stopped = false;
    const tick = async () => {
      try {
        const next = await gb.job(jobId);
        if (!stopped) setJob(next);
      } catch (err) {
        if (!stopped) setError(err.message);
      }
    };
    tick();
    const timer = window.setInterval(tick, 1500);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [jobId, setJob, setError]);
}

function ProviderSelect({ value, onChange }) {
  const [providers, setProviders] = useState([]);
  useEffect(() => { gb.providers().then((list) => setProviders(list.filter((p) => p.kind === 'llm' || p.kind === undefined))).catch(() => setProviders([])); }, []);
  return (
    <select data-testid="gb-provider-select" value={value} onChange={(e) => onChange(e.target.value)} className={input}>
      <option value="">Auto routing (priority + fallback)</option>
      {providers.filter((p) => p.available).map((p) => <option key={p.id} value={p.id}>{p.id}</option>)}
    </select>
  );
}

function StackSelect({ value, onChange }) {
  const [stacks, setStacks] = useState([]);
  useEffect(() => { gb.stacks().then(setStacks).catch(() => setStacks([])); }, []);
  return (
    <select data-testid="gb-stack-select" value={value} onChange={(e) => onChange(e.target.value)} className={input}>
      <option value="">Stack: engine default (html-static)</option>
      {stacks.map((s) => <option key={s.id} value={s.id}>{s.label || s.id}</option>)}
    </select>
  );
}

function RequestForm({ onDraft, busy }) {
  const [request, setRequest] = useState('');
  const [stack, setStack] = useState('');
  const [source, setSource] = useState('');
  const [provider, setProvider] = useState('');
  const [files, setFiles] = useState([]);
  const submit = (e) => { e.preventDefault(); onDraft({ request: request.trim(), source: source.trim(), provider, stack, files }); };
  return (
    <form onSubmit={submit} className="space-y-4" data-testid="gb-request-form">
      <label className="block text-sm text-zinc-300">Περιέγραψε την εφαρμογή ή την αλλαγή</label>
      <textarea data-testid="gb-request-input" rows={8} value={request} onChange={(e) => setRequest(e.target.value)} className={`${input} resize-y leading-6`} placeholder="Π.χ. Φτιάξε ελληνική εφαρμογή διαχείρισης πελατών με δημιουργία, αναζήτηση και μόνιμη αποθήκευση…" />
      <input data-testid="gb-source-input" value={source} onChange={(e) => setSource(e.target.value)} className={input} placeholder="Υπάρχον repository (προαιρετικό, π.χ. https://github.com/org/repo)" />
      <input data-testid="gb-attachments-input" type="file" multiple onChange={(e) => setFiles(e.target.files)} className="block w-full text-xs text-zinc-400" />
      <ProviderSelect value={provider} onChange={setProvider} />
      <StackSelect value={stack} onChange={setStack} />
      <button data-testid="gb-create-draft-btn" type="submit" disabled={busy || request.trim().length < 3} className="w-full rounded-xl bg-amber-400 px-4 py-3 font-medium text-black transition-colors hover:bg-amber-300 disabled:opacity-40">
        {busy ? 'Working…' : 'Create Gold Builder draft'}
      </button>
    </form>
  );
}

function JobControls({ job, busy, onAction }) {
  const [followUp, setFollowUp] = useState('');
  const active = ACTIVE.includes(job.status);
  return (
    <div className="mt-5 space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <button data-testid="gb-approve-start-btn" disabled={busy || job.status !== 'pending'} onClick={() => onAction('start')} className={`${btn} border-emerald-500/30 bg-emerald-500/10 text-emerald-200`}>Approve &amp; start</button>
        <button data-testid="gb-reverify-btn" disabled={busy || active || !job.plan} onClick={() => onAction('verify')} className={`${btn} border-cyan-500/30 bg-cyan-500/10 text-cyan-200`}>Re-verify in browser</button>
      </div>
      <div className="flex gap-2">
        <input data-testid="gb-followup-input" value={followUp} onChange={(e) => setFollowUp(e.target.value)} className={input} placeholder="Επόμενη οδηγία (follow-up)…" />
        <button data-testid="gb-followup-btn" disabled={busy || active || job.status === 'pending' || followUp.trim().length < 3} onClick={() => { onAction('iterate', followUp.trim()); setFollowUp(''); }} className={`${btn} border-amber-400/30 bg-amber-400/10 text-amber-200`}>Send</button>
      </div>
    </div>
  );
}

export function GoldBuilderPanel() {
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pollId, setPollId] = useState(() => localStorage.getItem(LAST_JOB_KEY));
  useJobPolling(pollId, setJob, setError);

  const run = useCallback(async (fn) => {
    setBusy(true); setError('');
    try { await fn(); } catch (err) { setError(err.message); } finally { setBusy(false); }
  }, []);

  const onDraft = ({ request, source, provider, stack, files }) => run(async () => {
    const body = { request, llm_provider: provider || null, stack_id: stack || null, with_media: false };
    const draft = source ? await gb.draftExisting({ ...body, source }) : await gb.draft(body);
    if (files?.length) await gb.attach(draft.id, files);
    localStorage.setItem(LAST_JOB_KEY, draft.id);
    setJob(draft); setPollId(draft.id);
  });

  const onAction = (name, arg) => run(async () => {
    if (name === 'start') setJob(await gb.start(job.id));
    if (name === 'verify') await gb.verify(job.id);
    if (name === 'iterate') await gb.iterate(job.id, arg);
    setJob(await gb.job(job.id));
  });

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,.8fr)_minmax(0,1.2fr)]" data-testid="gold-builder-panel">
      <section className={box}>
        <p className="mb-4 text-xs uppercase tracking-[0.2em] text-amber-300">Engine: Gold Builder (real)</p>
        <RequestForm onDraft={onDraft} busy={busy} />
        {error && <div data-testid="gb-error" className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}
        {job && <JobControls job={job} busy={busy} onAction={onAction} />}
      </section>
      <section className="space-y-6">{job ? <JobEvidence job={job} /> : <div className={box}><p className="text-sm text-zinc-600">No Gold Builder job yet.</p></div>}</section>
    </div>
  );
}
