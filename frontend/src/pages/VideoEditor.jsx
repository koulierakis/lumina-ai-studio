import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { apiGet, apiPut, apiPost, uploadFormData } from '../lib/api';
import Timeline from '../video/Timeline';
import VideoPreview from '../video/VideoPreview';
import Slider from '../editor/Slider';
import useVoiceRecorder from '../video/useVoiceRecorder';
import {
  ArrowLeft, Play, Pause, Upload, Music2, Mic, Type as TypeIcon,
  Sparkles, Save, Download, Loader2, Scissors,
} from 'lucide-react';
import {
  newClip, newOverlay, totalDuration, TRANSITIONS, KEN_BURNS, FILTERS,
  DEFAULT_ADJUST, effectiveDuration, locateAt,
} from '../video/model';

export default function VideoEditor() {
  const { projectId } = useParams();
  const nav = useNavigate();

  const [project, setProject] = useState(null);
  const [state, setState] = useState({ clips: [], textOverlays: [], music: null, voiceover: null });
  const [selectedClipId, setSelectedClipId] = useState(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [expPct, setExpPct] = useState(0);
  const [expMsg, setExpMsg] = useState('');
  const [rightPanel, setRightPanel] = useState('clip'); // clip | text | audio | export
  const [uploading, setUploading] = useState(0);
  const fileInputRef = useRef(null);
  const musicInputRef = useRef(null);
  const voice = useVoiceRecorder();
  const rafRef = useRef(null);

  // Load project
  useEffect(() => {
    (async () => {
      try {
        const r = await apiGet(`/video/projects/${projectId}`);
        setProject(r);
        setState(r.state || { clips: [], textOverlays: [], music: null, voiceover: null });
      } catch (err) {
        toast.error('Video project not found');
        nav('/studio/videos');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Autosave (throttled) — every 2s
  const saveTimer = useRef(null);
  useEffect(() => {
    if (!project) return;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        await apiPut(`/video/projects/${projectId}`, {
          state,
          name: project.name,
          aspect_ratio: project.aspect_ratio, fps: project.fps, resolution: project.resolution,
        });
      } catch { /* ignore */ }
    }, 2000);
    return () => clearTimeout(saveTimer.current);
  }, [state, project, projectId]);

  // Play/pause + advancing playhead
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const tick = (now) => {
      const dt = (now - last) / 1000;
      last = now;
      setCurrentTime((t) => {
        const total = totalDuration(state);
        const n = t + dt;
        if (n >= total) { setPlaying(false); return total; }
        return n;
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [playing, state]);

  // ----- Asset upload -----
  const uploadFiles = async (files) => {
    if (!files || files.length === 0) return;
    setUploading((n) => n + files.length);
    try {
      for (const f of files) {
        const fd = new FormData();
        fd.append('file', f);
          const res = await uploadFormData('/video/assets', fd);
        const kind = f.type.startsWith('video/') ? 'video' : 'photo';
        // Probe duration for video assets
        let dur = 4;
        if (kind === 'video') {
          try { dur = await probeVideoDuration(URL.createObjectURL(f)); } catch { /* ignore */ }
        }
        const clip = newClip(res.id, kind, res.mime_type, dur);
        if (kind === 'video') { clip.duration = dur; clip.trimStart = 0; clip.trimEnd = dur; }
        setState((s) => ({ ...s, clips: [...s.clips, clip] }));
      }
      toast.success(`${files.length} clip${files.length > 1 ? 's' : ''} added`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading((n) => Math.max(0, n - files.length));
    }
  };

  const uploadMusic = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await uploadFormData('/video/assets', fd);
      setState((s) => ({ ...s, music: { assetId: res.id, mime: res.mime_type, volume: 60, fadeIn: 1, fadeOut: 1 } }));
      toast.success('Music added');
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Music upload failed');
    }
  };

  const finishVoiceOver = async () => {
    const blob = await voice.stop();
    if (!blob) return;
    const fd = new FormData();
    fd.append('file', new File([blob], `voiceover.webm`, { type: 'audio/webm' }));
    try {
      const res = await uploadFormData('/video/assets', fd);
      setState((s) => ({ ...s, voiceover: { assetId: res.id, mime: res.mime_type, volume: 100 } }));
      toast.success('Voice-over saved');
    } catch (err) {
      toast.error('Voice-over upload failed');
    }
  };

  // ----- Clip ops -----
  const selectedClip = state.clips.find((c) => c.id === selectedClipId) || null;
  const updateClip = (id, patch) => setState((s) => ({
    ...s, clips: s.clips.map((c) => (c.id === id ? { ...c, ...patch } : c)),
  }));

  const deleteClip = (id) => setState((s) => ({ ...s, clips: s.clips.filter((c) => c.id !== id) }));
  const duplicateClip = (id) => setState((s) => {
    const i = s.clips.findIndex((c) => c.id === id);
    if (i < 0) return s;
    const clone = { ...s.clips[i], id: `c-${Date.now()}-${Math.random().toString(36).slice(2, 6)}` };
    const arr = [...s.clips.slice(0, i + 1), clone, ...s.clips.slice(i + 1)];
    return { ...s, clips: arr };
  });
  const reorder = (idx, dir) => setState((s) => {
    const j = idx + dir;
    if (j < 0 || j >= s.clips.length) return s;
    const arr = s.clips.slice();
    [arr[idx], arr[j]] = [arr[j], arr[idx]];
    return { ...s, clips: arr };
  });
  const trimClip = (id, dStart, dEnd) => updateClip(id, {
    trimStart: Math.max(0, (state.clips.find((c) => c.id === id).trimStart || 0) + dStart),
    trimEnd: Math.max(0.1, (state.clips.find((c) => c.id === id).trimEnd || state.clips.find((c) => c.id === id).duration) + dEnd),
  });
  const splitAtPlayhead = () => {
    const { index, localTime } = locateAt(state, currentTime);
    const c = state.clips[index];
    if (!c || localTime <= 0.1) return;
    if (c.kind === 'video') {
      const left = { ...c, id: `${c.id}-l`, trimEnd: (c.trimStart || 0) + localTime };
      const right = { ...c, id: `${c.id}-r`, trimStart: (c.trimStart || 0) + localTime };
      setState((s) => ({ ...s, clips: [...s.clips.slice(0, index), left, right, ...s.clips.slice(index + 1)] }));
    } else {
      const dLeft = localTime;
      const dRight = c.duration - localTime;
      const left = { ...c, id: `${c.id}-l`, duration: dLeft };
      const right = { ...c, id: `${c.id}-r`, duration: dRight };
      setState((s) => ({ ...s, clips: [...s.clips.slice(0, index), left, right, ...s.clips.slice(index + 1)] }));
    }
  };

  // ----- Text overlay ops -----
  const addOverlay = () => setState((s) => ({
    ...s, textOverlays: [...(s.textOverlays || []), { ...newOverlay('Text'), start: currentTime, end: currentTime + 3 }],
  }));

  // ----- Save + Export -----
  const doSave = async () => {
    setSaving(true);
    try {
      await apiPut(`/video/projects/${projectId}`, { state });
      toast.success('Saved');
    } finally { setSaving(false); }
  };

  const doExport = async () => {
    if (!state.clips.length) { toast.error('Add clips first'); return; }
    setExporting(true); setExpPct(0); setExpMsg('Preparing…');
    try {
      const mod = await import('../video/ffmpegExport');
      const blob = await mod.exportProject({
        project: { ...project, state },
        api: apiGet,
        onProgress: (msg, pct) => { setExpMsg(msg); setExpPct(pct); },
        onLog: () => {},
      });
      setExpMsg('Uploading…');
      // Upload to backend for gallery
      const fd = new FormData();
      fd.append('file', new File([blob], `${project.name || 'video'}.mp4`, { type: 'video/mp4' }));
      await uploadFormData(`/video/projects/${projectId}/export`, fd);
      // Trigger local download
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${project.name || 'video'}.mp4`; a.click();
      URL.revokeObjectURL(url);
      toast.success('Export complete — downloaded');
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(err);
      toast.error(err?.message || 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  if (!project) return <div className="p-10 text-white/50">Loading video…</div>;

  return (
    <div className="h-full w-full flex flex-col bg-ink-950 text-white" data-testid="video-editor">
      {/* Top bar */}
      <div className="h-12 shrink-0 border-b border-white/[0.06] flex items-center justify-between px-4">
        <div className="flex items-center gap-3">
          <button onClick={() => nav('/studio/videos')} className="text-white/60 hover:text-gold" data-testid="back-video-projects" title="Back">
            <ArrowLeft strokeWidth={1.25} className="w-4 h-4" />
          </button>
          <input
            value={project.name}
            onChange={(e) => setProject({ ...project, name: e.target.value })}
            onBlur={doSave}
            className="bg-transparent border-none text-sm text-white focus:outline-none"
            data-testid="video-name"
          />
          <span className="text-xs text-white/40">{project.aspect_ratio} · {project.fps} fps · {project.resolution}</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={doSave} disabled={saving} data-testid="save-video-btn" className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors">
            <Save strokeWidth={1.25} className="w-3.5 h-3.5" /> {saving ? 'Saving…' : 'Save'}
          </button>
          <button onClick={doExport} disabled={exporting} data-testid="export-video-btn" className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-gold text-black font-medium hover:bg-gold-soft transition-colors disabled:opacity-50">
            {exporting ? <Loader2 strokeWidth={1.5} className="w-3.5 h-3.5 animate-spin" /> : <Download strokeWidth={1.25} className="w-3.5 h-3.5" />}
            {exporting ? `Exporting ${expPct}%` : 'Export MP4'}
          </button>
        </div>
      </div>

      {/* Main area */}
      <div className="flex-1 flex min-h-0">
        {/* Left: import controls */}
        <div className="w-56 shrink-0 border-r border-white/[0.06] p-4 flex flex-col gap-2 text-sm">
          <button
            onClick={() => fileInputRef.current?.click()}
            data-testid="import-btn"
            className="flex items-center gap-2 bg-gold text-black text-xs font-medium px-3 py-2 rounded hover:bg-gold-soft transition-colors"
          >
            <Upload strokeWidth={1.5} className="w-4 h-4" /> Import media
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm"
            onChange={(e) => uploadFiles(e.target.files)}
            className="hidden"
            data-testid="import-input"
          />

          <button onClick={() => musicInputRef.current?.click()} data-testid="music-btn" className="flex items-center gap-2 bg-white/5 hover:bg-white/10 text-white text-xs px-3 py-2 rounded transition-colors">
            <Music2 strokeWidth={1.5} className="w-4 h-4" /> Add music
          </button>
          <input
            ref={musicInputRef}
            type="file"
            accept="audio/mpeg,audio/mp3,audio/wav,audio/webm"
            onChange={(e) => e.target.files[0] && uploadMusic(e.target.files[0])}
            className="hidden"
            data-testid="music-input"
          />

          {!voice.recording ? (
            <button onClick={voice.start} data-testid="voice-start" className="flex items-center gap-2 bg-white/5 hover:bg-white/10 text-white text-xs px-3 py-2 rounded transition-colors">
              <Mic strokeWidth={1.5} className="w-4 h-4" /> Record voice-over
            </button>
          ) : (
            <button onClick={finishVoiceOver} data-testid="voice-stop" className="flex items-center gap-2 bg-red-500 hover:bg-red-600 text-white text-xs px-3 py-2 rounded">
              <Mic strokeWidth={1.5} className="w-4 h-4" /> Stop ({voice.elapsed.toFixed(1)}s)
            </button>
          )}

          <button onClick={addOverlay} data-testid="add-text-btn" className="flex items-center gap-2 bg-white/5 hover:bg-white/10 text-white text-xs px-3 py-2 rounded transition-colors">
            <TypeIcon strokeWidth={1.5} className="w-4 h-4" /> Add text at playhead
          </button>

          {uploading > 0 && <p className="text-[11px] text-white/50 mt-2">Uploading {uploading}…</p>}

          <div className="mt-auto text-[10px] text-white/30 leading-relaxed pt-4">
            Duration: <span className="text-white/70">{totalDuration(state).toFixed(1)}s</span><br />
            Clips: {state.clips.length}<br />
            Autosave every 2s.
          </div>
        </div>

        {/* Center: preview + play controls */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0 relative">
            <VideoPreview state={state} currentTime={currentTime} aspect={project.aspect_ratio} playing={playing} />
          </div>
          <div className="h-10 shrink-0 border-t border-white/[0.06] flex items-center px-4 gap-3 text-xs text-white/70">
            <button onClick={() => setPlaying((p) => !p)} data-testid="play-pause" className="text-white hover:text-gold" title={playing ? 'Pause' : 'Play'}>
              {playing ? <Pause strokeWidth={1.5} className="w-5 h-5" /> : <Play strokeWidth={1.5} className="w-5 h-5" />}
            </button>
            <div className="tabular-nums" data-testid="time-readout">{currentTime.toFixed(1)}s / {totalDuration(state).toFixed(1)}s</div>
            <button onClick={splitAtPlayhead} data-testid="split-btn" className="flex items-center gap-1 text-xs text-white/70 hover:text-gold" title="Split at playhead">
              <Scissors strokeWidth={1.5} className="w-3.5 h-3.5" /> Split
            </button>
            <div className="flex-1" />
            {exporting && <span className="text-gold" data-testid="export-status">{expMsg} · {expPct}%</span>}
          </div>
          <Timeline
            state={state} currentTime={currentTime} setCurrentTime={setCurrentTime}
            selectedClipId={selectedClipId} setSelectedClipId={(id) => { setSelectedClipId(id); setRightPanel('clip'); }}
            onReorder={reorder}
            onDeleteClip={deleteClip}
            onDuplicateClip={duplicateClip}
            onSplit={splitAtPlayhead}
            onTrim={trimClip}
          />
        </div>

        {/* Right: contextual settings */}
        <aside className="w-80 shrink-0 border-l border-white/[0.06] p-4 overflow-y-auto">
          <div className="flex gap-1 mb-4 text-[11px]">
            {[['clip', 'Clip'], ['text', 'Text'], ['audio', 'Audio']].map(([k, l]) => (
              <button key={k} onClick={() => setRightPanel(k)} data-testid={`panel-${k}`}
                className={`px-3 py-1.5 rounded ${rightPanel === k ? 'bg-gold text-black font-medium' : 'bg-white/5 text-white/70 hover:text-white'}`}>{l}</button>
            ))}
          </div>

          {rightPanel === 'clip' && (selectedClip ? (
            <ClipSettings clip={selectedClip} onChange={(p) => updateClip(selectedClip.id, p)} />
          ) : <p className="text-white/40 text-xs">Select a clip on the timeline.</p>)}

          {rightPanel === 'text' && (
            <TextOverlaysPanel state={state} setState={setState} currentTime={currentTime} />
          )}

          {rightPanel === 'audio' && (
            <AudioPanel state={state} setState={setState} />
          )}
        </aside>
      </div>
    </div>
  );
}

function ClipSettings({ clip, onChange }) {
  const a = clip.adjust || DEFAULT_ADJUST;
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.3em] text-white/40 mb-3">Clip · {clip.kind}</div>

      {clip.kind === 'photo' && (
        <>
          <Slider label="Duration (s)" value={clip.duration} min={0.5} max={30} step={0.1} defaultValue={4}
            onChange={(v) => onChange({ duration: v })} onCommit={() => {}} testid="clip-duration" />
          <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-1">Ken Burns</label>
          <select value={clip.kenBurns} onChange={(e) => onChange({ kenBurns: e.target.value })} data-testid="ken-burns"
            className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white mb-3">
            {KEN_BURNS.map((k) => <option key={k}>{k}</option>)}
          </select>
        </>
      )}

      <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-1">Transition (out)</label>
      <select value={clip.transition} onChange={(e) => onChange({ transition: e.target.value })} data-testid="clip-transition"
        className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white mb-3">
        {TRANSITIONS.map((t) => <option key={t}>{t}</option>)}
      </select>

      <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-1">Filter</label>
      <select value={clip.filter} onChange={(e) => onChange({ filter: e.target.value })} data-testid="clip-filter"
        className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white mb-3">
        {FILTERS.map((t) => <option key={t}>{t}</option>)}
      </select>

      <div className="text-[11px] uppercase tracking-[0.3em] text-white/40 mb-2 mt-3">Adjustments</div>
      {['brightness', 'contrast', 'saturation', 'temperature', 'sharpness', 'blur'].map((k) => (
        <Slider key={k}
          label={k.charAt(0).toUpperCase() + k.slice(1)}
          value={a[k]}
          min={k === 'blur' ? 0 : -100}
          max={k === 'sharpness' || k === 'blur' ? 100 : 100}
          step={1}
          defaultValue={0}
          onChange={(v) => onChange({ adjust: { ...a, [k]: v } })}
          onCommit={() => {}}
          testid={`clip-${k}`}
        />
      ))}
      <button onClick={() => onChange({ adjust: { ...DEFAULT_ADJUST } })} className="text-[11px] text-white/50 hover:text-gold">Reset adjustments</button>

      {clip.kind === 'video' && (
        <Slider label="Original volume" value={clip.volume ?? 100} min={0} max={100} step={1} defaultValue={100}
          onChange={(v) => onChange({ volume: v })} onCommit={() => {}} testid="clip-volume" />
      )}
    </div>
  );
}

function TextOverlaysPanel({ state, setState, currentTime }) {
  const list = state.textOverlays || [];
  const update = (id, patch) => setState((s) => ({ ...s, textOverlays: s.textOverlays.map((o) => o.id === id ? { ...o, ...patch } : o) }));
  const remove = (id) => setState((s) => ({ ...s, textOverlays: s.textOverlays.filter((o) => o.id !== id) }));

  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.3em] text-white/40 mb-3">Text overlays</div>
      {list.length === 0 && <p className="text-[11px] text-white/40">Add text at playhead from the left toolbar.</p>}
      {list.map((t) => (
        <div key={t.id} className="mb-4 p-3 rounded bg-white/[0.02] border border-white/[0.06]" data-testid={`overlay-${t.id}`}>
          <textarea
            value={t.text}
            onChange={(e) => update(t.id, { text: e.target.value })}
            rows={2}
            className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white resize-none mb-2"
            data-testid={`overlay-text-${t.id}`}
          />
          <div className="grid grid-cols-2 gap-2 mb-2">
            <label className="text-[10px] text-white/50">Start (s)
              <input type="number" value={t.start ?? 0} step="0.1" min={0}
                onChange={(e) => update(t.id, { start: Number(e.target.value) })}
                className="w-full mt-0.5 bg-black/50 border border-white/10 rounded px-2 py-1 text-xs text-white" />
            </label>
            <label className="text-[10px] text-white/50">End (s)
              <input type="number" value={t.end ?? 3} step="0.1" min={0}
                onChange={(e) => update(t.id, { end: Number(e.target.value) })}
                className="w-full mt-0.5 bg-black/50 border border-white/10 rounded px-2 py-1 text-xs text-white" />
            </label>
          </div>
          <div className="flex items-center gap-2 mb-2">
            <input type="color" value={t.color} onChange={(e) => update(t.id, { color: e.target.value })} className="w-6 h-6" />
            <input type="number" value={t.fontSize} min={8} max={400}
              onChange={(e) => update(t.id, { fontSize: Number(e.target.value) })}
              className="w-16 bg-black/50 border border-white/10 rounded px-2 py-0.5 text-xs text-white" />
            <button onClick={() => remove(t.id)} className="ml-auto text-[10px] text-red-400 hover:text-red-300">Delete</button>
          </div>
        </div>
      ))}
      <p className="text-[10px] text-white/30 mt-2">Greek + English are both supported. Playhead now: {currentTime.toFixed(1)}s.</p>
    </div>
  );
}

function AudioPanel({ state, setState }) {
  const setMusic = (patch) => setState((s) => ({ ...s, music: s.music ? { ...s.music, ...patch } : s.music }));
  const setVoice = (patch) => setState((s) => ({ ...s, voiceover: s.voiceover ? { ...s.voiceover, ...patch } : s.voiceover }));
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.3em] text-white/40 mb-3">Audio</div>
      <div className="mb-6">
        <p className="text-[11px] text-white/60 mb-2">Music</p>
        {state.music ? (
          <>
            <Slider label="Volume" value={state.music.volume ?? 60} min={0} max={100} step={1} defaultValue={60}
              onChange={(v) => setMusic({ volume: v })} onCommit={() => {}} testid="music-volume" />
            <Slider label="Fade in (s)" value={state.music.fadeIn ?? 0} min={0} max={10} step={0.5} defaultValue={1}
              onChange={(v) => setMusic({ fadeIn: v })} onCommit={() => {}} testid="music-fade-in" />
            <Slider label="Fade out (s)" value={state.music.fadeOut ?? 0} min={0} max={10} step={0.5} defaultValue={1}
              onChange={(v) => setMusic({ fadeOut: v })} onCommit={() => {}} testid="music-fade-out" />
            <button onClick={() => setState((s) => ({ ...s, music: null }))} className="text-[11px] text-red-400 hover:text-red-300">Remove music</button>
          </>
        ) : <p className="text-[11px] text-white/40">No music. Add from the left toolbar.</p>}
      </div>
      <div>
        <p className="text-[11px] text-white/60 mb-2">Voice-over</p>
        {state.voiceover ? (
          <>
            <Slider label="Volume" value={state.voiceover.volume ?? 100} min={0} max={100} step={1} defaultValue={100}
              onChange={(v) => setVoice({ volume: v })} onCommit={() => {}} testid="voice-volume" />
            <button onClick={() => setState((s) => ({ ...s, voiceover: null }))} className="text-[11px] text-red-400 hover:text-red-300">Remove voice-over</button>
          </>
        ) : <p className="text-[11px] text-white/40">No voice-over. Record from the left toolbar.</p>}
      </div>
    </div>
  );
}

async function probeVideoDuration(url) {
  return new Promise((resolve, reject) => {
    const v = document.createElement('video');
    v.preload = 'metadata';
    v.onloadedmetadata = () => { resolve(v.duration || 4); URL.revokeObjectURL(url); };
    v.onerror = () => reject(new Error('probe failed'));
    v.src = url;
  });
}
