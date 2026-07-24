import { useEffect, useMemo, useReducer, useRef, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { apiGet, apiPost, apiPut, uploadFormData, fetchMediaBlobUrl } from '../lib/api';
import EditorCanvas from '../editor/EditorCanvas';
import Slider from '../editor/Slider';
import useEditorShortcuts from '../editor/useEditorShortcuts';
import useClipboardPaste from '../editor/useClipboardPaste';
import MaskCanvas from '../editor/MaskCanvas';
import TextLayerHUD from '../editor/TextLayerHUD';
import { MaskPanel, AiToolsPanel, TextPanel } from '../editor/Sprint3Panels';
import {
  DEFAULT_STATE, DEFAULT_ADJUST, ADJUST_RANGES, ADJUST_LABELS,
  reduce, initialHistory, updateAdjust, updateTransform, updateFilter,
} from '../editor/state';
import { FILTER_KEYS, cssForFilter } from '../editor/filters';
import { exportBlob } from '../editor/pipeline';
import { loadCustomPresets, saveCustomPreset, deleteCustomPreset } from '../editor/customPresets';
import {
  Undo2, Redo2, ZoomIn, ZoomOut, Maximize2, Square,
  RotateCcw, RotateCw, FlipHorizontal, FlipVertical, Crop as CropIcon,
  SlidersHorizontal, Palette, History as HistoryIcon, Sparkles, Download,
  Save, Eye, SplitSquareHorizontal, ArrowLeft,
  Brush as BrushIcon, Type as TypeIcon, Wand2,
} from 'lucide-react';

const TOOLS = [
  { key: 'transform', label: 'Transform', icon: CropIcon },
  { key: 'adjust', label: 'Adjustments', icon: SlidersHorizontal },
  { key: 'filter', label: 'Filters', icon: Palette },
  { key: 'mask', label: 'Mask', icon: BrushIcon },
  { key: 'text', label: 'Text', icon: TypeIcon },
  { key: 'ai', label: 'AI Tools', icon: Wand2 },
  { key: 'history', label: 'History', icon: HistoryIcon },
];

const CROP_RATIOS = ['off', 'free', '1:1', '16:9', '9:16', '4:5', '3:2'];

export default function Editor() {
  const { mediaId } = useParams();
  const nav = useNavigate();

  const [imgUrl, setImgUrl] = useState(null);
  const [imgEl, setImgEl] = useState(null);
  const [tool, setTool] = useState('adjust');
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [cropMode, setCropMode] = useState('off');
  const [cropRect, setCropRect] = useState(null);
  const [compareRatio, setCompareRatio] = useState(null);
  const [compareHold, setCompareHold] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exportFormat, setExportFormat] = useState('image/png');
  const [exportQuality, setExportQuality] = useState(0.95);
  const [customPresets, setCustomPresets] = useState(loadCustomPresets());

  // ----- Sprint 3 additions -----
  const maskCanvasRef = useRef(null);
  const [maskTool, setMaskTool] = useState('brush');   // brush | erase | rect
  const [brushSize, setBrushSize] = useState(80);
  const [hardness, setHardness] = useState(70);
  const [maskOpacity, setMaskOpacity] = useState(100);
  const [showMask, setShowMask] = useState(true);
  const [featherPx, setFeatherPx] = useState(6);
  const [hasMask, setHasMask] = useState(false);
  const [selectedTextId, setSelectedTextId] = useState(null);
  const [activeAiJob, setActiveAiJob] = useState(null);
  const [imgRect, setImgRect] = useState(null);
  const stageRef = useRef(null);

  const [h, dispatch] = useReducer(reduce, undefined, () => initialHistory(DEFAULT_STATE));
  const state = h.present;

  // Load image
  useEffect(() => {
    let revoke = null;
    setImgUrl(null);
    fetchMediaBlobUrl(mediaId)
      .then((url) => { revoke = url; setImgUrl(url); })
      .catch(() => toast.error('Failed to load image'));
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [mediaId]);

  // Load session (server + local fallback)
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await apiGet(`/editor/sessions/${mediaId}`);
        if (!cancelled && data?.state) {
          dispatch({ type: 'RESTORE', state: data.state });
          toast.success('Session restored');
        }
      } catch {
        // fallback to local
        const local = localStorage.getItem(`lumina_editor_${mediaId}`);
        if (local && !cancelled) {
          try { dispatch({ type: 'RESTORE', state: JSON.parse(local) }); } catch { /* noop */ }
        }
      }
    }
    load();
    return () => { cancelled = true; };
  }, [mediaId]);

  // Autosave — throttled
  const autosaveTimer = useRef(null);
  useEffect(() => {
    localStorage.setItem(`lumina_editor_${mediaId}`, JSON.stringify(state));
    clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      apiPut(`/editor/sessions/${mediaId}`, { state }).catch(() => {});
    }, 1500);
    return () => clearTimeout(autosaveTimer.current);
  }, [mediaId, state]);

  // ----- Undo / redo / reset -----
  const undo = () => dispatch({ type: 'UNDO' });
  const redo = () => dispatch({ type: 'REDO' });
  const resetAll = () => dispatch({ type: 'RESET_ALL' });
  const setState = (next) => dispatch({ type: 'SET', next });
  const previewState = (next) => dispatch({ type: 'REPLACE', next });
  const commit = () => dispatch({ type: 'COMMIT' });

  // Text layer helpers (silent updates while dragging, commit on release)
  const setTextLayers = useCallback((next, silent = false) => {
    dispatch({ type: silent ? 'REPLACE' : 'SET', next: { ...state, textLayers: next } });
  }, [state]);

  // Mask -> state (silent; committed on paint release inside MaskCanvas)
  const onMaskChange = useCallback((dataUrl) => {
    setHasMask(!!dataUrl);
    dispatch({ type: 'REPLACE', next: { ...state, mask: dataUrl } });
  }, [state]);

  // Clipboard paste
  useClipboardPaste(useCallback(async (blob, mime) => {
    // Upload as a new reference photo in a "clipboard" pack and switch source
    try {
      let clipPackId = localStorage.getItem('lumina_clipboard_pack');
      if (!clipPackId) {
        const c = await apiPost('/identity-packs', { name: 'Clipboard' });
        clipPackId = c.id;
        localStorage.setItem('lumina_clipboard_pack', clipPackId);
      }
      const fd = new FormData();
      fd.append('files', new File([blob], 'clipboard.png', { type: mime || 'image/png' }));
      const res = await uploadFormData(`/identity-packs/${clipPackId}/photos`, fd);
      const newId = res.photo_ids[res.photo_ids.length - 1];
      if (newId) {
        toast.success('Pasted image opened as new source');
        nav(`/studio/editor/${newId}`);
      }
    } catch (err) {
      toast.error('Could not open pasted image');
    }
  }, [nav]));

  // ----- Save version -----
  const doSave = useCallback(async () => {
    if (!imgEl || saving) return;
    setSaving(true);
    try {
      const stateToApply = { ...state, transform: { ...state.transform, crop: cropRect || state.transform.crop } };
      const blob = await exportBlob(imgEl, stateToApply, { format: 'image/png', quality: 1 });
      const fd = new FormData();
      fd.append('source_media_id', mediaId);
      fd.append('edit_note', 'Edited version');
      fd.append('file', blob, `edited-${Date.now()}.png`);
      await uploadFormData('/editor/versions', fd);
      toast.success('Version saved to Gallery');
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [imgEl, saving, state, cropRect, mediaId]);

  // ----- Export download -----
  const doExport = async () => {
    if (!imgEl) return;
    try {
      const stateToApply = { ...state, transform: { ...state.transform, crop: cropRect || state.transform.crop } };
      const blob = await exportBlob(imgEl, stateToApply, { format: exportFormat, quality: exportQuality });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const ext = exportFormat.split('/')[1] || 'png';
      a.href = url;
      a.download = `lumina-edit-${Date.now()}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('Downloaded');
    } catch (err) {
      toast.error('Export failed');
      if (process.env.NODE_ENV !== 'production') console.error(err);
    }
  };

  // ----- Keyboard shortcuts -----
  const shortcuts = useMemo(() => ({
    undo, redo, save: doSave, resetAll,
    zoomIn: () => setZoom((z) => Math.min(8, z * 1.15)),
    zoomOut: () => setZoom((z) => Math.max(0.05, z / 1.15)),
    fit: () => { setZoom(1); setPan({ x: 0, y: 0 }); },
    actual: () => setZoom(1),
    escape: () => {
      setCropMode('off'); setCropRect(null); setCompareRatio(null);
      setSelectedTextId(null);
    },
  }), [doSave]);
  useEditorShortcuts(shortcuts);

  // Delete selected text layer via Delete key (only when a text is selected)
  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target && e.target.tagName) || '';
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;
      if (e.key === 'Delete' && selectedTextId) {
        e.preventDefault();
        const next = (state.textLayers || []).filter((l) => l.id !== selectedTextId);
        dispatch({ type: 'SET', next: { ...state, textLayers: next } });
        setSelectedTextId(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedTextId, state]);

  // ----- Right panel content per tool -----
  const rightPanel = renderRightPanel({
    tool, state, previewState, setState, commit,
    cropMode, setCropMode, cropRect, setCropRect,
    customPresets, setCustomPresets,
    exportFormat, setExportFormat, exportQuality, setExportQuality,
    doExport, doSave, saving,
    imgUrl, history: h,
    goToPast: (i) => dispatch({ type: 'RESTORE', state: h.past[i] }),
    // Sprint 3 wiring
    mediaId,
    nav,
    maskTool, setMaskTool, brushSize, setBrushSize,
    hardness, setHardness, maskOpacity, setMaskOpacity,
    showMask, setShowMask, maskCanvasRef,
    featherPx, setFeatherPx, hasMask,
    selectedTextId, setSelectedTextId,
    setTextLayers,
    activeAiJob, setActiveAiJob,
  });

  return (
    <div className="h-full w-full flex bg-ink-950 text-white">
      {/* Left tool nav */}
      <div className="w-16 shrink-0 border-r border-white/[0.06] flex flex-col items-center py-4 gap-1">
        <button
          onClick={() => nav('/studio/gallery')}
          className="w-10 h-10 rounded flex items-center justify-center text-white/60 hover:text-gold hover:bg-white/5 mb-3 transition-colors"
          title="Back to Gallery"
          data-testid="back-btn"
        >
          <ArrowLeft strokeWidth={1.25} className="w-5 h-5" />
        </button>
        {TOOLS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTool(key)}
            title={label}
            data-testid={`tool-${key}`}
            className={`w-11 h-11 rounded flex items-center justify-center transition-colors ${
              tool === key ? 'bg-white/[0.06] text-gold' : 'text-white/50 hover:text-white hover:bg-white/[0.03]'
            }`}
          >
            <Icon strokeWidth={1.25} className="w-5 h-5" />
          </button>
        ))}
      </div>

      {/* Center canvas + top bar */}
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar
          zoom={zoom}
          onZoomIn={shortcuts.zoomIn}
          onZoomOut={shortcuts.zoomOut}
          onFit={shortcuts.fit}
          onActual={shortcuts.actual}
          undo={undo}
          redo={redo}
          canUndo={h.past.length > 0}
          canRedo={h.future.length > 0}
          onHoldStart={() => setCompareHold(true)}
          onHoldEnd={() => setCompareHold(false)}
          splitOn={compareRatio != null}
          toggleSplit={() => setCompareRatio(compareRatio == null ? 0.5 : null)}
          resetAll={resetAll}
          onSave={doSave}
          saving={saving}
        />
        <div className="relative flex-1 min-h-0" data-testid="canvas-region" ref={stageRef}>
          {imgUrl ? (
            <>
              <EditorCanvas
                imgUrl={imgUrl}
                state={state}
                zoom={zoom} setZoom={setZoom}
                pan={pan} setPan={setPan}
                cropMode={cropMode}
                cropRect={cropRect} setCropRect={setCropRect}
                compareRatio={compareRatio}
                compareHold={compareHold}
                onImageLoad={(el) => {
                  setImgEl(el);
                  const rect = el.getBoundingClientRect();
                  setImgRect(rect);
                }}
              />
              {/* Mask + text overlays anchored to the same image element */}
              <MaskOverlayHost
                imgEl={imgEl}
                zoom={zoom}
                pan={pan}
                showMask={showMask && tool === 'mask'}
              >
                {imgEl && (
                  <MaskCanvas
                    ref={maskCanvasRef}
                    natW={imgEl.naturalWidth}
                    natH={imgEl.naturalHeight}
                    active={tool === 'mask'}
                    tool={maskTool}
                    brushSize={brushSize}
                    hardness={hardness}
                    opacity={maskOpacity}
                    featherPx={featherPx}
                    onChange={onMaskChange}
                    initial={state.mask}
                  />
                )}
                {imgEl && (state.textLayers || []).map((L) => (
                  <TextLayerHUD
                    key={L.id}
                    layer={L}
                    selected={selectedTextId === L.id}
                    onSelect={setSelectedTextId}
                    onChange={(next) => {
                      const arr = state.textLayers.map((x) => (x.id === next.id ? next : x));
                      dispatch({ type: 'REPLACE', next: { ...state, textLayers: arr } });
                    }}
                    onCommit={commit}
                    natW={imgEl.naturalWidth}
                    natH={imgEl.naturalHeight}
                    imgRect={imgEl.getBoundingClientRect()}
                  />
                ))}
              </MaskOverlayHost>
            </>
          ) : (
            <div className="h-full flex items-center justify-center text-white/40 text-sm">Loading image…</div>
          )}
          {compareRatio != null && (
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={compareRatio}
              onChange={(e) => setCompareRatio(Number(e.target.value))}
              className="absolute left-8 right-8 bottom-6 accent-gold"
              data-testid="split-slider"
            />
          )}
        </div>
      </div>

      {/* Right controls */}
      <aside className="w-96 shrink-0 border-l border-white/[0.06] h-full overflow-y-auto bg-ink-950 p-5">
        {rightPanel}
      </aside>
    </div>
  );
}

// ============ Top bar ============
function TopBar({
  zoom, onZoomIn, onZoomOut, onFit, onActual,
  undo, redo, canUndo, canRedo,
  onHoldStart, onHoldEnd, splitOn, toggleSplit,
  resetAll, onSave, saving,
}) {
  return (
    <div className="h-12 shrink-0 border-b border-white/[0.06] flex items-center justify-between px-4 gap-3 text-sm">
      <div className="flex items-center gap-1">
        <IconBtn onClick={undo} disabled={!canUndo} title="Undo (Ctrl+Z)" testid="undo-btn"><Undo2 strokeWidth={1.25} /></IconBtn>
        <IconBtn onClick={redo} disabled={!canRedo} title="Redo (Ctrl+Shift+Z)" testid="redo-btn"><Redo2 strokeWidth={1.25} /></IconBtn>
        <div className="w-px h-5 bg-white/10 mx-2" />
        <IconBtn onClick={onZoomOut} title="Zoom out (-)" testid="zoom-out"><ZoomOut strokeWidth={1.25} /></IconBtn>
        <span className="text-xs text-white/60 w-14 text-center">{Math.round(zoom * 100)}%</span>
        <IconBtn onClick={onZoomIn} title="Zoom in (+)" testid="zoom-in"><ZoomIn strokeWidth={1.25} /></IconBtn>
        <IconBtn onClick={onFit} title="Fit to viewport (0)" testid="zoom-fit"><Maximize2 strokeWidth={1.25} /></IconBtn>
        <IconBtn onClick={onActual} title="Actual pixels (1)" testid="zoom-actual"><Square strokeWidth={1.25} /></IconBtn>
      </div>
      <div className="flex items-center gap-1">
        <button
          onMouseDown={onHoldStart}
          onMouseUp={onHoldEnd}
          onMouseLeave={onHoldEnd}
          data-testid="hold-compare"
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors"
          title="Hold to see original"
        >
          <Eye strokeWidth={1.25} className="w-4 h-4" /> Hold Original
        </button>
        <button
          onClick={toggleSplit}
          data-testid="toggle-split"
          className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded transition-colors ${
            splitOn ? 'bg-gold text-black' : 'bg-white/5 hover:bg-white/10 text-white/80'
          }`}
        >
          <SplitSquareHorizontal strokeWidth={1.25} className="w-4 h-4" /> Split
        </button>
        <div className="w-px h-5 bg-white/10 mx-2" />
        <button onClick={resetAll} className="text-xs px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-white/80 transition-colors" data-testid="reset-all-btn">
          Reset All
        </button>
        <button
          onClick={onSave}
          disabled={saving}
          data-testid="save-version-btn"
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-gold text-black font-medium hover:bg-gold-soft disabled:opacity-50 transition-colors"
        >
          <Save strokeWidth={1.5} className="w-4 h-4" /> {saving ? 'Saving…' : 'Save Version'}
        </button>
      </div>
    </div>
  );
}

function IconBtn({ children, onClick, disabled, title, testid }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      data-testid={testid}
      className="w-8 h-8 rounded flex items-center justify-center text-white/70 hover:text-gold hover:bg-white/5 disabled:opacity-30 disabled:hover:text-white/70 disabled:hover:bg-transparent transition-colors [&>svg]:w-4 [&>svg]:h-4"
    >
      {children}
    </button>
  );
}

