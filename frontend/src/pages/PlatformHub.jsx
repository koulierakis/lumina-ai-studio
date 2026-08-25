import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiDelete, apiGet, apiPatch, apiPost, fetchMediaBlobUrl } from '../lib/api';
import AuthImage from '../components/AuthImage';
import { AudioLines, Film, Image as ImageIcon, Loader2, Play, RefreshCw } from 'lucide-react';

const message = (error, fallback) => typeof error?.message === 'string' ? error.message : fallback;
const Empty = ({ children }) => <div className="rounded-xl border border-dashed border-white/10 p-8 text-center text-sm text-white/45">{children}</div>;
const ACTIVE_JOB_STATUSES = new Set(['queued', 'preparing', 'uploading', 'processing', 'rendering', 'executing', 'verifying']);

function mediaKind(item) {
  const mime = String(item?.mime_type || '').toLowerCase();
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('video/')) return 'video';
  if (mime.startsWith('audio/')) return 'audio';
  return String(item?.media_type || '').toLowerCase() || 'file';
}

function DeferredMediaPreview({ item }) {
  const kind = mediaKind(item);
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  if (kind === 'image') {
    return <AuthImage mediaId={item.id} className="h-full w-full object-cover" alt={item.edit_note || 'Media'} />;
  }

  const load = async () => {
    if (url || loading) return;
    setLoading(true);
    setError('');
    try {
      setUrl(await fetchMediaBlobUrl(item.id));
    } catch (e) {
      setError(message(e, 'Preview unavailable.'));
    } finally {
      setLoading(false);
    }
  };

  if (kind === 'video' && url) return <video src={url} controls preload="metadata" className="h-full w-full object-contain bg-black" />;
  if (kind === 'audio' && url) return <div className="flex h-full items-center px-4"><audio src={url} controls className="w-full" /></div>;

  return (
    <button type="button" onClick={load} className="flex h-full w-full flex-col items-center justify-center gap-2 text-white/50 hover:text-gold">
      {loading ? <Loader2 className="h-6 w-6 animate-spin" /> : kind === 'video' ? <Film className="h-7 w-7" /> : kind === 'audio' ? <AudioLines className="h-7 w-7" /> : <ImageIcon className="h-7 w-7" />}
      <span className="text-xs">{loading ? 'Loading preview…' : error || `Load ${kind} preview`}</span>
    </button>
  );
}

function MediaLibrary() {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState('');
  const [type, setType] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [grid, setGrid] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet('/media-library', { params: { q, media_type: type } });
      setItems(data.items || []);
      setError('');
    } catch (e) {
      setError(message(e, 'Media Library is unavailable.'));
    } finally {
      setLoading(false);
    }
  }, [q, type]);

  useEffect(() => {
    const timer = setTimeout(load, 200);
    return () => clearTimeout(timer);
  }, [load]);

  const update = async (item, body) => {
    try {
      const next = await apiPatch(`/media-library/${item.id}`, body);
      setItems((rows) => rows.map((row) => row.id === item.id ? next : row));
      setError('');
    } catch (e) {
      setError(message(e, 'Media could not be updated.'));
    }
  };

  return (
    <main className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1500px] p-6 sm:p-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div><h2 className="font-display text-4xl text-white">Media Library</h2><p className="mt-2 text-sm text-white/50">Every private image, video, audio asset, and export in one place.</p></div>
          <button onClick={load} className="inline-flex items-center gap-2 rounded border border-white/10 px-3 py-2 text-xs text-white/60"><RefreshCw className="h-3.5 w-3.5" />Refresh</button>
        </div>
        <div className="mt-6 flex flex-wrap gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search media or tags" className="min-w-56 flex-1 rounded bg-white/5 px-3 py-2 text-sm text-white" />
          <select value={type} onChange={(e) => setType(e.target.value)} className="rounded bg-white/5 px-3 text-sm text-white"><option value="">All types</option><option value="image">Images</option><option value="video">Videos</option><option value="audio">Audio</option></select>
          <button onClick={() => setGrid(!grid)} className="rounded border border-white/10 px-3 text-xs text-white/65">{grid ? 'List' : 'Grid'}</button>
        </div>
        {error && <div role="alert" className="mt-4 rounded border border-amber-300/20 bg-amber-300/5 p-3 text-sm text-amber-100">{error}<button onClick={load} className="ml-3 text-gold">Retry</button></div>}
        <div className={`mt-6 gap-3 ${grid ? 'grid sm:grid-cols-2 xl:grid-cols-4' : 'space-y-2'}`}>
          {items.map((item) => (
            <div key={item.id} className="lumina-glass rounded-xl p-4">
              <div className={`overflow-hidden rounded bg-white/[.04] ${grid ? 'aspect-video' : 'h-40'}`}><DeferredMediaPreview item={item} /></div>
              <p className="mt-3 truncate text-sm text-white">{item.edit_note || item.title || item.mime_type}</p>
              <p className="mt-1 text-xs text-white/40">{item.source_module || 'workspace'} · {item.provider || 'Local'} · {mediaKind(item)}</p>
              <div className="mt-3 flex flex-wrap gap-3 text-xs"><button onClick={() => update(item, { favorite: !item.favorite })} className="text-gold">{item.favorite ? '★ Favorite' : '☆ Favorite'}</button><button onClick={() => update(item, { tags: Array.from(new Set([...(item.tags || []), 'review'])) })} className="text-white/55">Tag review</button></div>
            </div>
          ))}
          {!loading && !items.length && !error && <Empty>No matching private media yet.</Empty>}
          {loading && <Empty>Loading media…</Empty>}
        </div>
      </div>
    </main>
  );
}

