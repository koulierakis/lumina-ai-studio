// Convert an editor state into a CSS filter string + overlay for the live
// preview <img>. Also expose a function that renders the same edit into an
// offscreen canvas for export at full pixel resolution.

import { cssForFilter, overlayForFilter } from './filters';
import { drawTextLayersToCanvas } from './textLayers';

/** Compose a CSS filter string from adjustments (real-time preview). */
export function buildCssFilter(state) {
  const a = state.adjust;
  // Combine exposure + brightness into brightness (both act similarly for preview).
  const brightness = 1 + (a.brightness + a.exposure) / 100;
  const contrast = 1 + a.contrast / 100;
  // saturation + vibrance both feed into saturate() (vibrance weighted lower).
  const saturate = Math.max(0, 1 + (a.saturation + a.vibrance * 0.6) / 100);
  // temperature -> hue rotation approximation; tint -> hue shift as well.
  const hue = a.temperature * -0.4 + a.tint * 0.4; // degrees
  const blur = Math.max(0, a.blur);
  const filterPresetCss = cssForFilter(state.filter.preset, state.filter.intensity);
  const parts = [
    filterPresetCss,
    `brightness(${brightness.toFixed(3)})`,
    `contrast(${contrast.toFixed(3)})`,
    `saturate(${saturate.toFixed(3)})`,
    hue !== 0 ? `hue-rotate(${hue.toFixed(1)}deg)` : '',
    blur > 0 ? `blur(${blur.toFixed(1)}px)` : '',
  ];
  return parts.filter(Boolean).join(' ');
}

/** Compute transform string for CSS transform on the <img>. */
export function buildCssTransform(state) {
  const t = state.transform;
  const parts = [];
  if (t.rotation) parts.push(`rotate(${t.rotation}deg)`);
  parts.push(`scale(${t.flipH ? -1 : 1}, ${t.flipV ? -1 : 1})`);
  return parts.join(' ');
}

/** Style object combining opacity + filter + transform. */
export function livePreviewStyle(state) {
  return {
    filter: buildCssFilter(state),
    transform: buildCssTransform(state),
    opacity: state.adjust.opacity / 100,
    transition: 'filter 60ms linear, transform 120ms ease',
  };
}

/** Overlay div style (for warmth/tint colored film + vignette). */
export function overlayStyles(state) {
  const preset = overlayForFilter(state.filter.preset, state.filter.intensity);
  const list = [];
  if (preset && preset.alpha > 0.001) {
    list.push({
      key: 'preset',
      style: {
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background: preset.color, mixBlendMode: preset.blend, opacity: preset.alpha,
      },
    });
  }
  // Simulated warmth / tint via color layer
  if (state.adjust.temperature !== 0) {
    const t = state.adjust.temperature;
    list.push({
      key: 'temperature',
      style: {
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background: t > 0 ? '#ff8a1a' : '#3aa8ff',
        opacity: Math.min(0.25, Math.abs(t) / 400),
        mixBlendMode: 'soft-light',
      },
    });
  }
  if (state.adjust.tint !== 0) {
    const t = state.adjust.tint;
    list.push({
      key: 'tint',
      style: {
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background: t > 0 ? '#c02090' : '#22c07a',
        opacity: Math.min(0.25, Math.abs(t) / 400),
        mixBlendMode: 'soft-light',
      },
    });
  }
  // Vignette
  if (state.adjust.vignette > 0) {
    const v = state.adjust.vignette / 100;
    list.push({
      key: 'vignette',
      style: {
        position: 'absolute', inset: 0, pointerEvents: 'none',
        boxShadow: `inset 0 0 ${120 + v * 200}px ${20 + v * 120}px rgba(0,0,0,${(v * 0.75).toFixed(2)})`,
      },
    });
  }
  return list;
}

/** Render the final edited image to an offscreen canvas at full resolution. */
export function renderToCanvas(imgEl, state) {
  const src = imgEl;
  const iw = src.naturalWidth;
  const ih = src.naturalHeight;
  const t = state.transform;

  // Apply crop (in image pixels) if any.
  const crop = t.crop && t.crop.w > 0 && t.crop.h > 0 ? t.crop : { x: 0, y: 0, w: iw, h: ih };

  // For rotation not multiple of 90, expand canvas to fit.
  const rot = ((t.rotation % 360) + 360) % 360;
  const rad = (rot * Math.PI) / 180;
  const sin = Math.abs(Math.sin(rad));
  const cos = Math.abs(Math.cos(rad));
  const outW = Math.round(crop.w * cos + crop.h * sin);
  const outH = Math.round(crop.w * sin + crop.h * cos);

  const canvas = document.createElement('canvas');
  canvas.width = outW;
  canvas.height = outH;
  const ctx = canvas.getContext('2d');

  ctx.save();
  ctx.translate(outW / 2, outH / 2);
  ctx.rotate(rad);
  ctx.scale(t.flipH ? -1 : 1, t.flipV ? -1 : 1);
  // CSS filter equivalent supported by Canvas 2D
  ctx.filter = buildCssFilter(state);
  ctx.globalAlpha = state.adjust.opacity / 100;
  ctx.drawImage(src, crop.x, crop.y, crop.w, crop.h, -crop.w / 2, -crop.h / 2, crop.w, crop.h);
  ctx.restore();

  // Vignette on canvas (radial gradient)
  if (state.adjust.vignette > 0) {
    const v = state.adjust.vignette / 100;
    const grad = ctx.createRadialGradient(outW / 2, outH / 2, Math.min(outW, outH) * 0.3, outW / 2, outH / 2, Math.max(outW, outH) * 0.75);
    grad.addColorStop(0, 'rgba(0,0,0,0)');
    grad.addColorStop(1, `rgba(0,0,0,${(v * 0.85).toFixed(3)})`);
    ctx.save();
    ctx.filter = 'none';
    ctx.globalAlpha = 1;
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, outW, outH);
    ctx.restore();
  }

  // Color overlays (temperature/tint/preset overlay)
  const overlays = overlayStyles(state);
  ctx.save();
  ctx.filter = 'none';
  overlays.forEach((o) => {
    if (o.key === 'preset' || o.key === 'temperature' || o.key === 'tint') {
      ctx.globalCompositeOperation = 'soft-light';
      ctx.globalAlpha = o.style.opacity ?? 0.1;
      ctx.fillStyle = o.style.background;
      ctx.fillRect(0, 0, outW, outH);
    }
  });
  ctx.restore();

  // Burn text layers on top at native scale
  if (state.textLayers && state.textLayers.length) {
    ctx.save();
    ctx.filter = 'none';
    ctx.globalCompositeOperation = 'source-over';
    drawTextLayersToCanvas(ctx, state.textLayers, outW, outH);
    ctx.restore();
  }

  return canvas;
}

/** Return a Blob for the current edit. */
export async function exportBlob(imgEl, state, { format = 'image/png', quality = 0.95 } = {}) {
  const canvas = renderToCanvas(imgEl, state);
  return new Promise((resolve) => canvas.toBlob(resolve, format, quality));
}
