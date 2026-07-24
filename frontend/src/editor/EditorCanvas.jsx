import { useEffect, useRef, useState, useCallback } from 'react';
import { livePreviewStyle, overlayStyles } from './pipeline';

/**
 * Editor canvas viewport with zoom / pan / crop overlay.
 * Props:
 *   imgUrl         - blob URL of the source image
 *   state          - editor state
 *   zoom, setZoom  - number, setter
 *   compareRatio   - 0..1 for split compare; null = off
 *   compareHold    - boolean; when true show original (no filters)
 *   cropMode       - 'off' | 'free' | ratio like '16:9', '1:1' etc
 *   cropRect       - current crop rectangle in image px, or null
 *   setCropRect
 *   onImageLoad    - receives HTMLImageElement (for export)
 */
export default function EditorCanvas({
  imgUrl, state, zoom, setZoom, compareRatio, compareHold,
  cropMode, cropRect, setCropRect, onImageLoad, pan, setPan,
}) {
  const wrapRef = useRef(null);
  const imgRef = useRef(null);
  const [nat, setNat] = useState({ w: 0, h: 0 });
  const [dragging, setDragging] = useState(null); // { startX, startY, base } for pan / crop

  const handleLoaded = useCallback(() => {
    const el = imgRef.current;
    if (!el) return;
    setNat({ w: el.naturalWidth, h: el.naturalHeight });
    onImageLoad && onImageLoad(el);
  }, [onImageLoad]);

  useEffect(() => {
    // Fit to viewport initially — set zoom so image fits container
    const el = wrapRef.current;
    const img = imgRef.current;
    if (!el || !img || !img.naturalWidth) return;
    const cw = el.clientWidth - 32;
    const ch = el.clientHeight - 32;
    const s = Math.min(cw / img.naturalWidth, ch / img.naturalHeight, 1);
    setZoom(s || 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nat.w, nat.h]);

  // Pan handling (drag on canvas when Space held OR cropMode==='off' and middle mouse)
  const onMouseDown = (e) => {
    if (cropMode !== 'off') return;
    setDragging({ startX: e.clientX, startY: e.clientY, base: pan, mode: 'pan' });
  };
  const onMouseMove = (e) => {
    if (!dragging) return;
    if (dragging.mode === 'pan') {
      setPan({
        x: dragging.base.x + (e.clientX - dragging.startX),
        y: dragging.base.y + (e.clientY - dragging.startY),
      });
    } else if (dragging.mode === 'crop') {
      const rect = imgRef.current.getBoundingClientRect();
      const scale = rect.width / (nat.w || 1); // display px per image px
      const dx = (e.clientX - rect.left) / scale;
      const dy = (e.clientY - rect.top) / scale;
      let x0 = dragging.startImgX, y0 = dragging.startImgY;
      let x1 = Math.max(0, Math.min(nat.w, dx));
      let y1 = Math.max(0, Math.min(nat.h, dy));
      let w = x1 - x0, h = y1 - y0;
      if (cropMode && cropMode !== 'free' && cropMode !== 'off') {
        const [rw, rh] = cropMode.split(':').map(Number);
        const targetRatio = rw / rh;
        if (Math.abs(w / (h || 1)) > targetRatio) h = Math.sign(h || 1) * Math.abs(w) / targetRatio;
        else w = Math.sign(w || 1) * Math.abs(h) * targetRatio;
      }
      setCropRect({
        x: Math.min(x0, x0 + w),
        y: Math.min(y0, y0 + h),
        w: Math.abs(w),
        h: Math.abs(h),
      });
    }
  };
  const onMouseUp = () => setDragging(null);

  const onCropDown = (e) => {
    if (cropMode === 'off') return;
    const rect = imgRef.current.getBoundingClientRect();
    const scale = rect.width / (nat.w || 1);
    const startImgX = (e.clientX - rect.left) / scale;
    const startImgY = (e.clientY - rect.top) / scale;
    setDragging({ mode: 'crop', startImgX, startImgY });
    setCropRect({ x: startImgX, y: startImgY, w: 0, h: 0 });
    e.stopPropagation();
  };

  const previewStyle = livePreviewStyle(state);
  const overlays = overlayStyles(state);

  const cropOverlay = cropRect && cropRect.w > 0 && cropRect.h > 0 && (
    <div
      style={{
        position: 'absolute',
        left: `${(cropRect.x / nat.w) * 100}%`,
        top: `${(cropRect.y / nat.h) * 100}%`,
        width: `${(cropRect.w / nat.w) * 100}%`,
        height: `${(cropRect.h / nat.h) * 100}%`,
        border: '1.5px solid #D4AF37',
        boxShadow: '0 0 0 9999px rgba(0,0,0,0.55)',
        pointerEvents: 'none',
      }}
      data-testid="crop-overlay"
    />
  );

  const splitLine = compareRatio != null && (
    <div style={{
      position: 'absolute', top: 0, bottom: 0,
      left: `${compareRatio * 100}%`,
      width: '2px', background: '#D4AF37', pointerEvents: 'none', zIndex: 2,
    }} />
  );

  return (
    <div
      ref={wrapRef}
      className="relative w-full h-full overflow-hidden bg-ink-950 select-none"
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      data-testid="editor-canvas"
    >
      <div
        style={{
          position: 'absolute',
          left: '50%', top: '50%',
          transform: `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transformOrigin: 'center center',
          width: nat.w || 'auto',
          height: nat.h || 'auto',
        }}
      >
        <div style={{ position: 'relative', width: nat.w || 'auto', height: nat.h || 'auto' }}>
          {/* Original (for compare-hold) */}
          <img
            src={imgUrl}
            alt=""
            style={{
              display: 'block', width: '100%', height: '100%',
              visibility: compareHold ? 'visible' : 'hidden',
              position: 'absolute', inset: 0,
            }}
            draggable={false}
          />
          {/* Live edited preview */}
          <img
            ref={imgRef}
            src={imgUrl}
            alt=""
            crossOrigin="anonymous"
            onLoad={handleLoaded}
            style={{
              display: 'block', width: '100%', height: '100%',
              position: 'relative',
              visibility: compareHold ? 'hidden' : 'visible',
              clipPath: compareRatio != null ? `inset(0 0 0 ${compareRatio * 100}%)` : undefined,
              ...previewStyle,
            }}
            draggable={false}
            onMouseDown={onCropDown}
          />
          {overlays.map(({ key, style }) => (
            <div key={key} style={{ ...style, clipPath: compareRatio != null ? `inset(0 0 0 ${compareRatio * 100}%)` : undefined }} />
          ))}
          {compareRatio != null && (
            <img
              src={imgUrl}
              alt=""
              style={{
                position: 'absolute', inset: 0, width: '100%', height: '100%',
                clipPath: `inset(0 ${(1 - compareRatio) * 100}% 0 0)`,
              }}
              draggable={false}
            />
          )}
          {cropOverlay}
          {splitLine}
        </div>
      </div>
    </div>
  );
}
