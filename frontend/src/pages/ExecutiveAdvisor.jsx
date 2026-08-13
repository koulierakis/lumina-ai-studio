import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BrainCircuit,
  BriefcaseBusiness,
  Building2,
  ChartNoAxesCombined,
  CircleAlert,
  CircleDollarSign,
  Loader2,
  MessageSquareText,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  UserRound,
  UsersRound,
} from 'lucide-react';
import { apiDelete, apiGet, apiPost, apiPut } from '../lib/api';

const ROLE_OPTIONS = [
  ['auto', 'Auto', Sparkles],
  ['board', 'Board', UsersRound],
  ['ceo', 'CEO', Building2],
  ['cfo', 'CFO', CircleDollarSign],
  ['cmo', 'CMO', Target],
  ['strategy', 'Strategy', ChartNoAxesCombined],
  ['investment', 'Investment', BriefcaseBusiness],
  ['operations', 'Operations', BrainCircuit],
  ['risk', 'Risk', ShieldCheck],
  ['mentor', 'Mentor', UserRound],
];

function Message({ item }) {
  const assistant = item.role === 'assistant';
  return (
    <div className={`flex ${assistant ? 'justify-start' : 'justify-end'}`}>
      <div className={`max-w-[88%] rounded-2xl border px-4 py-3 ${assistant ? 'border-white/[0.08] bg-white/[0.025]' : 'border-gold/20 bg-gold/[0.08]'}`}>
        <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-white/35">
          {assistant ? 'Executive Advisor' : 'You'}
          {item.role_mode && <span className="rounded-full border border-white/10 px-2 py-0.5">{item.role_mode}</span>}
        </div>
        <div className="whitespace-pre-wrap text-sm leading-7 text-white/80">{item.content}</div>
      </div>
    </div>
  );
}

