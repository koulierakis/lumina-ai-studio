import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BellRing,
  BookOpenCheck,
  Clock3,
  ExternalLink,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiDelete, apiGet, apiPatch, apiPost } from '../lib/api';

const money = (cents, currency = 'EUR') =>
  new Intl.NumberFormat('el-GR', { style: 'currency', currency }).format((Number(cents) || 0) / 100);

const localDate = () => new Date().toISOString().slice(0, 10);
const localDateTime = () => {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60 * 1000);
  return local.toISOString().slice(0, 16);
};

function Shell({ eyebrow, title, description, children }) {
  return (
    <div className="mx-auto w-full max-w-7xl space-y-7 pb-12" data-testid="productivity-center">
      <header className="rounded-3xl border border-white/10 bg-gradient-to-br from-white/[0.06] to-white/[0.02] p-6 shadow-2xl sm:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-300/80">{eyebrow}</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-zinc-400">{description}</p>
      </header>
      {children}
    </div>
  );
}

function Card({ children, className = '' }) {
  return <section className={`rounded-2xl border border-white/10 bg-white/[0.035] p-5 shadow-xl ${className}`}>{children}</section>;
}

function Empty({ children }) {
  return <div className="rounded-xl border border-dashed border-white/10 px-4 py-10 text-center text-sm text-zinc-500">{children}</div>;
}