/**
 * Positions its children over the source <img> using the same transform stack
 * (translate + scale) so the mask canvas + text overlays follow zoom / pan.
 */
function MaskOverlayHost({ imgEl, zoom, pan, showMask, children }) {
  if (!imgEl) return null;
  const w = imgEl.naturalWidth;
  const h = imgEl.naturalHeight;
  return (
    <div
      style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: '50%', top: '50%',
          transform: `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transformOrigin: 'center center',
          width: w, height: h,
        }}
      >
        <div style={{ position: 'relative', width: '100%', height: '100%', pointerEvents: 'none' }}>
          {/* Only mask canvas needs pointer events; text HUDs handle their own */}
          <div style={{ position: 'absolute', inset: 0, pointerEvents: showMask ? 'auto' : 'none', display: showMask ? 'block' : 'none' }}>
            {children[0]}
          </div>
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'auto' }}>
            {children[1]}
          </div>
        </div>
      </div>
    </div>
  );
}

// ============ Right panel content ============
function renderRightPanel(ctx) {
  const { tool } = ctx;
  return (
    <div>
      {tool === 'transform' && <TransformPanel {...ctx} />}
      {tool === 'adjust' && <AdjustPanel {...ctx} />}
      {tool === 'filter' && <FilterPanel {...ctx} />}
      {tool === 'mask' && (
        <MaskPanel
          maskTool={ctx.maskTool} setMaskTool={ctx.setMaskTool}
          brushSize={ctx.brushSize} setBrushSize={ctx.setBrushSize}
          hardness={ctx.hardness} setHardness={ctx.setHardness}
          opacity={ctx.maskOpacity} setOpacity={ctx.setMaskOpacity}
          showMask={ctx.showMask} setShowMask={ctx.setShowMask}
          maskCanvasRef={ctx.maskCanvasRef}
          featherPx={ctx.featherPx} setFeatherPx={ctx.setFeatherPx}
        />
      )}
      {tool === 'text' && (
        <TextPanel
          layers={ctx.state.textLayers || []}
          setLayers={ctx.setTextLayers}
          commit={ctx.commit}
          selectedId={ctx.selectedTextId}
          setSelectedId={ctx.setSelectedTextId}
        />
      )}
      {tool === 'ai' && (
        <AiToolsPanel
          mediaId={ctx.mediaId}
          maskCanvasRef={ctx.maskCanvasRef}
          hasMask={ctx.hasMask}
          activeAiJob={ctx.activeAiJob}
          setActiveAiJob={ctx.setActiveAiJob}
          onOpenNewSource={(id) => ctx.nav(`/studio/editor/${id}`)}
        />
      )}
      {tool === 'history' && <HistoryPanel {...ctx} />}
      <ExportSection {...ctx} />
    </div>
  );
}

function SectionTitle({ children }) {
  return <div className="text-[11px] uppercase tracking-[0.3em] text-white/40 mb-4">{children}</div>;
}

function TransformPanel({ state, setState, cropMode, setCropMode, cropRect, setCropRect, previewState, commit }) {
  const applyRot = (deg) => setState(({ ...state, transform: { ...state.transform, rotation: (state.transform.rotation + deg) % 360 } }));
  return (
    <div className="mb-8">
      <SectionTitle>Transform</SectionTitle>
      <div className="grid grid-cols-2 gap-2 mb-5">
        <BtnRow onClick={() => applyRot(-90)} testid="rot-left"><RotateCcw strokeWidth={1.25} className="w-4 h-4" /> Rotate 90° left</BtnRow>
        <BtnRow onClick={() => applyRot(90)} testid="rot-right"><RotateCw strokeWidth={1.25} className="w-4 h-4" /> Rotate 90° right</BtnRow>
        <BtnRow onClick={() => setState(updateTransform(state, { flipH: !state.transform.flipH }))} testid="flip-h"><FlipHorizontal strokeWidth={1.25} className="w-4 h-4" /> Flip horizontal</BtnRow>
        <BtnRow onClick={() => setState(updateTransform(state, { flipV: !state.transform.flipV }))} testid="flip-v"><FlipVertical strokeWidth={1.25} className="w-4 h-4" /> Flip vertical</BtnRow>
      </div>
      <Slider
        label="Straighten (fine rotation)"
        value={state.transform.rotation}
        min={-45} max={45} step={0.1} defaultValue={0}
        onChange={(v) => previewState(updateTransform(state, { rotation: v }))}
        onCommit={commit}
        testid="straighten"
      />

      <SectionTitle>Crop</SectionTitle>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {CROP_RATIOS.map((r) => (
          <button
            key={r}
            onClick={() => { setCropMode(r); if (r === 'off') setCropRect(null); }}
            data-testid={`crop-${r.replace(':', 'x')}`}
            className={`text-[11px] px-2.5 py-1.5 rounded border transition-colors ${
              cropMode === r ? 'bg-gold/15 border-gold/60 text-gold' : 'bg-white/[0.02] border-white/10 text-white/60 hover:text-white'
            }`}
          >
            {r === 'off' ? 'Off' : r === 'free' ? 'Free' : r}
          </button>
        ))}
      </div>
      {cropMode !== 'off' && (
        <p className="text-[11px] text-white/40 mb-3">Drag on the image to draw crop region.</p>
      )}
      {cropRect && cropRect.w > 0 && (
        <div className="flex gap-2 mb-2">
          <button
            onClick={() => setState(updateTransform(state, { crop: cropRect }))}
            data-testid="apply-crop"
            className="text-xs px-3 py-1.5 rounded bg-gold text-black font-medium hover:bg-gold-soft transition-colors"
          >
            Apply Crop
          </button>
          <button
            onClick={() => setCropRect(null)}
            className="text-xs px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-white/70 transition-colors"
          >
            Clear
          </button>
        </div>
      )}
      {state.transform.crop && (
        <button
          onClick={() => setState(updateTransform(state, { crop: null }))}
          className="text-[11px] text-white/50 hover:text-gold underline"
        >
          Remove active crop
        </button>
      )}
    </div>
  );
}

function AdjustPanel({ state, previewState, setState, commit }) {
  const groups = [
    { title: 'Light', keys: ['exposure', 'brightness', 'contrast', 'highlights', 'shadows', 'whites', 'blacks'] },
    { title: 'Color', keys: ['temperature', 'tint', 'saturation', 'vibrance'] },
    { title: 'Detail', keys: ['sharpness', 'clarity', 'dehaze', 'blur'] },
    { title: 'Effects', keys: ['vignette', 'opacity'] },
  ];
  const change = (k, v) => previewState(updateAdjust(state, k, v));
  return (
    <div className="mb-8">
      {groups.map(({ title, keys }) => (
        <div key={title} className="mb-6">
          <SectionTitle>{title}</SectionTitle>
          {keys.map((k) => (
            <Slider
              key={k}
              label={ADJUST_LABELS[k]}
              value={state.adjust[k]}
              min={ADJUST_RANGES[k][0]} max={ADJUST_RANGES[k][1]}
              step={k === 'blur' ? 0.5 : 1}
              defaultValue={DEFAULT_ADJUST[k]}
              onChange={(v) => change(k, v)}
              onCommit={commit}
              testid={k}
            />
          ))}
        </div>
      ))}
      <button
        onClick={() => setState({ ...state, adjust: { ...DEFAULT_ADJUST } })}
        className="text-xs px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-white/70 transition-colors"
        data-testid="reset-adjust"
      >
        Reset all adjustments
      </button>
    </div>
  );
}

function FilterPanel({ state, setState, previewState, commit, imgUrl, customPresets, setCustomPresets }) {
  const applyFilter = (name) => setState(updateFilter(state, { preset: name, intensity: state.filter.intensity }));
  const saveCurrent = () => {
    const name = window.prompt('Preset name');
    if (!name) return;
    const list = saveCustomPreset(name, state);
    setCustomPresets(list);
    toast.success('Preset saved');
  };
  const applyCustom = (p) => setState(p.snapshot);
  const removeCustom = (name) => setCustomPresets(deleteCustomPreset(name));

  return (
    <div className="mb-8">
      <SectionTitle>Filters</SectionTitle>
      <div className="grid grid-cols-3 gap-2 mb-4">
        {FILTER_KEYS.map((name) => {
          const isActive = state.filter.preset === name;
          const previewFilter = cssForFilter(name, 100);
          return (
            <button
              key={name}
              onClick={() => applyFilter(name)}
              data-testid={`filter-${name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`}
              className={`group text-[11px] rounded overflow-hidden border transition-colors ${
                isActive ? 'border-gold' : 'border-white/10 hover:border-white/25'
              }`}
            >
              <div className="aspect-square bg-white/5 relative overflow-hidden">
                {imgUrl && (
                  <img
                    src={imgUrl}
                    alt={name}
                    style={{ filter: previewFilter, width: '100%', height: '100%', objectFit: 'cover' }}
                    draggable={false}
                  />
                )}
              </div>
              <div className={`px-1.5 py-1 text-center ${isActive ? 'bg-gold text-black' : 'bg-black/40 text-white/70'}`}>{name}</div>
            </button>
          );
        })}
      </div>
      <Slider
        label="Intensity"
        value={state.filter.intensity}
        min={0} max={100} step={1} defaultValue={100}
        onChange={(v) => previewState(updateFilter(state, { intensity: v }))}
        onCommit={commit}
        testid="filter-intensity"
      />
      <div className="pt-3 border-t border-white/[0.06] mt-4">
        <div className="flex items-center justify-between mb-2">
          <SectionTitle>Custom presets</SectionTitle>
          <button onClick={saveCurrent} className="text-[11px] text-gold hover:text-gold-soft" data-testid="save-preset">
            Save current
          </button>
        </div>
        {customPresets.length === 0 && <p className="text-[11px] text-white/40">No custom presets yet.</p>}
        <div className="space-y-1">
          {customPresets.map((p) => (
            <div key={p.name} className="flex items-center justify-between bg-white/[0.02] rounded px-3 py-1.5 text-sm">
              <button onClick={() => applyCustom(p)} className="text-white/80 hover:text-gold flex-1 text-left">{p.name}</button>
              <button onClick={() => removeCustom(p.name)} className="text-white/40 hover:text-red-400 text-[11px]">delete</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function HistoryPanel({ history, goToPast }) {
  const entries = [...history.past.map((s, i) => ({ s, i, label: describeState(s) })), { s: history.present, i: history.past.length, label: 'Current' }];
  return (
    <div className="mb-8">
      <SectionTitle>History</SectionTitle>
      <div className="space-y-1 max-h-[50vh] overflow-y-auto">
        {entries.map((e, idx) => (
          <button
            key={idx}
            onClick={() => idx < history.past.length && goToPast(idx)}
            data-testid={`history-${idx}`}
            className={`w-full text-left px-3 py-2 rounded text-xs transition-colors ${
              idx === history.past.length
                ? 'bg-gold/15 text-gold'
                : 'bg-white/[0.02] hover:bg-white/[0.05] text-white/70'
            }`}
          >
            <span className="text-white/40 mr-2">{idx + 1}.</span>{e.label}
          </button>
        ))}
      </div>
      <p className="text-[11px] text-white/40 mt-4">Ctrl+Z undo · Ctrl+Shift+Z redo</p>
    </div>
  );
}

function describeState(s) {
  const parts = [];
  if (s.filter?.preset && s.filter.preset !== 'None') parts.push(`Filter: ${s.filter.preset}`);
  if (s.transform?.rotation) parts.push(`Rotate ${s.transform.rotation}°`);
  if (s.transform?.flipH) parts.push('Flip H');
  if (s.transform?.flipV) parts.push('Flip V');
  if (s.transform?.crop) parts.push('Crop');
  const adj = Object.entries(s.adjust || {}).filter(([_, v]) => v !== DEFAULT_ADJUST[_] && DEFAULT_ADJUST[_] !== undefined);
  if (adj.length) parts.push(`${adj.length} adj`);
  return parts.join(' · ') || 'Initial';
}

function BtnRow({ children, onClick, testid }) {
  return (
    <button
      onClick={onClick}
      data-testid={testid}
      className="flex items-center gap-2 justify-start text-xs px-3 py-2 rounded bg-white/[0.02] border border-white/10 text-white/80 hover:bg-white/[0.05] hover:border-white/20 transition-colors"
    >
      {children}
    </button>
  );
}

function ExportSection({ exportFormat, setExportFormat, exportQuality, setExportQuality, doExport }) {
  return (
    <div className="pt-6 border-t border-white/[0.06]">
      <SectionTitle>Export</SectionTitle>
      <div className="grid grid-cols-3 gap-1.5 mb-3">
        {['image/png', 'image/jpeg', 'image/webp'].map((f) => (
          <button
            key={f}
            onClick={() => setExportFormat(f)}
            data-testid={`fmt-${f.split('/')[1]}`}
            className={`text-[11px] py-1.5 rounded border transition-colors ${
              exportFormat === f ? 'bg-gold/15 border-gold/60 text-gold' : 'bg-white/[0.02] border-white/10 text-white/60 hover:text-white'
            }`}
          >
            {f.split('/')[1].toUpperCase()}
          </button>
        ))}
      </div>
      {exportFormat !== 'image/png' && (
        <Slider
          label={`Quality (${Math.round(exportQuality * 100)}%)`}
          value={Math.round(exportQuality * 100)}
          min={30} max={100} step={1} defaultValue={95}
          onChange={(v) => setExportQuality(v / 100)}
          onCommit={() => {}}
          testid="export-quality"
        />
      )}
      <button
        onClick={doExport}
        data-testid="export-btn"
        className="w-full mt-2 flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 text-white py-2.5 rounded text-sm transition-colors"
      >
        <Download strokeWidth={1.5} className="w-4 h-4" /> Download
      </button>
    </div>
  );
}
