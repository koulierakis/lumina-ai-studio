// Right-panel content for Sprint 3 tools (mask / text / AI).
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { apiGet, apiPost, uploadFormData, fetchMediaBlobUrl } from '../lib/api';
import Slider from './Slider';
import { newTextLayer, FONT_FAMILIES } from './textLayers';
import {
  Brush, Square as RectIcon, Eraser, RotateCcw, Loader2, Sparkles, Plus,
  Trash2, Eye, EyeOff, Lock, Unlock, Copy, Type as TypeIcon,
} from 'lucide-react';

// ---------- MASK PANEL ----------
export function MaskPanel({
  maskTool, setMaskTool, brushSize, setBrushSize,
  hardness, setHardness, opacity, setOpacity,
  showMask, setShowMask, maskCanvasRef,
  featherPx, setFeatherPx,
}) {
  const btn = (val, label, Icon, testid) => (
    <button
      onClick={() => setMaskTool(val)}
      data-testid={`mask-tool-${testid}`}
      className={`flex items-center gap-1.5 text-xs px-3 py-2 rounded border transition-colors ${
        maskTool === val
          ? 'bg-gold/15 border-gold/60 text-gold'
          : 'bg-white/[0.02] border-white/10 text-white/70 hover:text-white'
      }`}
    >
      <Icon strokeWidth={1.25} className="w-4 h-4" /> {label}
    </button>
  );
  return (
    <div className="mb-6">
      <div className="text-[11px] uppercase tracking-[0.3em] text-white/40 mb-4">Mask</div>
      <div className="grid grid-cols-3 gap-2 mb-4">
        {btn('brush', 'Brush', Brush, 'brush')}
        {btn('erase', 'Erase', Eraser, 'erase')}
        {btn('rect', 'Rect', RectIcon, 'rect')}
      </div>

      <Slider label="Brush size" value={brushSize} min={4} max={400} step={2} defaultValue={80}
        onChange={setBrushSize} onCommit={() => {}} testid="brush-size" />
      <Slider label="Hardness" value={hardness} min={0} max={100} step={1} defaultValue={70}
        onChange={setHardness} onCommit={() => {}} testid="hardness" />
      <Slider label="Opacity" value={opacity} min={5} max={100} step={1} defaultValue={100}
        onChange={setOpacity} onCommit={() => {}} testid="mask-opacity" />
      <Slider label="Feather (px)" value={featherPx} min={0} max={40} step={1} defaultValue={0}
        onChange={setFeatherPx} onCommit={() => {}} testid="feather" />

      <div className="grid grid-cols-2 gap-2 mt-4">
        <button
          onClick={() => maskCanvasRef.current?.clear()}
          data-testid="mask-clear"
          className="flex items-center justify-center gap-1.5 text-xs py-2 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors"
        >
          <Trash2 strokeWidth={1.25} className="w-3.5 h-3.5" /> Clear
        </button>
        <button
          onClick={() => maskCanvasRef.current?.invert()}
          data-testid="mask-invert"
          className="flex items-center justify-center gap-1.5 text-xs py-2 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors"
        >
          <RotateCcw strokeWidth={1.25} className="w-3.5 h-3.5" /> Invert
        </button>
        <button
          onClick={() => maskCanvasRef.current?.feather(featherPx || 6)}
          data-testid="mask-feather"
          className="flex items-center justify-center gap-1.5 text-xs py-2 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors"
        >
          Feather now
        </button>
        <button
          onClick={() => setShowMask(!showMask)}
          data-testid="mask-toggle-visibility"
          className="flex items-center justify-center gap-1.5 text-xs py-2 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors"
        >
          {showMask ? <Eye strokeWidth={1.25} className="w-3.5 h-3.5" /> : <EyeOff strokeWidth={1.25} className="w-3.5 h-3.5" />}
          {showMask ? 'Visible' : 'Hidden'}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 mt-2">
        <button
          onClick={() => maskCanvasRef.current?.undo()}
          data-testid="mask-undo"
          className="text-xs py-2 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors"
        >
          Undo mask
        </button>
        <button
          onClick={() => maskCanvasRef.current?.redo()}
          data-testid="mask-redo"
          className="text-xs py-2 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors"
        >
          Redo mask
        </button>
      </div>

      <p className="text-[11px] text-white/40 mt-4 leading-relaxed">
        White = area to edit · other pixels stay untouched. Mask lives in the
        session and is attached to AI edits when relevant.
      </p>
    </div>
  );
}

