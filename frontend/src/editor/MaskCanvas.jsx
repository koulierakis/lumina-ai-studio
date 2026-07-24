// Mask canvas — freehand brush + rectangular selection with undo/redo,
// serializable to a base64 PNG for backend upload and session storage.
import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from 'react';

/**
 * Interactive mask overlay drawn on top of the source image (in image pixel
 * coordinates). The canvas alpha channel is the mask: opaque white = edit area,
 * transparent = keep untouched.
 */
const MaskCanvas = forwardRef(function MaskCanvas(
  { natW, natH, active, tool, brushSize, hardness, opacity, feather, onChange, initial },
  ref,
) {
  const canvasRef = useRef(null);
  const [drawing, setDrawing] = useState(null); // { last:{x,y} } | { start:{x,y}, mode:'rect' }
  const [history, setHistory] = useState({ past: [], present: null, future: [] });

  // Push snapshot
  const snapshot = () => {
    const c = canvasRef.current;
    if (!c) return null;
    return c.toDataURL('image/png');
  };
  const commit = () => {
    const snap = snapshot();
    if (!snap) return;
    setHistory((h) => ({ past: [...h.past, h.present || snap].slice(-40), present: snap, future: [] }));
    onChange && onChange(snap);
  };
  const restore = (dataUrl) => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, c.width, c.height);
    if (!dataUrl) return;
    const img = new Image();
    img.onload = () => ctx.drawImage(img, 0, 0);
    img.src = dataUrl;
  };

  useImperativeHandle(ref, () => ({
    getMask: () => snapshot(),
    setMask: (dataUrl) => { restore(dataUrl); setHistory({ past: [], present: dataUrl, future: [] }); onChange && onChange(dataUrl); },
    clear: () => {
      const c = canvasRef.current;
      const ctx = c.getContext('2d');
      ctx.clearRect(0, 0, c.width, c.height);
      commit();
    },
    invert: () => {
      const c = canvasRef.current;
      const ctx = c.getContext('2d');
      const img = ctx.getImageData(0, 0, c.width, c.height);
      const d = img.data;
      for (let i = 0; i < d.length; i += 4) {
        d[i + 3] = 255 - d[i + 3];
        d[i] = 255; d[i + 1] = 255; d[i + 2] = 255;
      }
      ctx.putImageData(img, 0, 0);
      commit();
    },
    feather: (px) => {
      const c = canvasRef.current;
      const ctx = c.getContext('2d');
      ctx.filter = `blur(${px}px)`;
      const tmp = document.createElement('canvas');
      tmp.width = c.width; tmp.height = c.height;
      tmp.getContext('2d').drawImage(c, 0, 0);
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.drawImage(tmp, 0, 0);
      ctx.filter = 'none';
      commit();
    },
    undo: () => {
      setHistory((h) => {
        if (!h.past.length) return h;
        const prev = h.past[h.past.length - 1];
        restore(prev);
        onChange && onChange(prev);
        return { past: h.past.slice(0, -1), present: prev, future: [h.present, ...h.future] };
      });
    },
    redo: () => {
      setHistory((h) => {
        if (!h.future.length) return h;
        const nxt = h.future[0];
        restore(nxt);
        onChange && onChange(nxt);
        return { past: [...h.past, h.present], present: nxt, future: h.future.slice(1) };
      });
    },
    hasMask: () => !!history.present,
  }));

  // Init canvas + restore initial
  useEffect(() => {
    const c = canvasRef.current;
    if (!c || !natW || !natH) return;
    c.width = natW;
    c.height = natH;
    if (initial) restore(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [natW, natH]);

  // ----- brush painting -----
  const evtToImg = (e) => {
    const c = canvasRef.current;
    const rect = c.getBoundingClientRect();
    const scaleX = c.width / rect.width;
    const scaleY = c.height / rect.height;
    return { x: (e.clientX - rect.left) * scaleX, y: (e.clientY - rect.top) * scaleY };
  };

  const paintDot = (ctx, x, y, size, hard, alpha, erase) => {
    ctx.save();
    ctx.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
    // radial gradient for hardness
    const soft = 1 - hard / 100;
    const inner = size * (1 - soft) * 0.5;
    const grad = ctx.createRadialGradient(x, y, inner, x, y, size / 2);
    grad.addColorStop(0, `rgba(255,255,255,${alpha})`);
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(x, y, size / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  };

  const onDown = (e) => {
    if (!active) return;
    const c = canvasRef.current;
    const ctx = c.getContext('2d');
    const p = evtToImg(e);
    if (tool === 'rect') {
      setDrawing({ mode: 'rect', start: p, snapBefore: snapshot() });
    } else {
      setDrawing({ mode: 'brush', last: p });
      paintDot(ctx, p.x, p.y, brushSize, hardness, opacity / 100, tool === 'erase');
    }
    e.preventDefault();
  };
  const onMove = (e) => {
    if (!drawing || !active) return;
    const c = canvasRef.current;
    const ctx = c.getContext('2d');
    const p = evtToImg(e);
    if (drawing.mode === 'brush') {
      // interpolate between last and p to avoid gaps at fast movement
      const last = drawing.last || p;
      const dx = p.x - last.x, dy = p.y - last.y;
      const dist = Math.hypot(dx, dy);
      const steps = Math.max(1, Math.floor(dist / (brushSize / 4)));
      for (let i = 1; i <= steps; i++) {
        const t = i / steps;
        paintDot(ctx, last.x + dx * t, last.y + dy * t, brushSize, hardness, opacity / 100, tool === 'erase');
      }
      setDrawing({ ...drawing, last: p });
    } else if (drawing.mode === 'rect') {
      // Preview: restore snapshot then draw rect
      restore(drawing.snapBefore);
      const x = Math.min(drawing.start.x, p.x);
      const y = Math.min(drawing.start.y, p.y);
      const w = Math.abs(p.x - drawing.start.x);
      const h = Math.abs(p.y - drawing.start.y);
      setTimeout(() => {
        const ctx2 = canvasRef.current.getContext('2d');
        ctx2.save();
        ctx2.fillStyle = `rgba(255,255,255,${opacity / 100})`;
        ctx2.fillRect(x, y, w, h);
        ctx2.restore();
      }, 0);
    }
  };
  const onUp = () => {
    if (drawing) commit();
    setDrawing(null);
  };

  return (
    <canvas
      ref={canvasRef}
      onMouseDown={onDown}
      onMouseMove={onMove}
      onMouseUp={onUp}
      onMouseLeave={onUp}
      style={{
        position: 'absolute', inset: 0, width: '100%', height: '100%',
        pointerEvents: active ? 'auto' : 'none',
        opacity: 0.55,
        mixBlendMode: 'screen',
        cursor: active ? 'crosshair' : 'default',
      }}
      data-testid="mask-canvas"
    />
  );
});

export default MaskCanvas;
