// Video editor state model + helpers.
// A project = { clips[], textOverlays[], music, voiceover, aspect_ratio, fps, resolution }
// Each clip = { id, kind:'video'|'photo', assetId, mime, duration, trimStart, trimEnd,
//               transition, adjust, filter, kenBurns, volume }
// TextOverlay = { id, text, start, end, x, y, fontSize, color, ... }
// Music = { assetId, mime, volume, fadeIn, fadeOut }
// Voice = { assetId, mime, volume }

import { newTextLayer } from '../editor/textLayers';

export const RATIOS = ['16:9', '9:16', '1:1', '4:5'];
export const FPS_CHOICES = [24, 25, 30];
export const RES_CHOICES = ['720p', '1080p'];
export const TRANSITIONS = ['none', 'fade', 'dissolve', 'slide', 'zoom'];
export const KEN_BURNS = ['none', 'zoom-in', 'zoom-out', 'pan-left', 'pan-right'];

export const DEFAULT_ADJUST = {
  brightness: 0, contrast: 0, saturation: 0, temperature: 0, sharpness: 0, blur: 0,
};

export const FILTERS = ['None', 'Natural', 'Cinematic', 'Warm', 'Cool', 'B&W', 'Vintage', 'Matte'];

let cid = 1;
export function newClip(assetId, kind, mime, duration = 4) {
  return {
    id: `c-${Date.now()}-${cid++}`,
    kind, assetId, mime,
    duration: Math.max(0.5, duration),
    trimStart: 0,
    trimEnd: kind === 'video' ? duration : 0, // for photo, trim not used
    transition: 'none',
    adjust: { ...DEFAULT_ADJUST },
    filter: 'None',
    kenBurns: kind === 'photo' ? 'zoom-in' : 'none',
    volume: 100,
  };
}

export function newOverlay(text = 'Text') {
  const t = newTextLayer({ text, x: 5, y: 85, w: 90, h: 10, align: 'center' });
  t.start = 0; t.end = 3;
  return t;
}

export const EMPTY_PROJECT_STATE = {
  clips: [],
  textOverlays: [],
  music: null,     // { assetId, mime, volume, fadeIn, fadeOut }
  voiceover: null, // { assetId, mime, volume }
};

/** Total timeline duration in seconds. */
export function totalDuration(state) {
  return (state.clips || []).reduce((acc, c) => acc + effectiveDuration(c), 0);
}
export function effectiveDuration(c) {
  if (c.kind === 'video') return Math.max(0.1, (c.trimEnd || c.duration) - (c.trimStart || 0));
  return Math.max(0.1, c.duration || 4);
}

/** Given a global timeline time, return {clipIndex, localTime}. */
export function locateAt(state, t) {
  let acc = 0;
  for (let i = 0; i < (state.clips || []).length; i++) {
    const d = effectiveDuration(state.clips[i]);
    if (t < acc + d) return { index: i, localTime: t - acc };
    acc += d;
  }
  return { index: (state.clips.length || 1) - 1, localTime: 0 };
}

/** Build CSS filter string for a clip (used for preview). */
export function cssFilterFor(clip) {
  const a = clip.adjust || DEFAULT_ADJUST;
  const parts = [];
  parts.push(`brightness(${(1 + a.brightness / 100).toFixed(3)})`);
  parts.push(`contrast(${(1 + a.contrast / 100).toFixed(3)})`);
  parts.push(`saturate(${(1 + a.saturation / 100).toFixed(3)})`);
  if (a.temperature) parts.push(`hue-rotate(${(-a.temperature * 0.4).toFixed(1)}deg)`);
  if (a.blur > 0) parts.push(`blur(${a.blur}px)`);
  // Filter preset
  const f = clip.filter;
  if (f === 'Cinematic') parts.push('contrast(1.1) saturate(1.05)');
  else if (f === 'Warm') parts.push('saturate(1.05) brightness(1.02)');
  else if (f === 'Cool') parts.push('saturate(0.95) brightness(1.02)');
  else if (f === 'B&W') parts.push('grayscale(1) contrast(1.05)');
  else if (f === 'Vintage') parts.push('sepia(0.35) contrast(0.95) saturate(0.85)');
  else if (f === 'Matte') parts.push('contrast(0.9) brightness(1.05) saturate(0.9)');
  else if (f === 'Natural') parts.push('contrast(1.05) saturate(1.03)');
  return parts.join(' ');
}

/** Ken Burns transform for photos, progress in [0..1]. */
export function kenBurnsTransform(kind, t) {
  switch (kind) {
    case 'zoom-in': return `scale(${(1 + 0.12 * t).toFixed(3)})`;
    case 'zoom-out': return `scale(${(1.12 - 0.12 * t).toFixed(3)})`;
    case 'pan-left': return `scale(1.1) translateX(${(-4 + 8 * t).toFixed(2)}%)`;
    case 'pan-right': return `scale(1.1) translateX(${(4 - 8 * t).toFixed(2)}%)`;
    default: return 'none';
  }
}

/** Aspect ratio ⇒ output width/height at chosen resolution. */
export function outputDims(aspect, res) {
  const h = res === '720p' ? 720 : 1080;
  const [aw, ah] = aspect.split(':').map(Number);
  const w = Math.round((h * aw) / ah / 2) * 2;
  return { w, h };
}