// ---------- AI TOOLS PANEL ----------
const AI_TOOLS = [
  { key: 'retouch', label: 'Identity-safe retouch', desc: 'Clean stray dust/hair. Preserves age & texture.' },
  { key: 'enhance', label: 'Enhance', desc: 'Overall quality lift; balanced tones.' },
  { key: 'upscale', label: 'Upscale', desc: 'Reconstruct higher resolution.', note: 'Model-dependent' },
  { key: 'sharpen', label: 'Improve sharpness', desc: 'Micro-detail sharpening.' },
  { key: 'remove_bg', label: 'Remove background', desc: 'Isolate subject.', note: 'Transparent PNG best-effort' },
  { key: 'replace_bg', label: 'Replace background', desc: 'Custom new background.' },
  { key: 'blur_bg', label: 'Blur background', desc: 'Photographic DoF.' },
  { key: 'change_clothes', label: 'Change clothing', desc: 'Only clothing changes.' },
  { key: 'change_location', label: 'Change location', desc: 'Same person, new place.' },
  { key: 'remove_object', label: 'Remove object', desc: 'Uses mask if provided.' },
  { key: 'replace_object', label: 'Replace object', desc: 'Uses mask if provided.' },
  { key: 'outpaint', label: 'Extend / outpaint', desc: 'Extend beyond edges.', note: 'Model-dependent aspect' },
  { key: 'relight', label: 'Relight', desc: 'Change lighting only.' },
  { key: 'restore', label: 'Restore', desc: 'Restore low-res / degraded.' },
];

