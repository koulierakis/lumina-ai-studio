import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bot, CheckCircle2, ChevronRight, CircleAlert, FileText, Film, Globe2,
  ImageIcon, Loader2, Mic2, Plus, RefreshCw, Settings2, Sparkles, Wallet,
  Workflow, Zap,
} from 'lucide-react';
import { apiGet } from '../lib/api';
import AuthImage from '../components/AuthImage';
import { CONTROL_CENTER_TOOLS, activeJobs, buildMessages, formatRelativeTime, suggestedActions } from '../dashboard/model';

const TOOL_ICONS = { image: ImageIcon, video: Film, voice: Mic2, document: FileText, finance: Wallet, research: Globe2, automation: Workflow, settings: Settings2 };

function ToolCard({ tool, onOpen }) {
  const Icon = TOOL_ICONS[tool.icon] || Sparkles;
  return <button onClick={() => onOpen(tool.to)} data-testid={`dashboard-tool-${tool.key}`} className="lumina-glass group rounded-xl p-6 text-left transition-all hover:border-gold/45 hover:bg-white/[0.045]">
    <div className="flex items-start justify-between gap-3"><span className="rounded-lg bg-gold/10 p-2.5 text-gold"><Icon className="w-5 h-5" strokeWidth={1.35} /></span><ChevronRight className="w-4 h-4 text-white/25 group-hover:text-gold transition-colors" /></div>
    <h3 className="mt-5 text-lg font-semibold text-white">{tool.label}</h3><p className="mt-1.5 text-sm leading-relaxed text-white/60">{tool.description}</p>
  </button>;
}

const emptyData = () => ({ gallery: [], jobs: [], projects: [], providers: [], health: null, panelErrors: {}, system: null });

