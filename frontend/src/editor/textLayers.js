// Text layer helpers.

let nextId = 1;
export function newTextLayer(overrides = {}) {
  return {
    id: `text-${Date.now()}-${nextId++}`,
    text: 'Text',
    x: 50, y: 50,           // percent of image
    w: 30, h: 8,             // percent of image
    rotation: 0,
    fontFamily: 'Outfit, sans-serif',
    fontSize: 48,            // in image pixels at native resolution
    bold: false, italic: false, underline: false,
    align: 'center',
    color: '#FFFFFF',
    opacity: 100,
    letterSpacing: 0,
    lineHeight: 1.2,
    shadow: { on: false, x: 2, y: 2, blur: 6, color: '#000000' },
    outline: { on: false, width: 2, color: '#000000' },
    bg: { on: false, color: '#000000', opacity: 40, radius: 6, padX: 12, padY: 6 },
    hidden: false, locked: false,
    ...overrides,
  };
}

export const FONT_FAMILIES = [
  'Outfit, sans-serif',
  'Cormorant Garamond, serif',
  'Georgia, serif',
  'Times New Roman, serif',
  'Arial, sans-serif',
  'Helvetica, sans-serif',
  'Courier New, monospace',
  'Impact, sans-serif',
  'Verdana, sans-serif',
];

export function textLayerStyle(layer, imgW, imgH, previewScale = 1) {
  const shadow = layer.shadow?.on
    ? `${layer.shadow.x}px ${layer.shadow.y}px ${layer.shadow.blur}px ${layer.shadow.color}`
    : 'none';
  const stroke = layer.outline?.on
    ? `${layer.outline.width}px ${layer.outline.color}`
    : undefined;
  const bg = layer.bg?.on
    ? {
        background: hexToRgba(layer.bg.color, (layer.bg.opacity ?? 40) / 100),
        borderRadius: `${layer.bg.radius}px`,
        padding: `${layer.bg.padY}px ${layer.bg.padX}px`,
      }
    : {};
  return {
    fontFamily: layer.fontFamily,
    fontSize: `${layer.fontSize * previewScale}px`,
    fontWeight: layer.bold ? 700 : 400,
    fontStyle: layer.italic ? 'italic' : 'normal',
    textDecoration: layer.underline ? 'underline' : 'none',
    textAlign: layer.align,
    color: layer.color,
    opacity: layer.opacity / 100,
    letterSpacing: `${layer.letterSpacing}px`,
    lineHeight: layer.lineHeight,
    textShadow: shadow,
    WebkitTextStroke: stroke,
    ...bg,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    userSelect: 'none',
  };
}

function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Render every text layer onto the given 2D canvas context at full resolution. */
export function drawTextLayersToCanvas(ctx, layers, imgW, imgH) {
  layers.forEach((L) => {
    if (L.hidden) return;
    ctx.save();
    const cx = (L.x / 100) * imgW + (L.w / 100 * imgW) / 2;
    const cy = (L.y / 100) * imgH + (L.h / 100 * imgH) / 2;
    ctx.translate(cx, cy);
    ctx.rotate((L.rotation * Math.PI) / 180);
    ctx.globalAlpha = L.opacity / 100;

    // background box
    if (L.bg?.on) {
      const bw = (L.w / 100) * imgW;
      const bh = (L.h / 100) * imgH;
      ctx.fillStyle = hexToRgba(L.bg.color, (L.bg.opacity ?? 40) / 100);
      roundRect(ctx, -bw / 2, -bh / 2, bw, bh, L.bg.radius);
      ctx.fill();
    }

    ctx.font = `${L.italic ? 'italic ' : ''}${L.bold ? '700' : '400'} ${L.fontSize}px ${L.fontFamily}`;
    ctx.fillStyle = L.color;
    ctx.textAlign = L.align === 'left' ? 'left' : L.align === 'right' ? 'right' : 'center';
    ctx.textBaseline = 'middle';

    const lines = (L.text || '').split('\n');
    const lineH = L.fontSize * L.lineHeight;
    const totalH = lineH * lines.length;
    let startY = -totalH / 2 + lineH / 2;
    const xAt = L.align === 'left' ? -(L.w / 100 * imgW) / 2 : L.align === 'right' ? (L.w / 100 * imgW) / 2 : 0;
    lines.forEach((line, i) => {
      const y = startY + i * lineH;
      if (L.outline?.on) {
        ctx.lineWidth = L.outline.width;
        ctx.strokeStyle = L.outline.color;
        ctx.strokeText(line, xAt, y);
      }
      ctx.fillText(line, xAt, y);
      if (L.underline) {
        const w = ctx.measureText(line).width;
        const ux = L.align === 'left' ? xAt : L.align === 'right' ? xAt - w : xAt - w / 2;
        ctx.fillRect(ux, y + L.fontSize * 0.35, w, Math.max(1, L.fontSize * 0.05));
      }
    });
    ctx.restore();
  });
}

function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, Math.min(w, h) / 2));
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}
