import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Archive, ArrowRight, CheckCircle2, FolderPlus, Search, Settings2, Trash2 } from 'lucide-react';
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '../lib/api';

const safe = (error, fallback) => typeof error?.message === 'string' ? error.message : fallback;
const Card = ({ children, className = '' }) => <div className={`lumina-glass rounded-xl p-5 ${className}`}>{children}</div>;

function Projects() {
  const [projects, setProjects] = useState([]); const [name, setName] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [archived, setArchived] = useState(false); const navigate = useNavigate();
  const load = useCallback(async () => { setBusy(true); try { setProjects(await apiGet(`/projects?include_archived=${archived}`)); setError(''); } catch (e) { setError(safe(e, 'Projects are temporarily unavailable.')); } finally { setBusy(false); } }, [archived]);
  useEffect(() => { load(); }, [load]);
  const create = async (event) => { event.preventDefault(); if (!name.trim()) return; try { await apiPost('/projects', { name }); setName(''); load(); } catch (e) { setError(safe(e, 'Project could not be created.')); } };
  const change = async (project, status) => { try { await apiPatch(`/projects/${project.id}`, { status }); load(); } catch (e) { setError(safe(e, 'Project could not be updated.')); } };
  const remove = async (project) => { if (!window.confirm(`Delete “${project.name}”? This cannot be undone.`)) return; try { await apiDelete(`/projects/${project.id}`); load(); } catch (e) { setError(safe(e, 'Project could not be deleted.')); } };
  return <main className="h-full overflow-y-auto"><div className="mx-auto max-w-[1500px] p-6 sm:p-10"><header className="flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-7"><div><p className="text-[11px] uppercase tracking-[.28em] text-gold">Business Center</p><h2 className="mt-2 font-display text-4xl text-white">Projects</h2><p className="mt-2 text-sm text-white/50">Keep work across LUMINA together, privately.</p></div><button onClick={() => setArchived(!archived)} className="text-xs text-white/60">{archived ? 'Hide archived' : 'Show archived'}</button></header><form onSubmit={create} className="mt-6 flex gap-2"><input value={name} onChange={(e) => setName(e.target.value)} aria-label="Project name" placeholder="Name a new project" className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-4 py-3 text-sm text-white" /><button className="rounded-lg bg-gold px-4 text-sm font-medium text-black"><FolderPlus className="mr-2 inline h-4 w-4" />Create</button></form>{error && <p role="alert" className="mt-4 text-sm text-amber-200">{error}</p>}<div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{projects.map((project) => <Card key={project.id}><div className="flex justify-between gap-3"><button onClick={() => navigate(`/studio/projects/${project.id}`)} className="text-left"><h3 className="text-base text-white">{project.name}</h3><p className="mt-2 text-xs text-white/45">{project.description || 'No description yet.'}</p></button><span className="text-[10px] uppercase text-gold">{project.status}</span></div><div className="mt-5 flex gap-3 text-xs"><button onClick={() => change(project, project.status === 'archived' ? 'active' : 'archived')} className="text-white/55 hover:text-white"><Archive className="mr-1 inline h-3.5 w-3.5" />{project.status === 'archived' ? 'Restore' : 'Archive'}</button><button onClick={() => remove(project)} className="text-red-200/70 hover:text-red-200"><Trash2 className="mr-1 inline h-3.5 w-3.5" />Delete</button></div></Card>)}{!busy && !projects.length && <Card className="sm:col-span-2 xl:col-span-3 text-center text-sm text-white/45">No projects yet. Create one to collect media, jobs, notes, and exports.</Card>}</div></div></main>;
}