export default function Dashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState(emptyData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(false);
    let overview = null;
    let system = null;
    const panelErrors = {};
    try {
      overview = await apiGet('/workspace/overview');
    } catch {
      panelErrors.overview = 'Workspace overview is unavailable.';
    }
    try {
      system = await apiGet('/system/status');
    } catch {
      panelErrors.system = 'System status is unavailable.';
    }
    if (overview) {
      Object.assign(panelErrors, overview.panel_errors || {});
      setData({
        gallery: (overview.media || []).map((item) => ({ ...item, media_id: item.id })),
        jobs: overview.jobs || [],
        projects: overview.projects || [],
        providers: overview.readiness?.providers || [],
        health: overview.readiness,
        panelErrors,
        system,
      });
    } else {
      setData({ ...emptyData(), panelErrors, system });
    }
    setError(Object.keys(panelErrors).length > 0);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);
  const running = useMemo(() => activeJobs(data.jobs), [data.jobs]);
  const messages = useMemo(() => buildMessages({ ...data, system: data.system }), [data]);
  const actions = useMemo(() => suggestedActions(data), [data]);
  const system = data.system;
  const systemReadyLabel = system?.system_ready ? 'Ready' : system?.overall_readiness === 'degraded' ? 'Degraded' : system ? 'Checking' : '—';
  const backendLabel = system?.backend?.status === 'ok' ? 'Online' : 'Offline';
  const localAiLabel = system?.ollama?.online ? 'Online' : 'Offline';
  const codingModelLabel = system?.coding_model?.installed ? (system.coding_model.name || 'Installed') : (system?.coding_model?.name ? 'Missing' : '—');
  const activeJobCount = typeof system?.active_jobs === 'number' ? system.active_jobs : running.length;
  const warningCount = Array.isArray(system?.warnings) ? system.warnings.length : Object.keys(data.panelErrors).length;

  return <main className="h-full w-full overflow-y-auto" data-testid="dashboard-page">
    <div className="mx-auto max-w-[1540px] p-6 sm:p-10">
      <header className="flex flex-col gap-5 border-b border-white/[0.07] pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="text-sm font-semibold uppercase tracking-[0.24em] text-gold">Control center</p><h2 className="mt-2 font-display text-4xl font-bold tracking-tight text-white sm:text-5xl">Good to see you.</h2><p className="mt-3 text-base text-white/60">Everything important in your Lumina workspace, in one calm view.</p></div>
        <div className="flex gap-2"><button onClick={load} disabled={loading} className="rounded-lg border border-white/10 px-4 py-2.5 text-sm font-semibold text-white/70 hover:border-white/20 hover:text-white disabled:opacity-40"><RefreshCw className={`mr-2 inline h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />Refresh</button><button onClick={() => navigate('/studio/generate')} data-testid="dashboard-new-image" className="rounded-lg bg-gold px-4 py-2.5 text-sm font-semibold text-black hover:bg-gold-soft"><Plus className="mr-1.5 inline h-4 w-4" />New image</button></div>
      </header>

      {error && <div className="mt-5 flex items-center gap-2 rounded-lg border border-amber-300/20 bg-amber-300/5 px-4 py-3 text-xs text-amber-100"><CircleAlert className="h-4 w-4" />Some workspace data could not be refreshed. The available information is shown below.</div>}

      <section className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6" data-testid="dashboard-system-status">
        {[
          ['System Ready', loading ? '—' : systemReadyLabel, CheckCircle2, system?.system_ready ? 'All core services ready' : 'One or more services need attention'],
          ['Backend', loading ? '—' : backendLabel, Zap, 'Local API process'],
          ['Local AI', loading ? '—' : localAiLabel, Bot, 'Ollama runtime'],
          ['Coding Model', loading ? '—' : codingModelLabel, Sparkles, system?.coding_model?.name || 'Configured model'],
          ['Active Jobs', loading ? '—' : activeJobCount, Loader2, activeJobCount ? 'Lumina is working for you' : 'Nothing is waiting'],
          ['Warnings', loading ? '—' : warningCount, CircleAlert, warningCount ? 'See messages below' : 'No active warnings'],
        ].map(([label, value, Icon, detail]) => <div key={label} className="lumina-glass rounded-xl p-6"><div className="flex items-start justify-between"><span className="text-sm font-medium text-white/65">{label}</span><Icon className="h-4 w-4 text-gold" strokeWidth={1.4} /></div><div className="mt-5 truncate text-2xl font-semibold text-white" title={String(value)}>{value}</div><p className="mt-1 text-sm text-white/55">{detail}</p></div>)}
      </section>

      {!!system?.warnings?.length && <div className="mt-4 space-y-2" data-testid="dashboard-system-warnings">{system.warnings.map((warning) => <div key={warning} className="rounded-lg border border-amber-300/15 bg-amber-300/[0.04] px-4 py-2 text-xs text-amber-100/90">{warning}</div>)}</div>}

      <section className="mt-10"><div className="flex items-center justify-between"><div><h3 className="font-display text-3xl text-white">Your studios</h3><p className="mt-1 text-sm text-white/45">Quick access to every Lumina workspace.</p></div><span className="hidden text-[10px] uppercase tracking-[0.2em] text-white/30 md:block">Widget-ready layout</span></div><div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{CONTROL_CENTER_TOOLS.map((tool) => <ToolCard key={tool.key} tool={tool} onOpen={navigate} />)}</div></section>

      <section className="mt-10 grid gap-6 xl:grid-cols-3">
        <div className="lumina-glass rounded-xl p-6 xl:col-span-2"><div className="flex items-center justify-between"><div><h3 className="font-display text-3xl text-white">Recent activity</h3><p className="mt-1 text-xs text-white/45">Your newest generated and edited files.</p></div><button onClick={() => navigate('/studio/gallery')} className="text-xs text-gold hover:text-gold-soft">Open Gallery <ChevronRight className="inline h-3.5 w-3.5" /></button></div>
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">{data.gallery.slice(0, 4).map((item) => <button key={item.id} onClick={() => navigate(`/studio/editor/${item.media_id}`)} className="group relative aspect-[4/3] overflow-hidden rounded-lg bg-white/[0.03] text-left"><AuthImage mediaId={item.media_id} alt={item.prompt || 'Recent Lumina file'} className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105" /><span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 to-transparent px-3 pb-2 pt-8 text-[10px] text-white/70">{formatRelativeTime(item.created_at)}</span></button>)}{!loading && data.gallery.length === 0 && <button onClick={() => navigate('/studio/generate')} className="col-span-full flex min-h-36 flex-col items-center justify-center rounded-lg border border-dashed border-white/10 text-sm text-white/45 hover:border-gold/40 hover:text-white"><ImageIcon className="mb-2 h-5 w-5 text-gold/70" />Create your first file</button>}{loading && <div className="col-span-full min-h-36 animate-pulse rounded-lg bg-white/[0.03]" />}</div>
        </div>
        <div id="jobs" className="lumina-glass rounded-xl p-6"><h3 className="font-display text-3xl text-white">Active jobs</h3><p className="mt-1 text-xs text-white/45">Live creation progress.</p><div className="mt-5 space-y-3">{running.slice(0, 4).map((job) => <div key={job.id} className="rounded-lg bg-white/[0.03] p-3"><div className="flex justify-between gap-3 text-xs"><span className="truncate text-white/75">{job.prompt || 'AI image generation'}</span><span className="capitalize text-gold">{job.status}</span></div><div className="mt-3 h-1 overflow-hidden rounded bg-white/10"><div className={`h-full rounded bg-gold ${job.status === 'queued' ? 'w-1/4' : 'w-2/3'}`} /></div></div>)}{!loading && !running.length && <div className="rounded-lg border border-dashed border-white/10 p-5 text-center text-xs text-white/45">No active jobs. Your workspace is up to date.</div>}</div><div className="mt-5 border-t border-white/[0.07] pt-4"><div className="flex items-center justify-between"><span className="text-xs text-white/55">Recent projects</span><button onClick={() => navigate('/studio/video-studio')} className="text-[11px] text-gold">Open Video Studio</button></div><div className="mt-3 space-y-2">{data.projects.slice(0, 2).map((project) => <button key={project.id} onClick={() => navigate('/studio/video-studio')} className="flex w-full items-center justify-between rounded-md bg-white/[0.025] px-3 py-2 text-left"><span className="truncate text-xs text-white/70">{project.name || 'Untitled project'}</span><span className="ml-2 shrink-0 text-[10px] text-white/35">{formatRelativeTime(project.updated_at || project.created_at)}</span></button>)}{!loading && !data.projects.length && <p className="text-xs text-white/40">No video projects yet.</p>}</div></div></div>
      </section>

      <section className="mt-6 grid gap-6 xl:grid-cols-2"><div className="lumina-glass rounded-xl p-6"><div className="flex items-center gap-2"><Bot className="h-4 w-4 text-gold" /><h3 className="font-display text-3xl text-white">Recent messages</h3></div><div className="mt-5 space-y-3">{messages.map((message) => <div key={message.title} className="flex items-center gap-3 rounded-lg bg-white/[0.025] px-3 py-3"><span className={`h-2 w-2 rounded-full ${message.tone === 'green' ? 'bg-emerald-400' : message.tone === 'gold' ? 'bg-gold' : 'bg-white/35'}`} /><span className="text-xs text-white/65">{message.title}</span></div>)}{!messages.length && <p className="text-xs text-white/45">No system messages right now.</p>}</div></div><div className="lumina-glass rounded-xl p-6"><div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-gold" /><h3 className="font-display text-3xl text-white">Suggested next actions</h3></div><div className="mt-5 space-y-2">{actions.map((action) => <button key={action.title} onClick={() => navigate(action.to)} className="group flex w-full items-center justify-between rounded-lg bg-white/[0.025] px-3 py-3 text-left hover:bg-white/[0.05]"><span><span className="block text-xs text-white/80">{action.title}</span><span className="mt-0.5 block text-[11px] text-white/40">{action.description}</span></span><ChevronRight className="h-4 w-4 text-white/25 group-hover:text-gold" /></button>)}</div></div></section>
    </div>
  </main>;
}
