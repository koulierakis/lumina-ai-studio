import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiDelete, apiGet, apiPost } from '../lib/api';
import { toast } from 'sonner';
import { Plus, Trash2, Film, PlayCircle } from 'lucide-react';
import { RATIOS, FPS_CHOICES, RES_CHOICES } from '../video/model';

export default function VideoProjects() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [aspect, setAspect] = useState('16:9');
  const [fps, setFps] = useState(30);
  const [res, setRes] = useState('1080p');
  const nav = useNavigate();

  const load = async () => {
    setLoading(true);
    const data = await apiGet('/video/projects');
    setProjects(data);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    const data = await apiPost('/video/projects', {
      name: name.trim(), aspect_ratio: aspect, fps, resolution: res,
      state: { clips: [], textOverlays: [], music: null, voiceover: null },
    });
    setCreating(false);
    setName('');
    toast.success('Video project created');
    nav(`/studio/videos/${data.id}`);
  };

  const remove = async (id) => {
    if (!window.confirm('Delete this video project?')) return;
    await apiDelete(`/video/projects/${id}`);
    load();
  };

  return (
    <div className="h-full w-full overflow-y-auto p-10" data-testid="video-projects-page">
      <div className="flex items-start justify-between mb-8">
        <div>
          <h2 className="font-display text-4xl text-white tracking-tight">Videos</h2>
          <p className="text-white/50 text-sm mt-1">
            Simple CapCut-style video projects. Photos, videos, music, voice-over — exported to MP4.
          </p>
        </div>
        <button
          onClick={() => setCreating(true)}
          data-testid="new-video-btn"
          className="flex items-center gap-2 bg-gold text-black text-sm font-medium px-4 py-2.5 rounded hover:bg-gold-soft transition-colors"
        >
          <Plus strokeWidth={1.5} className="w-4 h-4" /> Create Video
        </button>
      </div>

      {creating && (
        <form onSubmit={create} className="lumina-glass rounded-lg p-6 mb-8 max-w-2xl">
          <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="new-video-name"
            className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white focus:border-gold/50 outline-none mb-4"
            placeholder="My video"
            autoFocus
          />
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
              <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Aspect</label>
              <select value={aspect} onChange={(e) => setAspect(e.target.value)} data-testid="new-video-aspect" className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white">
                {RATIOS.map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">FPS</label>
              <select value={fps} onChange={(e) => setFps(Number(e.target.value))} data-testid="new-video-fps" className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white">
                {FPS_CHOICES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Resolution</label>
              <select value={res} onChange={(e) => setRes(e.target.value)} data-testid="new-video-res" className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white">
                {RES_CHOICES.map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
          </div>
          <div className="flex gap-2">
            <button type="submit" data-testid="new-video-submit" className="bg-gold text-black text-sm font-medium px-4 py-2 rounded hover:bg-gold-soft transition-colors">Create</button>
            <button type="button" onClick={() => setCreating(false)} className="text-white/60 hover:text-white text-sm px-3 py-2 rounded transition-colors">Cancel</button>
          </div>
        </form>
      )}

      {loading && <p className="text-white/40 text-sm">Loading…</p>}
      {!loading && projects.length === 0 && (
        <div className="lumina-glass rounded-lg p-10 text-center">
          <Film strokeWidth={1} className="w-8 h-8 mx-auto text-gold/70 mb-3" />
          <h3 className="font-display text-2xl text-white mb-2">No video projects yet</h3>
          <p className="text-white/40 text-sm">Click Create Video to start your first project.</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((p) => (
          <div key={p.id} className="lumina-glass rounded-lg p-5 group" data-testid={`video-project-${p.id}`}>
            <div className="flex items-start justify-between mb-3">
              <div>
                <h3 className="text-white font-medium text-sm">{p.name}</h3>
                <p className="text-white/40 text-[11px] mt-1">
                  {p.aspect_ratio} · {p.fps} fps · {p.resolution} · {(p.state?.clips || []).length} clips
                </p>
              </div>
              <button onClick={() => remove(p.id)} className="text-white/30 hover:text-red-400 transition-colors" title="Delete">
                <Trash2 strokeWidth={1.25} className="w-4 h-4" />
              </button>
            </div>
            <button
              onClick={() => nav(`/studio/videos/${p.id}`)}
              data-testid={`open-video-${p.id}`}
              className="w-full flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 text-white text-xs py-2 rounded transition-colors"
            >
              <PlayCircle strokeWidth={1.5} className="w-4 h-4" /> Open Editor
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