function SearchCenter() {
  const [query, setQuery] = useState(''); const [results, setResults] = useState(null); const [error, setError] = useState(''); const [loading, setLoading] = useState(false); const [recent, setRecent] = useState(() => JSON.parse(localStorage.getItem('lumina_recent_searches') || '[]')); const timer = useRef(); const navigate = useNavigate();
  useEffect(() => () => clearTimeout(timer.current), []);
  const run = (value) => { clearTimeout(timer.current); if (!value.trim()) return setResults(null); timer.current = setTimeout(async () => { setLoading(true); try { const data = await apiGet('/workspace/search', { params: { q: value } }); setResults(data); setError(''); const next = [value, ...recent.filter((item) => item !== value)].slice(0, 5); setRecent(next); localStorage.setItem('lumina_recent_searches', JSON.stringify(next)); } catch (e) { setError(safe(e, 'Search is temporarily unavailable.')); } finally { setLoading(false); } }, 250); };
  const groups = useMemo(() => results ? Object.entries(results).filter(([, items]) => items?.length) : [], [results]);
  return <main className="h-full overflow-y-auto"><div className="mx-auto max-w-5xl p-6 sm:p-10"><p className="text-[11px] uppercase tracking-[.28em] text-gold">Workspace</p><h2 className="mt-2 font-display text-4xl text-white">Search everything</h2><div className="mt-7 flex items-center gap-3 rounded-xl border border-white/10 bg-white/[.03] px-4"><Search className="h-5 w-5 text-gold" /><input autoFocus value={query} onChange={(e) => { setQuery(e.target.value); run(e.target.value); }} onKeyDown={(e) => e.key === 'Escape' && setResults(null)} placeholder="Projects, media, jobs, identity packs, modules" className="w-full bg-transparent py-4 text-sm text-white outline-none" /></div>{!query && recent.length > 0 && <div className="mt-5 text-xs text-white/45">Recent: {recent.map((item) => <button key={item} onClick={() => { setQuery(item); run(item); }} className="ml-2 text-gold">{item}</button>)}</div>}{loading && <p className="mt-6 text-sm text-white/45">Searching your private workspace…</p>}{error && <p role="alert" className="mt-6 text-sm text-amber-200">{error}</p>}{results && !groups.length && <Card className="mt-6 text-sm text-white/45">No private workspace matches found.</Card>}{groups.map(([group, items]) => <section key={group} className="mt-7"><h3 className="text-xs uppercase tracking-widest text-white/45">{group.replace('_', ' ')}</h3><div className="mt-3 space-y-2">{items.map((item, index) => <button key={item.id || index} onClick={() => item.route ? navigate(item.route) : item.id && group === 'projects' ? navigate(`/studio/projects/${item.id}`) : null} className="flex w-full items-center justify-between rounded-lg bg-white/[.03] px-4 py-3 text-left hover:bg-white/[.06]"><span className="text-sm text-white/75">{item.name || item.title || item.prompt || item.id}</span><ArrowRight className="h-4 w-4 text-gold" /></button>)}</div></section>)}</div></main>;
}