export default function ExecutiveAdvisor() {
  const [status, setStatus] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [session, setSession] = useState(null);
  const [message, setMessage] = useState('');
  const [role, setRole] = useState('auto');
  const [deep, setDeep] = useState(true);
  const [rememberMessage, setRememberMessage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [memories, setMemories] = useState([]);
  const [memoryText, setMemoryText] = useState('');
  const [profileText, setProfileText] = useState('{}');

  const loadSidebar = useCallback(async () => {
    try {
      const [statusData, sessionData, memoryData, profileData] = await Promise.all([
        apiGet('/runtime/advisor/status', { retry: false }),
        apiGet('/runtime/advisor/sessions'),
        apiGet('/runtime/advisor/memory'),
        apiGet('/runtime/advisor/profile'),
      ]);
      setStatus(statusData);
      setSessions(sessionData.sessions || []);
      setMemories(memoryData.memories || []);
      setProfileText(JSON.stringify(profileData.profile || {}, null, 2));
    } catch (err) {
      setError(err?.message || 'Could not load Executive Advisor.');
    }
  }, []);

  useEffect(() => { loadSidebar(); }, [loadSidebar]);

  const openSession = async (id) => {
    setError('');
    try {
      const data = await apiGet(`/runtime/advisor/sessions/${id}`);
      setSession(data);
    } catch (err) {
      setError(err?.message || 'Could not open session.');
    }
  };

  const newSession = () => {
    setSession(null);
    setMessage('');
    setError('');
  };

  const send = async () => {
    const value = message.trim();
    if (!value || busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await apiPost('/runtime/advisor/ask', {
        message: value,
        session_id: session?.id || null,
        role,
        deep_reasoning: deep,
        remember_message: rememberMessage,
        context: {},
      }, { timeout: 320000 });
      setMessage('');
      setRememberMessage(false);
      const detail = await apiGet(`/runtime/advisor/sessions/${response.session_id}`, { retry: false });
      setSession(detail);
      await loadSidebar();
    } catch (err) {
      setError(err?.responseData?.detail || err?.message || 'Advisor request failed.');
    } finally {
      setBusy(false);
    }
  };

  const deleteSession = async (id) => {
    await apiDelete(`/runtime/advisor/sessions/${id}`);
    if (session?.id === id) setSession(null);
    await loadSidebar();
  };

  const saveMemory = async () => {
    const value = memoryText.trim();
    if (!value) return;
    await apiPost('/runtime/advisor/memory', { text: value, category: 'manual' });
    setMemoryText('');
    await loadSidebar();
  };

  const forgetMemory = async (id) => {
    await apiDelete(`/runtime/advisor/memory/${id}`);
    await loadSidebar();
  };

  const saveProfile = async () => {
    try {
      const parsed = JSON.parse(profileText || '{}');
      await apiPut('/runtime/advisor/profile', { profile: parsed });
      setError('');
      await loadSidebar();
    } catch (err) {
      setError(err instanceof SyntaxError ? 'Profile must be valid JSON.' : err?.message || 'Could not save profile.');
    }
  };

  const messages = session?.messages || [];
  const selectedRole = useMemo(() => ROLE_OPTIONS.find(([id]) => id === role), [role]);

  return (
    <main className="min-h-screen w-full overflow-y-auto" data-testid="executive-advisor-page">
      <div className="mx-auto max-w-[1700px] p-5 sm:p-8">
        <header className="flex flex-col gap-4 border-b border-white/[0.07] pb-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] uppercase tracking-[0.28em] text-gold">LUMINA Executive Intelligence</p>
            <h1 className="mt-2 font-display text-4xl text-white sm:text-5xl">Executive Advisor</h1>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-white/45">One persistent advisor for finance, marketing, strategy, investments, operations, risk and personal decision support.</p>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 text-xs text-white/50">
            <span className={`h-2 w-2 rounded-full ${status?.available ? 'bg-emerald-400' : 'bg-amber-300'}`} />
            {status?.available ? `${status.model} ready` : 'Local model unavailable'}
          </div>
        </header>

        {error && <div className="mt-5 flex gap-2 rounded-lg border border-red-400/20 bg-red-400/5 p-3 text-sm text-red-100"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />{String(error)}</div>}

        <div className="mt-6 grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)_320px]">
          <aside className="space-y-4">
            <button onClick={newSession} className="w-full rounded-lg bg-gold px-4 py-3 text-sm font-medium text-black">New advisory session</button>
            <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
              <h2 className="px-2 pb-2 text-[11px] uppercase tracking-[0.18em] text-white/35">Sessions</h2>
              <div className="space-y-1">
                {sessions.length === 0 && <p className="px-2 py-4 text-xs text-white/30">No sessions yet.</p>}
                {sessions.map((item) => (
                  <div key={item.id} className={`group flex items-start gap-2 rounded-lg p-2 ${session?.id === item.id ? 'bg-white/[0.07]' : 'hover:bg-white/[0.035]'}`}>
                    <button onClick={() => openSession(item.id)} className="min-w-0 flex-1 text-left">
                      <div className="truncate text-xs text-white/75">{item.title}</div>
                      <div className="mt-1 truncate text-[10px] text-white/30">{item.last_message || `${item.message_count} messages`}</div>
                    </button>
                    <button onClick={() => deleteSession(item.id)} className="p-1 text-white/20 opacity-0 group-hover:opacity-100" title="Delete"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                ))}
              </div>
            </section>
          </aside>

          <section className="flex min-h-[720px] flex-col rounded-xl border border-white/[0.08] bg-white/[0.02]">
            <div className="border-b border-white/[0.07] p-4">
              <div className="flex flex-wrap gap-2">
                {ROLE_OPTIONS.map(([id, label, Icon]) => (
                  <button key={id} onClick={() => setRole(id)} className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] ${role === id ? 'border-gold/40 bg-gold/10 text-gold' : 'border-white/10 text-white/40 hover:text-white/70'}`}>
                    <Icon className="h-3.5 w-3.5" />{label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              {messages.length === 0 ? (
                <div className="mx-auto mt-20 max-w-2xl text-center">
                  <MessageSquareText className="mx-auto h-10 w-10 text-gold/70" />
                  <h2 className="mt-5 font-display text-3xl text-white">What decision are we making?</h2>
                  <p className="mt-3 text-sm leading-7 text-white/40">Use Auto for normal advisory routing or Board when you want a unified multi-discipline recommendation.</p>
                </div>
              ) : messages.map((item) => <Message key={item.id} item={item} />)}
              {busy && <div className="flex items-center gap-2 text-xs text-white/35"><Loader2 className="h-4 w-4 animate-spin" />{deep ? 'Deep analysis in progress…' : 'Preparing response…'}</div>}
            </div>

            <div className="border-t border-white/[0.07] p-4">
              <textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }} rows={4} placeholder={`Ask ${selectedRole?.[1] || 'Executive Advisor'}…`} className="w-full resize-none rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm leading-6 text-white outline-none placeholder:text-white/25 focus:border-gold/35" />
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap gap-4 text-xs text-white/40">
                  <label className="flex items-center gap-2"><input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} />Deep reasoning</label>
                  <label className="flex items-center gap-2"><input type="checkbox" checked={rememberMessage} onChange={(e) => setRememberMessage(e.target.checked)} />Remember this</label>
                </div>
                <button onClick={send} disabled={!message.trim() || busy} className="inline-flex items-center gap-2 rounded-lg bg-gold px-4 py-2.5 text-xs font-medium text-black disabled:opacity-40"><Send className="h-4 w-4" />Send</button>
              </div>
            </div>
          </section>

          <aside className="space-y-5">
            <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-4">
              <div className="flex items-center gap-2"><BrainCircuit className="h-4 w-4 text-gold" /><h2 className="text-sm text-white">Memory</h2></div>
              <div className="mt-3 flex gap-2"><input value={memoryText} onChange={(e) => setMemoryText(e.target.value)} placeholder="Remember a fact, goal or preference…" className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-none" /><button onClick={saveMemory} className="rounded-lg border border-gold/20 p-2 text-gold"><Save className="h-4 w-4" /></button></div>
              <div className="mt-3 max-h-56 space-y-2 overflow-y-auto">
                {memories.map((item) => <div key={item.id} className="group flex gap-2 rounded-lg border border-white/[0.06] p-2"><p className="flex-1 text-[11px] leading-5 text-white/50">{item.text}</p><button onClick={() => forgetMemory(item.id)} className="text-white/20 opacity-0 group-hover:opacity-100"><Trash2 className="h-3.5 w-3.5" /></button></div>)}
              </div>
            </section>

            <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-4">
              <div className="flex items-center gap-2"><UserRound className="h-4 w-4 text-gold" /><h2 className="text-sm text-white">Advisor profile</h2></div>
              <p className="mt-2 text-[11px] leading-5 text-white/35">Structured persistent context. Keep sensitive information only if you want it stored locally.</p>
              <textarea value={profileText} onChange={(e) => setProfileText(e.target.value)} rows={12} className="mt-3 w-full resize-y rounded-lg border border-white/10 bg-black/20 p-3 font-mono text-[11px] leading-5 text-white/55 outline-none" />
              <button onClick={saveProfile} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs text-white/60"><Save className="h-3.5 w-3.5" />Save profile</button>
            </section>
          </aside>
        </div>
      </div>
    </main>
  );
}
