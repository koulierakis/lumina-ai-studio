import { useCallback, useEffect, useMemo, useState } from 'react';
import { Brain, CheckCircle2, CircleAlert, Plus, Send, Target } from 'lucide-react';
import { apiGet, apiPatch, apiPost } from '../lib/api';

const MODES = ['mentor', 'coach', 'decision', 'accountability', 'reflection'];

export default function Mentor() {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState('');
  const [session, setSession] = useState(null);
  const [message, setMessage] = useState('');
  const [mode, setMode] = useState('mentor');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const loadSessions = useCallback(async () => {
    const data = await apiGet('/mentor/sessions');
    setSessions(data.items || []);
    setActiveId((current) => current || data.items?.[0]?.id || '');
  }, []);

  useEffect(() => { loadSessions().catch((err) => setError(err?.message || 'Could not load Mentor sessions.')); }, [loadSessions]);
  useEffect(() => {
    if (!activeId) { setSession(null); return; }
    apiGet(`/mentor/sessions/${activeId}`).then(setSession).catch((err) => setError(err?.message || 'Could not load Mentor session.'));
  }, [activeId]);

  const createSession = async () => {
    setBusy(true); setError('');
    try {
      const created = await apiPost('/mentor/sessions', { title: 'New Mentor Session', goal: '', context: '' });
      await loadSessions(); setActiveId(created.id); setSession(created);
    } catch (err) { setError(err?.message || 'Could not create Mentor session.'); }
    finally { setBusy(false); }
  };

  const send = async () => {
    const value = message.trim();
    if (!activeId || !value || busy) return;
    setBusy(true); setError('');
    try {
      await apiPost(`/mentor/sessions/${activeId}/message`, { message: value, mode });
      setMessage('');
      const fresh = await apiGet(`/mentor/sessions/${activeId}`);
      setSession(fresh); await loadSessions();
    } catch (err) { setError(err?.message || 'Mentor request failed.'); }
    finally { setBusy(false); }
  };

  const updateField = async (field, value) => {
    if (!activeId) return;
    const updated = await apiPatch(`/mentor/sessions/${activeId}`, { [field]: value });
    setSession(updated); await loadSessions();
  };

  const messages = useMemo(() => session?.messages || [], [session]);

  return (
    <main className="min-h-screen w-full overflow-y-auto">
      <div className="mx-auto max-w-[1500px] p-6 sm:p-10">
        <header className="flex flex-col gap-5 border-b border-white/[0.07] pb-8 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] uppercase tracking-[0.28em] text-gold">Stateful guidance</p>
            <h2 className="mt-2 font-display text-4xl tracking-tight text-white sm:text-5xl">Mentor</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-white/50">Persistent goals, decisions, accountability and structured next actions. The Mentor challenges assumptions instead of merely agreeing.</p>
          </div>
          <button onClick={createSession} disabled={busy} className="inline-flex items-center gap-2 rounded-md bg-gold px-4 py-2.5 text-xs font-medium text-black disabled:opacity-40"><Plus className="h-4 w-4" />New session</button>
        </header>

        {error && <div className="mt-5 flex gap-2 rounded-lg border border-red-400/20 bg-red-400/5 px-4 py-3 text-sm text-red-100"><CircleAlert className="h-4 w-4" />{error}</div>}

        <div className="mt-8 grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)_340px]">
          <aside className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-4">
            <div className="mb-3 flex items-center gap-2 text-sm text-white"><Brain className="h-4 w-4 text-gold" />Sessions</div>
            <div className="space-y-2">{sessions.map((item) => <button key={item.id} onClick={() => setActiveId(item.id)} className={`w-full rounded-lg border px-3 py-3 text-left ${activeId === item.id ? 'border-gold/30 bg-gold/5' : 'border-white/[0.07] bg-black/10'}`}><div className="text-sm text-white/85">{item.title}</div><div className="mt-1 line-clamp-2 text-[11px] text-white/35">{item.goal || 'No goal set yet'}</div></button>)}</div>
          </aside>

          <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5">
            {!session ? <p className="text-sm text-white/40">Create or select a Mentor session.</p> : <>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-[11px] uppercase tracking-[0.16em] text-white/40">Title<input defaultValue={session.title} onBlur={(e) => updateField('title', e.target.value)} className="mt-2 w-full rounded-md border border-white/10 bg-black/20 px-3 py-2 text-sm normal-case tracking-normal text-white outline-none" /></label>
                <label className="text-[11px] uppercase tracking-[0.16em] text-white/40">Goal<input defaultValue={session.goal} onBlur={(e) => updateField('goal', e.target.value)} className="mt-2 w-full rounded-md border border-white/10 bg-black/20 px-3 py-2 text-sm normal-case tracking-normal text-white outline-none" /></label>
              </div>
              <div className="mt-5 max-h-[520px] space-y-3 overflow-y-auto pr-1">{messages.map((item) => <div key={item.id} className={`rounded-lg border px-4 py-3 ${item.role === 'assistant' ? 'border-gold/15 bg-gold/[0.03]' : 'border-white/[0.07] bg-black/15'}`}><div className="text-[10px] uppercase tracking-[0.16em] text-white/30">{item.role === 'assistant' ? 'Mentor' : 'You'}</div><p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-white/75">{item.content}</p>{item.structured?.priorities?.length > 0 && <div className="mt-3 space-y-1 text-xs text-white/50">{item.structured.priorities.map((p) => <div key={p}>• {p}</div>)}</div>}</div>)}</div>
              <div className="mt-5 flex flex-wrap gap-2">{MODES.map((item) => <button key={item} onClick={() => setMode(item)} className={`rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.14em] ${mode === item ? 'border-gold/35 text-gold' : 'border-white/10 text-white/35'}`}>{item}</button>)}</div>
              <div className="mt-3 flex gap-2"><textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3} placeholder="What are you trying to decide, solve or improve?" className="flex-1 rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none placeholder:text-white/25" /><button onClick={send} disabled={!message.trim() || busy} className="self-end rounded-md bg-gold p-3 text-black disabled:opacity-30"><Send className="h-4 w-4" /></button></div>
            </>}
          </section>

          <aside className="space-y-5">
            <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5"><div className="flex items-center gap-2"><Target className="h-4 w-4 text-gold" /><h3 className="text-sm text-white">Open actions</h3></div><div className="mt-4 space-y-2">{(session?.open_actions || []).map((action) => <div key={action} className="flex gap-2 text-xs leading-relaxed text-white/55"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />{action}</div>)}{!session?.open_actions?.length && <p className="text-xs text-white/35">No actions captured yet.</p>}</div></section>
            <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5"><h3 className="text-sm text-white">Context</h3><textarea defaultValue={session?.context || ''} onBlur={(e) => session && updateField('context', e.target.value)} rows={10} placeholder="Persistent background, constraints, people, deadlines, definitions…" className="mt-3 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs leading-relaxed text-white outline-none placeholder:text-white/25" /></section>
          </aside>
        </div>
      </div>
    </main>
  );
}