function Settings() {
  const [readiness, setReadiness] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [runtime, setRuntime] = useState(null);
  const [message, setMessage] = useState('');
  const [runtimeMessage, setRuntimeMessage] = useState('');
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try {
      const [r, p, rt] = await Promise.all([
        apiGet('/settings/readiness'),
        apiGet('/settings/preferences'),
        apiGet('/system/runtime-settings'),
      ]);
      setReadiness(r);
      setPrefs(p);
      setRuntime(rt);
      setError('');
    } catch (e) {
      setError(safe(e, 'Settings diagnostics are unavailable.'));
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  const save = async (event) => {
    event.preventDefault();
    try {
      setPrefs(await apiPut('/settings/preferences', prefs));
      setMessage('Preferences saved locally.');
    } catch (e) {
      setError(safe(e, 'Preferences could not be saved.'));
    }
  };
  const saveRuntime = async (event) => {
    event.preventDefault();
    try {
      setRuntime(await apiPut('/system/runtime-settings', runtime));
      setRuntimeMessage('Runtime settings saved. Restart LUMINA for port changes to apply.');
      setError('');
    } catch (e) {
      setError(safe(e, 'Runtime settings could not be saved.'));
    }
  };
  return (
    <main className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl p-6 sm:p-10">
        <p className="text-[11px] uppercase tracking-[.28em] text-gold">Workspace</p>
        <h2 className="mt-2 font-display text-4xl text-white">Settings</h2>
        {error && <p role="alert" className="mt-5 text-amber-200">{error}</p>}
        <div className="mt-7 grid gap-5 lg:grid-cols-2">
          <Card>
            <h3 className="text-white">Application preferences</h3>
            <form onSubmit={save} className="mt-5 space-y-4 text-sm text-white/70">
              <label className="block">Theme
                <select value={prefs?.theme || 'dark'} onChange={(e) => setPrefs({ ...prefs, theme: e.target.value })} className="mt-2 block w-full rounded bg-black/30 p-2">
                  <option value="dark">Dark</option>
                  <option value="system">System</option>
                </select>
              </label>
              <label className="block">Default image output
                <select value={prefs?.default_output || 'png'} onChange={(e) => setPrefs({ ...prefs, default_output: e.target.value })} className="mt-2 block w-full rounded bg-black/30 p-2">
                  <option value="png">PNG</option>
                  <option value="jpeg">JPEG</option>
                  <option value="webp">WebP</option>
                </select>
              </label>
              <button className="rounded bg-gold px-4 py-2 text-black">Save preferences</button>
              {message && <p className="text-emerald-300">{message}</p>}
            </form>
          </Card>
          <Card>
            <h3 className="text-white">Security and system status</h3>
            <p className="mt-4 text-sm text-white/55">Owner credentials: {readiness?.security?.owner_configured ? 'Configured' : 'Unavailable'}</p>
            <p className="mt-2 text-sm text-white/55">Session signing: {readiness?.security?.jwt_configured ? 'Configured' : 'Unavailable'}</p>
            <p className="mt-2 text-xs text-white/40">Secret values are never displayed.</p>
          </Card>
          <Card className="lg:col-span-2">
            <h3 className="text-white">Runtime manager</h3>
            <p className="mt-2 text-sm text-white/45">Local launcher settings stored in <span className="text-white/70">.lumina-runtime/config.json</span>.</p>
            <form onSubmit={saveRuntime} className="mt-5 grid gap-4 sm:grid-cols-2 text-sm text-white/70">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={!!runtime?.dashboard_auto_open} onChange={(e) => setRuntime({ ...runtime, dashboard_auto_open: e.target.checked })} />
                Open dashboard automatically on startup
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={!!runtime?.automatic_ollama_startup} onChange={(e) => setRuntime({ ...runtime, automatic_ollama_startup: e.target.checked })} />
                Start Ollama automatically when needed
              </label>
              <label className="block">Preferred Ollama model
                <input value={runtime?.preferred_ollama_model || ''} onChange={(e) => setRuntime({ ...runtime, preferred_ollama_model: e.target.value })} className="mt-2 block w-full rounded bg-black/30 p-2" />
              </label>
              <label className="block">Logging level
                <select value={runtime?.logging_level || 'INFO'} onChange={(e) => setRuntime({ ...runtime, logging_level: e.target.value })} className="mt-2 block w-full rounded bg-black/30 p-2">
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                </select>
              </label>
              <label className="block">Backend port
                <input type="number" min={1} max={65535} value={runtime?.backend_port ?? 8000} onChange={(e) => setRuntime({ ...runtime, backend_port: Number(e.target.value) })} className="mt-2 block w-full rounded bg-black/30 p-2" />
              </label>
              <label className="block">Frontend port
                <input type="number" min={1} max={65535} value={runtime?.frontend_port ?? 3000} onChange={(e) => setRuntime({ ...runtime, frontend_port: Number(e.target.value) })} className="mt-2 block w-full rounded bg-black/30 p-2" />
              </label>
              <label className="block">Startup timeout (seconds)
                <input type="number" min={30} max={900} value={runtime?.startup_timeout_seconds ?? 180} onChange={(e) => setRuntime({ ...runtime, startup_timeout_seconds: Number(e.target.value) })} className="mt-2 block w-full rounded bg-black/30 p-2" />
              </label>
              <div className="sm:col-span-2">
                <button className="rounded bg-gold px-4 py-2 text-black">Save runtime settings</button>
                {runtimeMessage && <p className="mt-3 text-emerald-300">{runtimeMessage}</p>}
              </div>
            </form>
          </Card>
          <Card className="lg:col-span-2">
            <h3 className="text-white">Provider readiness</h3>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {readiness?.providers?.map((provider) => (
                <div key={provider.id} className="rounded bg-white/[.03] p-3 text-sm text-white/65">
                  {provider.id}
                  <span className="ml-2 text-xs text-gold">{provider.healthy ? 'Ready' : provider.configured ? 'Checking' : 'Not configured'}</span>
                </div>
              )) || <p className="text-sm text-white/45">Provider readiness unavailable.</p>}
            </div>
          </Card>
        </div>
      </div>
    </main>
  );
}

export default function WorkspaceCenter({ mode }) { return mode === 'projects' ? <Projects /> : mode === 'search' ? <SearchCenter /> : <Settings />; }