function jobTarget(job) {
  const module = String(job?.module || '').toLowerCase();
  if (module.includes('video')) return '/studio/video-studio';
  if (module.includes('voice')) return '/studio/voice-studio';
  if (module.includes('image') || module.includes('generate')) return '/studio/generate';
  if (module.includes('code')) return '/studio/code-builder';
  return null;
}

function JobsCenter() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState([]);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setJobs((await apiGet('/workspace/jobs', { params: { status } })).jobs || []);
      setError('');
    } catch (e) {
      setError(message(e, 'Jobs Center is unavailable.'));
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { setLoading(true); load(); }, [load]);
  const hasActive = useMemo(() => jobs.some((job) => ACTIVE_JOB_STATUSES.has(job.status)), [jobs]);
  useEffect(() => {
    if (!hasActive) return undefined;
    const timer = setInterval(load, 1800);
    return () => clearInterval(timer);
  }, [hasActive, load]);

  return (
    <main className="h-full overflow-y-auto"><div className="mx-auto max-w-[1500px] p-6 sm:p-10">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-display text-4xl text-white">Jobs Center</h2><button onClick={load} className="inline-flex items-center gap-2 rounded border border-white/10 px-3 py-2 text-xs text-white/60"><RefreshCw className="h-3.5 w-3.5" />Refresh</button></div>
      <select value={status} onChange={(e) => setStatus(e.target.value)} className="mt-6 rounded bg-white/5 p-2 text-white"><option value="">All statuses</option>{['queued','preparing','processing','rendering','completed','failed','cancelled'].map((x) => <option key={x}>{x}</option>)}</select>
      {error && <div className="mt-4 rounded border border-amber-300/20 bg-amber-300/5 p-3 text-sm text-amber-100">{error}<button onClick={load} className="ml-3 text-gold">Retry</button></div>}
      <div className="mt-5 space-y-2">
        {jobs.map((job) => {
          const target = jobTarget(job);
          const progress = Number.isFinite(Number(job.progress)) ? Math.max(0, Math.min(100, Number(job.progress))) : null;
          return <div key={`${job.module}-${job.id}`} className="lumina-glass rounded-xl p-4"><div className="flex items-center justify-between gap-4"><span className="min-w-0 truncate text-sm text-white">{job.title || job.prompt || job.text || 'Workspace job'}</span><span className="shrink-0 text-xs text-gold">{job.module} · {job.status}</span></div>{progress !== null && <div className="mt-3 h-1.5 overflow-hidden rounded bg-white/10"><div className="h-full bg-gold transition-all" style={{ width: `${progress}%` }} /></div>}<div className="mt-2 flex items-center justify-between text-[11px] text-white/35"><span>{progress !== null ? `${Math.round(progress)}%` : ACTIVE_JOB_STATUSES.has(job.status) ? 'Working…' : ''}</span>{target && <button onClick={() => navigate(target)} className="inline-flex items-center gap-1 text-gold"><Play className="h-3 w-3" />Open module</button>}</div></div>;
        })}
        {!loading && !jobs.length && !error && <Empty>No jobs match this filter.</Empty>}
        {loading && !jobs.length && <Empty>Loading jobs…</Empty>}
      </div>
    </div></main>
  );
}

function Notifications() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const load = useCallback(async () => { try { setRows(await apiGet('/notifications')); setError(''); } catch (e) { setError(message(e, 'Notifications are unavailable.')); } }, []);
  useEffect(() => { load(); }, [load]);
  const markAll = async () => { await apiPost('/notifications/mark-all-read', {}); load(); };
  return <main className="h-full overflow-y-auto"><div className="mx-auto max-w-4xl p-6 sm:p-10"><div className="flex justify-between"><h2 className="font-display text-4xl text-white">Notifications</h2><button onClick={markAll} className="text-xs text-gold">Mark all read</button></div>{error && <p className="mt-4 text-amber-200">{error}</p>}<div className="mt-6 space-y-2">{rows.map((row) => <div key={row.id} className={`lumina-glass flex justify-between rounded-xl p-4 ${row.read ? 'opacity-60' : ''}`}><span><b className="text-sm text-white">{row.title}</b><span className="ml-2 text-xs text-white/45">{row.message}</span></span><span className="flex gap-3 text-xs"><button onClick={() => apiPatch(`/notifications/${row.id}`, { read: true }).then(load)}>Read</button><button onClick={() => apiDelete(`/notifications/${row.id}`).then(load)}>Dismiss</button></span></div>)}{!rows.length && <Empty>No notifications right now.</Empty>}</div></div></main>;
}

export default function PlatformHub({ mode }) {
  return mode === 'media' ? <MediaLibrary /> : mode === 'jobs' ? <JobsCenter /> : <Notifications />;
}