function Finance() {
  const [entries, setEntries] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ direction: 'income', amount: '', currency: 'EUR', category: '', description: '', occurred_on: localDate(), notes: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [items, totals] = await Promise.all([apiGet('/finance/entries'), apiGet('/finance/summary')]);
      setEntries(items || []);
      setSummary(totals || null);
    } catch (error) {
      toast.error(error.message || 'Δεν φορτώθηκαν τα οικονομικά.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const submit = async (event) => {
    event.preventDefault();
    const amount = Math.round(Number(form.amount) * 100);
    if (!Number.isFinite(amount) || amount <= 0) {
      toast.error('Συμπλήρωσε έγκυρο ποσό.');
      return;
    }
    setSaving(true);
    try {
      await apiPost('/finance/entries', {
        direction: form.direction,
        amount_cents: amount,
        currency: form.currency,
        category: form.category.trim(),
        description: form.description.trim(),
        occurred_on: form.occurred_on,
        notes: form.notes.trim(),
        tags: [],
      });
      setForm((current) => ({ ...current, amount: '', category: '', description: '', notes: '' }));
      toast.success('Η κίνηση καταχωρήθηκε.');
      await load();
    } catch (error) {
      toast.error(error.message || 'Η κίνηση δεν αποθηκεύτηκε.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id) => {
    try {
      await apiDelete(`/finance/entries/${id}`);
      toast.success('Η κίνηση διαγράφηκε.');
      await load();
    } catch (error) {
      toast.error(error.message || 'Η διαγραφή απέτυχε.');
    }
  };

  const month = summary?.month_totals?.EUR || { income_cents: 0, expense_cents: 0, net_cents: 0 };
  const year = summary?.year_totals?.EUR || { income_cents: 0, expense_cents: 0, net_cents: 0 };

  return (
    <Shell eyebrow="JSA Finance" title="Οικονομικό Κέντρο" description="Ιδιωτικό τοπικό ledger για έσοδα, έξοδα και καθαρό αποτέλεσμα. Τα δεδομένα παραμένουν στη βάση του Lumina.">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Έσοδα μήνα', money(month.income_cents), TrendingUp],
          ['Έξοδα μήνα', money(month.expense_cents), TrendingDown],
          ['Καθαρό μήνα', money(month.net_cents), WalletCards],
          ['Καθαρό έτους', money(year.net_cents), WalletCards],
        ].map(([label, value, Icon]) => (
          <Card key={label}>
            <div className="flex items-center justify-between gap-3"><p className="text-xs uppercase tracking-[0.16em] text-zinc-500">{label}</p><Icon size={17} className="text-amber-300/80" /></div>
            <p className="mt-4 text-2xl font-semibold tabular-nums text-white">{value}</p>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.5fr]">
        <Card>
          <h2 className="text-lg font-semibold text-white">Νέα οικονομική κίνηση</h2>
          <form onSubmit={submit} className="mt-5 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <select className="field" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
                <option value="income">Έσοδο</option><option value="expense">Έξοδο</option>
              </select>
              <input className="field" value={form.currency} maxLength={3} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} aria-label="Currency" />
            </div>
            <input className="field" type="number" step="0.01" min="0.01" required placeholder="Ποσό" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
            <input className="field" required placeholder="Κατηγορία (π.χ. Software, Commission)" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
            <input className="field" required placeholder="Περιγραφή" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <input className="field" type="date" required value={form.occurred_on} onChange={(e) => setForm({ ...form, occurred_on: e.target.value })} />
            <textarea className="field min-h-24" placeholder="Σημειώσεις" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            <button disabled={saving} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-amber-300 px-4 py-3 text-sm font-semibold text-black transition hover:bg-amber-200 disabled:opacity-50">
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />} Καταχώρηση
            </button>
          </form>
        </Card>

        <Card>
          <div className="flex items-center justify-between"><h2 className="text-lg font-semibold text-white">Κινήσεις</h2><button onClick={load} className="rounded-lg border border-white/10 p-2 text-zinc-400 hover:text-white" title="Ανανέωση"><RefreshCw size={16} /></button></div>
          <div className="mt-4 space-y-2">
            {loading ? <p className="py-8 text-center text-sm text-zinc-500">Φόρτωση…</p> : entries.length === 0 ? <Empty>Δεν υπάρχουν ακόμη οικονομικές κινήσεις.</Empty> : entries.map((entry) => (
              <div key={entry.id} className="flex items-start justify-between gap-4 rounded-xl border border-white/8 bg-black/20 p-4">
                <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-white">{entry.description}</p><span className={`rounded-full px-2 py-0.5 text-[11px] ${entry.direction === 'income' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'}`}>{entry.direction === 'income' ? 'Έσοδο' : 'Έξοδο'}</span></div><p className="mt-1 text-xs text-zinc-500">{entry.occurred_on} · {entry.category}</p></div>
                <div className="flex shrink-0 items-center gap-3"><p className={`font-semibold tabular-nums ${entry.direction === 'income' ? 'text-emerald-300' : 'text-rose-300'}`}>{entry.direction === 'income' ? '+' : '-'}{money(entry.amount_cents, entry.currency)}</p><button onClick={() => remove(entry.id)} className="text-zinc-600 hover:text-rose-300" title="Διαγραφή"><Trash2 size={15} /></button></div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </Shell>
  );
}

function Research() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [form, setForm] = useState({ title: '', query: '', source_url: '', notes: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try { setItems((await apiGet('/research/items')) || []); }
    catch (error) { toast.error(error.message || 'Δεν φορτώθηκε η έρευνα.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (event) => {
    event.preventDefault(); setWorking(true);
    try {
      await apiPost('/research/items', { ...form, findings: '', status: 'open', tags: [] });
      setForm({ title: '', query: '', source_url: '', notes: '' }); toast.success('Η έρευνα αποθηκεύτηκε.'); await load();
    } catch (error) { toast.error(error.message || 'Η αποθήκευση απέτυχε.'); }
    finally { setWorking(false); }
  };

  const fetchUrl = async () => {
    if (!form.source_url.trim()) { toast.error('Βάλε πρώτα ένα δημόσιο URL.'); return; }
    setWorking(true);
    try {
      await apiPost('/research/fetch', { url: form.source_url.trim(), title: form.title.trim(), save: true }, { timeout: 20000 });
      toast.success('Η web πηγή εισήχθη στη βιβλιοθήκη.'); setForm({ title: '', query: '', source_url: '', notes: '' }); await load();
    } catch (error) { toast.error(error.message || 'Η εισαγωγή της πηγής απέτυχε.'); }
    finally { setWorking(false); }
  };

  const remove = async (id) => { try { await apiDelete(`/research/items/${id}`); await load(); } catch (error) { toast.error(error.message || 'Η διαγραφή απέτυχε.'); } };

  return (
    <Shell eyebrow="Internet Research" title="Research Workspace" description="Αποθήκευση ερευνητικών θεμάτων, σημειώσεων και πραγματικών δημόσιων web πηγών. Η εισαγωγή URL προστατεύεται από local-network/SSRF πρόσβαση.">
      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.45fr]">
        <Card>
          <div className="flex items-center gap-2"><Search size={18} className="text-amber-300" /><h2 className="text-lg font-semibold text-white">Νέα έρευνα</h2></div>
          <form onSubmit={save} className="mt-5 space-y-3">
            <input className="field" required placeholder="Τίτλος" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <input className="field" placeholder="Ερευνητικό ερώτημα" value={form.query} onChange={(e) => setForm({ ...form, query: e.target.value })} />
            <input className="field" type="url" placeholder="https://… (προαιρετικό)" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} />
            <textarea className="field min-h-28" placeholder="Σημειώσεις / στόχος έρευνας" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            <div className="grid gap-2 sm:grid-cols-2"><button disabled={working} className="rounded-xl bg-amber-300 px-4 py-3 text-sm font-semibold text-black hover:bg-amber-200 disabled:opacity-50">Αποθήκευση</button><button type="button" disabled={working} onClick={fetchUrl} className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white hover:bg-white/10 disabled:opacity-50"><ExternalLink size={15} /> Εισαγωγή URL</button></div>
          </form>
        </Card>
        <Card>
          <div className="flex items-center justify-between"><div className="flex items-center gap-2"><BookOpenCheck size={18} className="text-amber-300" /><h2 className="text-lg font-semibold text-white">Research Library</h2></div><span className="text-xs text-zinc-500">{items.length} items</span></div>
          <div className="mt-4 space-y-3">{loading ? <p className="py-8 text-center text-sm text-zinc-500">Φόρτωση…</p> : items.length === 0 ? <Empty>Δεν έχεις αποθηκευμένη έρευνα.</Empty> : items.map((item) => <article key={item.id} className="rounded-xl border border-white/8 bg-black/20 p-4"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><h3 className="font-medium text-white">{item.title}</h3>{item.query ? <p className="mt-1 text-xs text-amber-200/70">{item.query}</p> : null}{item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex max-w-full items-center gap-1 truncate text-xs text-sky-300 hover:text-sky-200"><ExternalLink size={12} /> {item.source_url}</a> : null}</div><button onClick={() => remove(item.id)} className="text-zinc-600 hover:text-rose-300"><Trash2 size={15} /></button></div>{item.notes ? <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-zinc-400">{item.notes}</p> : null}{item.findings ? <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-zinc-400">Imported source text</summary><p className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 text-xs leading-5 text-zinc-500">{item.findings}</p></details> : null}</article>)}</div>
        </Card>
      </div>
    </Shell>
  );
}

function Automations() {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ title: '', message: '', cadence: 'once', run_at: localDateTime() });

  const load = useCallback(async () => { setLoading(true); try { setTasks((await apiGet('/automations/tasks')) || []); } catch (error) { toast.error(error.message || 'Δεν φορτώθηκαν τα automations.'); } finally { setLoading(false); } }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async (event) => {
    event.preventDefault(); setSaving(true);
    try {
      const date = new Date(form.run_at);
      if (Number.isNaN(date.getTime())) throw new Error('Μη έγκυρη ημερομηνία.');
      await apiPost('/automations/tasks', { title: form.title.trim(), message: form.message.trim(), cadence: form.cadence, run_at: date.toISOString(), enabled: true });
      toast.success('Το automation ενεργοποιήθηκε.'); setForm({ title: '', message: '', cadence: 'once', run_at: localDateTime() }); await load();
    } catch (error) { toast.error(error.message || 'Το automation δεν αποθηκεύτηκε.'); }
    finally { setSaving(false); }
  };

  const toggle = async (task) => { try { await apiPatch(`/automations/tasks/${task.id}`, { enabled: !task.enabled }); await load(); } catch (error) { toast.error(error.message || 'Η αλλαγή απέτυχε.'); } };
  const run = async (id) => { try { await apiPost(`/automations/tasks/${id}/run`, {}); toast.success('Το automation εκτελέστηκε και δημιουργήθηκε notification.'); await load(); } catch (error) { toast.error(error.message || 'Η εκτέλεση απέτυχε.'); } };
  const remove = async (id) => { try { await apiDelete(`/automations/tasks/${id}`); await load(); } catch (error) { toast.error(error.message || 'Η διαγραφή απέτυχε.'); } };

  const active = useMemo(() => tasks.filter((item) => item.enabled).length, [tasks]);

  return (
    <Shell eyebrow="Automations" title="Automation Center" description="Τοπικός persisted scheduler για reminders και επαναλαμβανόμενες ειδοποιήσεις. Συνεχίζει να λειτουργεί όσο τρέχει το Lumina backend.">
      <div className="grid gap-4 sm:grid-cols-3"><Card><p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Σύνολο</p><p className="mt-3 text-3xl font-semibold text-white">{tasks.length}</p></Card><Card><p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Ενεργά</p><p className="mt-3 text-3xl font-semibold text-emerald-300">{active}</p></Card><Card><p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Εκτελέσεις</p><p className="mt-3 text-3xl font-semibold text-white">{tasks.reduce((sum, task) => sum + Number(task.run_count || 0), 0)}</p></Card></div>
      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.5fr]">
        <Card><div className="flex items-center gap-2"><Clock3 size={18} className="text-amber-300" /><h2 className="text-lg font-semibold text-white">Νέο automation</h2></div><form onSubmit={submit} className="mt-5 space-y-3"><input className="field" required placeholder="Τίτλος" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /><textarea className="field min-h-24" required placeholder="Μήνυμα notification" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} /><select className="field" value={form.cadence} onChange={(e) => setForm({ ...form, cadence: e.target.value })}><option value="once">Μία φορά</option><option value="hourly">Κάθε ώρα</option><option value="daily">Καθημερινά</option><option value="weekly">Εβδομαδιαία</option></select><input className="field" type="datetime-local" required value={form.run_at} onChange={(e) => setForm({ ...form, run_at: e.target.value })} /><button disabled={saving} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-amber-300 px-4 py-3 text-sm font-semibold text-black hover:bg-amber-200 disabled:opacity-50"><BellRing size={16} /> Ενεργοποίηση</button></form></Card>
        <Card><h2 className="text-lg font-semibold text-white">Scheduled tasks</h2><div className="mt-4 space-y-3">{loading ? <p className="py-8 text-center text-sm text-zinc-500">Φόρτωση…</p> : tasks.length === 0 ? <Empty>Δεν υπάρχουν automations.</Empty> : tasks.map((task) => <div key={task.id} className="rounded-xl border border-white/8 bg-black/20 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><h3 className="font-medium text-white">{task.title}</h3><span className={`rounded-full px-2 py-0.5 text-[11px] ${task.enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-zinc-500/15 text-zinc-400'}`}>{task.enabled ? 'Active' : 'Paused'}</span></div><p className="mt-1 text-xs text-zinc-500">{task.cadence} · next: {task.next_run_at ? new Date(task.next_run_at).toLocaleString('el-GR') : '—'}</p><p className="mt-2 text-sm text-zinc-400">{task.message}</p></div><div className="flex gap-2"><button onClick={() => run(task.id)} className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white hover:bg-white/10">Run now</button><button onClick={() => toggle(task)} className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 hover:bg-white/10">{task.enabled ? 'Pause' : 'Enable'}</button><button onClick={() => remove(task.id)} className="rounded-lg border border-white/10 p-2 text-zinc-500 hover:text-rose-300"><Trash2 size={14} /></button></div></div></div>)}</div></Card>
      </div>
    </Shell>
  );
}

export default function ProductivityCenter({ mode }) {
  if (mode === 'research') return <Research />;
  if (mode === 'automations') return <Automations />;
  return <Finance />;
}
