import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../lib/api';
import { toast } from 'sonner';
import { Bot, CheckCircle2, Code2, FileCode2, FolderPlus, Loader2, Play } from 'lucide-react';

export default function CodeCreator() {
  const [status, setStatus] = useState(null);
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState(null);

  const refresh = async () => {
    const [nextStatus, nextProjects] = await Promise.all([
      apiGet('/code-creator/status'),
      apiGet('/code-creator/projects'),
    ]);
    setStatus(nextStatus || null);
    setProjects(Array.isArray(nextProjects) ? nextProjects : []);
  };

  useEffect(() => { refresh().catch((e) => toast.error(e.message)); }, []);

  const create = async () => {
    if (!name.trim() || !description.trim()) return toast.error('Γράψε όνομα και περιγραφή εφαρμογής.');
    setBusy(true);
    try {
      const project = await apiPost('/code-creator/projects', { name, description, stack: 'auto' });
      setSelected(project);
      setName(''); setDescription(''); setCheck(null);
      await refresh();
      toast.success('Το νέο project δημιουργήθηκε.');
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const openProject = async (id) => {
    setCheck(null);
    try { setSelected(await apiGet(`/code-creator/projects/${id}`)); }
    catch (e) { toast.error(e.message); }
  };

  const generate = async () => {
    if (!selected) return;
    setBusy(true); setCheck(null);
    try {
      const project = await apiPost(`/code-creator/projects/${selected.id}/generate`, {} , { timeout: 650000 });
      setSelected(project); await refresh();
      toast.success('Ο κώδικας δημιουργήθηκε.');
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const runCheck = async () => {
    if (!selected) return;
    setBusy(true);
    try { setCheck(await apiPost(`/code-creator/projects/${selected.id}/check`, {}, { timeout: 220000 })); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return <div className="mx-auto max-w-7xl p-6 space-y-6">
    <div>
      <div className="flex items-center gap-3"><Code2 className="h-8 w-8"/><h1 className="text-3xl font-semibold">Code Creator</h1></div>
      <p className="mt-2 text-white/60">Περιέγραψε την εφαρμογή σου και το LUMINA θα δημιουργήσει τα αρχεία κώδικα σε ασφαλή ξεχωριστό φάκελο.</p>
    </div>

    <div className="rounded-2xl border border-white/10 bg-white/5 p-4 flex items-center gap-3">
      <Bot className="h-5 w-5"/>
      <div className="flex-1"><div className="font-medium">Τοπικός εγκέφαλος κώδικα</div><div className="text-sm text-white/60">{status?.online ? `${status.model} — ${status.installed ? 'έτοιμο' : 'το μοντέλο λείπει'}` : 'Το Ollama δεν απαντά'}</div></div>
      <span className={`rounded-full px-3 py-1 text-xs ${status?.online && status?.installed ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'}`}>{status?.online && status?.installed ? 'ΕΤΟΙΜΟ' : 'ΕΛΕΓΧΟΣ'}</span>
    </div>

    <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
      <div className="space-y-4">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4 space-y-3">
          <div className="flex items-center gap-2 font-medium"><FolderPlus className="h-4 w-4"/> Νέα εφαρμογή</div>
          <input className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2" value={name} onChange={e=>setName(e.target.value)} placeholder="Όνομα, π.χ. Gym CRM"/>
          <textarea className="min-h-32 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2" value={description} onChange={e=>setDescription(e.target.value)} placeholder="Πες με απλά λόγια τι πρέπει να κάνει..."/>
          <button disabled={busy} onClick={create} className="w-full rounded-xl bg-white text-black py-2 font-medium disabled:opacity-50">Δημιουργία project</button>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
          <div className="mb-2 px-1 text-sm text-white/60">Οι εφαρμογές μου</div>
          <div className="space-y-2 max-h-[420px] overflow-auto">
            {projects.map(p=><button key={p.id} onClick={()=>openProject(p.id)} className={`w-full rounded-xl border p-3 text-left ${selected?.id===p.id?'border-white/40 bg-white/10':'border-white/5 bg-black/20'}`}><div className="font-medium">{p.name}</div><div className="mt-1 text-xs text-white/50">{p.status} · {p.files || 0} αρχεία</div></button>)}
            {!projects.length && <div className="p-3 text-sm text-white/40">Δεν υπάρχει ακόμη εφαρμογή.</div>}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-white/5 p-5 min-h-[580px]">
        {!selected ? <div className="h-full grid place-items-center text-center text-white/45"><div><FileCode2 className="mx-auto h-12 w-12 mb-3"/><p>Δημιούργησε ή άνοιξε ένα project.</p></div></div> : <div className="space-y-5">
          <div><h2 className="text-2xl font-semibold">{selected.name}</h2><p className="mt-1 text-white/60">{selected.description}</p></div>
          <div className="flex flex-wrap gap-3">
            <button disabled={busy || !status?.installed} onClick={generate} className="flex items-center gap-2 rounded-xl bg-white text-black px-4 py-2 font-medium disabled:opacity-40">{busy?<Loader2 className="h-4 w-4 animate-spin"/>:<Code2 className="h-4 w-4"/>} Δημιουργία κώδικα</button>
            <button disabled={busy || !selected.files} onClick={runCheck} className="flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2 disabled:opacity-40"><Play className="h-4 w-4"/> Έλεγχος εφαρμογής</button>
          </div>
          {selected.summary && <div className="rounded-xl border border-white/10 bg-black/20 p-4"><div className="text-sm text-white/50">Τι δημιούργησε</div><p className="mt-1">{selected.summary}</p></div>}
          {!!selected.run_instructions?.length && <div><h3 className="font-medium mb-2">Πώς ανοίγει</h3><div className="space-y-2">{selected.run_instructions.map((x,i)=><code key={i} className="block rounded-lg bg-black/40 p-3 text-sm">{x}</code>)}</div></div>}
          <div><h3 className="font-medium mb-2">Αρχεία ({selected.file_list?.length || selected.files || 0})</h3><div className="grid gap-2 sm:grid-cols-2 max-h-64 overflow-auto">{selected.file_list?.map(x=><div key={x} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-sm text-white/70">{x}</div>)}</div></div>
          {check && <div className={`rounded-xl border p-4 ${check.ok?'border-emerald-500/30 bg-emerald-500/10':'border-red-500/30 bg-red-500/10'}`}><div className="flex items-center gap-2 font-medium"><CheckCircle2 className="h-4 w-4"/>{check.ok?'Ο έλεγχος πέρασε':'Βρέθηκαν προβλήματα'}</div>{check.checks?.map((x,i)=><pre key={i} className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap text-xs">{x.command}\n{x.output}</pre>)}</div>}
        </div>}
      </div>
    </div>
  </div>;
}
