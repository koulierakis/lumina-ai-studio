// Filter preset definitions.
// Each preset yields a CSS filter string PLUS an optional overlay (color + blend mode + alpha)
// applied on top of the image for warmth/tint effects.

export const FILTERS = {
  None:          { css: '', overlay: null },
  Natural:       { css: 'contrast(1.05) saturate(1.05)', overlay: null },
  Portrait:      { css: 'contrast(1.06) saturate(0.92) brightness(1.03)', overlay: { color: '#f2c9a1', alpha: 0.06, blend: 'soft-light' } },
  Cinematic:     { css: 'contrast(1.15) saturate(1.1) brightness(0.96)', overlay: { color: '#1e3a5f', alpha: 0.10, blend: 'soft-light' } },
  Warm:          { css: 'saturate(1.08) brightness(1.02)', overlay: { color: '#ffb060', alpha: 0.12, blend: 'soft-light' } },
  Cool:          { css: 'saturate(0.95) brightness(1.02)', overlay: { color: '#7fbfff', alpha: 0.12, blend: 'soft-light' } },
  Vintage:       { css: 'sepia(0.35) contrast(0.95) saturate(0.85) brightness(1.02)', overlay: { color: '#f0a060', alpha: 0.08, blend: 'multiply' } },
  'Black & White':{ css: 'grayscale(1) contrast(1.06)', overlay: null },
  Matte:         { css: 'contrast(0.9) brightness(1.05) saturate(0.9)', overlay: { color: '#c8c8d8', alpha: 0.05, blend: 'lighten' } },
  Film:          { css: 'contrast(1.1) saturate(0.95) sepia(0.08)', overlay: { color: '#5a3e2b', alpha: 0.05, blend: 'soft-light' } },
};

export const FILTER_KEYS = Object.keys(FILTERS);

// Blend a filter's intensity (0..100) with the identity ('no-op').
// The CSS `filter` property does not have an intensity multiplier natively, so
// we approximate: at 100% return the full css; at 0% return ''. We can't
// mid-scale CSS filter reliably, so we interpolate saturate/contrast/brightness
// numerically when the string parses that way. For the CSS overlay we scale alpha.
function scaleFactor(name, valueStr, intensity) {
  // valueStr like "1.15" — 1 is identity for saturate/contrast/brightness
  const v = parseFloat(valueStr);
  if (Number.isNaN(v)) return valueStr;
  const identity = 1;
  const t = intensity / 100;
  return (identity + (v - identity) * t).toFixed(3);
}

export function cssForFilter(preset, intensity = 100) {
  const f = FILTERS[preset];
  if (!f || !f.css) return '';
  if (intensity >= 100) return f.css;
  if (intensity <= 0) return '';
  // Parse "contrast(1.05) saturate(1.05) ..." and scale numeric args.
  return f.css.replace(/(\w[\w-]*)\(([^)]+)\)/g, (_m, name, arg) => {
    if (['contrast', 'saturate', 'brightness', 'sepia', 'grayscale'].includes(name)) {
      return `${name}(${scaleFactor(name, arg, intensity)})`;
    }
    return `${name}(${arg})`;
  });
}

export function overlayForFilter(preset, intensity = 100) {
  const f = FILTERS[preset];
  if (!f || !f.overlay) return null;
  const t = intensity / 100;
  return { ...f.overlay, alpha: f.overlay.alpha * t };
}