export function AiToolsPanel({
  mediaId, maskCanvasRef, hasMask, activeAiJob, setActiveAiJob,
  onOpenNewSource, // (mediaId) => go to new editor with saved result
}) {
  const [packs, setPacks] = useState([]);
  const [packId, setPackId] = useState(localStorage.getItem('lumina_active_pack') || '');
  const [tool, setTool] = useState('retouch');
  const [instruction, setInstruction] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [errorText, setErrorText] = useState('');

  useEffect(() => {
    apiGet('/identity-packs').then(setPacks).catch(() => {});
  }, []);

  // Poll active job status
  useEffect(() => {
    if (!activeAiJob) return;
    if (['completed', 'failed', 'canceled'].includes(activeAiJob.status)) return;
    const t = setInterval(async () => {
      try {
        const data = await apiGet(`/editor/ai-jobs/${activeAiJob.id}`);
        setActiveAiJob(data);
        if (data.status === 'completed' && data.output_media_id) {
          setPreviewUrl(await fetchMediaBlobUrl(data.output_media_id));
          toast.success('AI edit complete');
        }
        if (data.status === 'failed') {
          setErrorText(data.error || 'AI edit failed');
          toast.error('AI edit failed');
        }
      } catch {/* ignore */}
    }, 2000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAiJob?.id, activeAiJob?.status]);

  const activeTool = AI_TOOLS.find((t) => t.key === tool);
  const requiresMask = ['remove_object', 'replace_object'].includes(tool);

  const submit = async () => {
    setSubmitting(true);
    setErrorText('');
    setPreviewUrl(null);
    try {
      const fd = new FormData();
      fd.append('source_media_id', mediaId);
      fd.append('tool', tool);
      fd.append('instruction', instruction || '');
      if (packId) fd.append('identity_pack_id', packId);
      const maskUrl = hasMask ? maskCanvasRef.current?.getMask() : null;
      if (maskUrl) {
        const blob = await (await fetch(maskUrl)).blob();
        fd.append('mask', new File([blob], 'mask.png', { type: 'image/png' }));
      }
      const data = await uploadFormData('/editor/ai-edit', fd);
      setActiveAiJob(data);
      toast.info('AI edit submitted');
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Failed to submit';
      setErrorText(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const retry = async () => {
    if (!activeAiJob) return;
    setErrorText('');
    setPreviewUrl(null);
    try {
      const data = await apiPost(`/editor/ai-jobs/${activeAiJob.id}/retry`);
      setActiveAiJob(data);
      toast.info('Retrying');
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Retry failed');
    }
  };

  const cancel = async () => {
    if (!activeAiJob || activeAiJob.status === 'finalizing') return;
    try {
      const data = await apiPost(`/editor/ai-jobs/${activeAiJob.id}/cancel`);
      setActiveAiJob(data);
    } catch { /* ignore */ }
  };

  const openResult = () => {
    if (activeAiJob?.output_media_id) onOpenNewSource(activeAiJob.output_media_id);
  };

  return (
    <div className="mb-6" data-testid="ai-panel">
      <div className="text-[11px] uppercase tracking-[0.3em] text-white/40 mb-4">AI Tools</div>

      <select
        value={tool}
        onChange={(e) => setTool(e.target.value)}
        data-testid="ai-tool-select"
        className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none mb-1"
      >
        {AI_TOOLS.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
      </select>
      <p className="text-[11px] text-white/50 mb-3">
        {activeTool?.desc}{activeTool?.note && <span className="text-gold/80"> · {activeTool.note}</span>}
      </p>

      <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Identity Pack (optional)</label>
      <select
        value={packId}
        onChange={(e) => setPackId(e.target.value)}
        data-testid="ai-pack-select"
        className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white mb-3"
      >
        <option value="">— none —</option>
        {packs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>

      <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Custom instruction</label>
      <textarea
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        rows={3}
        placeholder="Describe exactly what should change…"
        data-testid="ai-instruction"
        className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none resize-none mb-3"
      />

      <div className={`text-[11px] rounded px-2.5 py-1.5 mb-3 ${
        requiresMask && !hasMask ? 'bg-red-500/15 text-red-300' : 'bg-white/[0.03] text-white/50'
      }`} data-testid="mask-status">
        Mask: {hasMask ? 'attached' : 'none'}{requiresMask ? ' · recommended for this tool' : ''}
      </div>

      {activeAiJob && !['completed', 'failed', 'canceled'].includes(activeAiJob.status) && (
        <div className="mb-3 p-3 rounded border border-white/[0.06] bg-white/[0.02] text-xs">
          <div className="flex items-center gap-2 text-white/80">
            <Loader2 strokeWidth={1.25} className="w-3.5 h-3.5 animate-spin text-gold" />
            <span data-testid="ai-job-status">{activeAiJob.status}</span>
          </div>
          {activeAiJob.status !== 'finalizing' && (
            <button
              onClick={cancel}
              className="mt-2 text-[11px] text-white/50 hover:text-red-400"
              data-testid="ai-cancel"
            >
              Cancel
            </button>
          )}
        </div>
      )}

      {activeAiJob?.status === 'failed' && (
        <div className="mb-3 p-3 rounded border border-red-500/40 bg-red-500/10 text-xs text-red-200">
          <div data-testid="ai-error">{errorText || activeAiJob.error}</div>
          <button
            onClick={retry}
            data-testid="ai-retry"
            className="mt-2 text-[11px] px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-white"
          >
            Retry
          </button>
        </div>
      )}

      {previewUrl && (
        <div className="mb-3">
          <div className="text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Result preview</div>
          <img src={previewUrl} alt="ai-result" className="w-full rounded" data-testid="ai-preview" />
          <button
            onClick={openResult}
            data-testid="ai-open-result"
            className="mt-2 w-full text-xs py-2 rounded bg-gold text-black font-medium hover:bg-gold-soft transition-colors"
          >
            Open result as new source
          </button>
        </div>
      )}

      <button
        onClick={submit}
        disabled={submitting || (activeAiJob && !['completed', 'failed', 'canceled'].includes(activeAiJob.status))}
        data-testid="ai-submit"
        className="w-full flex items-center justify-center gap-2 bg-gold text-black font-medium py-2.5 rounded hover:bg-gold-soft disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <Sparkles strokeWidth={1.5} className="w-4 h-4" />
        {submitting ? 'Submitting…' : 'Run AI edit'}
      </button>
    </div>
  );
}

// ---------- TEXT LAYERS PANEL ----------
export function TextPanel({ layers, setLayers, commit, selectedId, setSelectedId }) {
  const sel = useMemo(() => layers.find((l) => l.id === selectedId) || null, [layers, selectedId]);

  const add = () => {
    const nl = newTextLayer();
    setLayers([...layers, nl], true);
    setSelectedId(nl.id);
    commit();
  };
  const update = (patch, doCommit = false) => {
    if (!sel) return;
    const next = layers.map((l) => (l.id === sel.id ? { ...l, ...patch } : l));
    setLayers(next, true);
    if (doCommit) commit();
  };
  const remove = (id) => {
    setLayers(layers.filter((l) => l.id !== id), true);
    if (selectedId === id) setSelectedId(null);
    commit();
  };
  const duplicate = (l) => {
    const nl = { ...l, id: `txt_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`, x: l.x + 20, y: l.y + 20 };
    setLayers([...layers, nl], true);
    setSelectedId(nl.id);
    commit();
  };

  return (
    <div className="mb-6" data-testid="text-panel">
      <div className="flex items-center justify-between mb-4">
        <div className="text-[11px] uppercase tracking-[0.3em] text-white/40">Text Layers</div>
        <button onClick={add} data-testid="text-add" className="p-1.5 rounded bg-gold/10 text-gold hover:bg-gold/20">
          <Plus strokeWidth={1.5} className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="space-y-2 mb-4">
        {layers.map((l) => (
          <div key={l.id} className={`rounded border p-2 ${selectedId === l.id ? 'border-gold/50 bg-gold/[0.04]' : 'border-white/[0.06] bg-white/[0.02]'}`}>
            <div className="flex items-center gap-1">
              <button onClick={() => setSelectedId(l.id)} className="flex-1 text-left text-xs text-white/80 truncate">{l.text || '(empty)'}</button>
              <button onClick={() => update({ visible: !l.visible }, true)} className="p-1 text-white/40 hover:text-white">{l.visible ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}</button>
              <button onClick={() => update({ locked: !l.locked }, true)} className="p-1 text-white/40 hover:text-white">{l.locked ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />}</button>
              <button onClick={() => duplicate(l)} className="p-1 text-white/40 hover:text-white"><Copy className="w-3 h-3" /></button>
              <button onClick={() => remove(l.id)} className="p-1 text-white/40 hover:text-red-400"><Trash2 className="w-3 h-3" /></button>
            </div>
          </div>
        ))}
      </div>
      {sel && (
        <div className="space-y-3">
          <div><label className="block text-[10px] uppercase tracking-widest text-white/40 mb-1">Text</label><textarea value={sel.text} onChange={(e) => update({ text: e.target.value })} onBlur={() => commit()} rows={2} className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white" /></div>
          <div><label className="block text-[10px] uppercase tracking-widest text-white/40 mb-1">Font</label><select value={sel.fontFamily} onChange={(e) => update({ fontFamily: e.target.value }, true)} className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white">{FONT_FAMILIES.map((f) => <option key={f} value={f}>{f}</option>)}</select></div>
          <div className="grid grid-cols-2 gap-2">
            <div><label className="block text-[10px] uppercase tracking-widest text-white/40 mb-1">Size</label><input type="number" min="8" max="400" value={sel.fontSize} onChange={(e) => update({ fontSize: Number(e.target.value) })} onBlur={() => commit()} className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white" /></div>
            <div><label className="block text-[10px] uppercase tracking-widest text-white/40 mb-1">Color</label><input type="color" value={sel.color} onChange={(e) => update({ color: e.target.value }, true)} className="w-full h-8 bg-black/50 border border-white/10 rounded px-1" /></div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div><label className="block text-[10px] uppercase tracking-widest text-white/40 mb-1">Weight</label><select value={sel.fontWeight} onChange={(e) => update({ fontWeight: e.target.value }, true)} className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white"><option value="400">Regular</option><option value="600">Semibold</option><option value="700">Bold</option><option value="800">Extra Bold</option></select></div>
            <div><label className="block text-[10px] uppercase tracking-widest text-white/40 mb-1">Align</label><select value={sel.textAlign} onChange={(e) => update({ textAlign: e.target.value }, true)} className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-xs text-white"><option value="left">Left</option><option value="center">Center</option><option value="right">Right</option></select></div>
          </div>
          <Slider label="Opacity" value={Math.round((sel.opacity ?? 1) * 100)} min={0} max={100} step={1} defaultValue={100} onChange={(v) => update({ opacity: v / 100 })} onCommit={() => commit()} />
          <Slider label="Rotation" value={sel.rotation || 0} min={-180} max={180} step={1} defaultValue={0} onChange={(v) => update({ rotation: v })} onCommit={() => commit()} />
        </div>
      )}
      {!sel && <p className="text-[11px] text-white/35">Select or add a text layer.</p>}
    </div>
  );
}
