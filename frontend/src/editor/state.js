// Editor state model, reducer, and default values.
// Everything the editor knows is derived from `state` — non-destructive.

export const DEFAULT_ADJUST = {
  exposure: 0, brightness: 0, contrast: 0,
  highlights: 0, shadows: 0, whites: 0, blacks: 0,
  temperature: 0, tint: 0,
  saturation: 0, vibrance: 0,
  sharpness: 0, clarity: 0, dehaze: 0,
  blur: 0, vignette: 0, opacity: 100,
};

export const ADJUST_RANGES = {
  exposure: [-100, 100], brightness: [-100, 100], contrast: [-100, 100],
  highlights: [-100, 100], shadows: [-100, 100], whites: [-100, 100], blacks: [-100, 100],
  temperature: [-100, 100], tint: [-100, 100],
  saturation: [-100, 100], vibrance: [-100, 100],
  sharpness: [0, 100], clarity: [-100, 100], dehaze: [-100, 100],
  blur: [0, 50], vignette: [0, 100], opacity: [0, 100],
};

export const ADJUST_LABELS = {
  exposure: 'Exposure', brightness: 'Brightness', contrast: 'Contrast',
  highlights: 'Highlights', shadows: 'Shadows', whites: 'Whites', blacks: 'Blacks',
  temperature: 'Temperature', tint: 'Tint',
  saturation: 'Saturation', vibrance: 'Vibrance',
  sharpness: 'Sharpness', clarity: 'Clarity', dehaze: 'Dehaze',
  blur: 'Blur', vignette: 'Vignette', opacity: 'Opacity',
};

export const DEFAULT_TRANSFORM = {
  rotation: 0,      // in degrees, -180..180
  flipH: false,
  flipV: false,
  crop: null,       // { x, y, w, h } in image pixels, or null
};

export const DEFAULT_STATE = {
  transform: { ...DEFAULT_TRANSFORM },
  adjust: { ...DEFAULT_ADJUST },
  filter: { preset: 'None', intensity: 100 },
  textLayers: [],
  mask: null,      // base64 png data URL of the current mask, if any
  // history managed separately
};

// ---------- Reducer ----------
// The editor keeps a history stack of `present` snapshots for undo/redo.
export function initialHistory(state = DEFAULT_STATE) {
  return { past: [], present: state, future: [] };
}

export function reduce(h, action) {
  switch (action.type) {
    case 'SET': {
      // record history
      if (JSON.stringify(action.next) === JSON.stringify(h.present)) return h;
      return { past: [...h.past, h.present].slice(-100), present: action.next, future: [] };
    }
    case 'REPLACE': {
      // silent (no history entry) — for slider dragging live preview
      return { ...h, present: action.next };
    }
    case 'COMMIT': {
      // capture current present into history (called on slider release)
      const last = h.past[h.past.length - 1];
      if (last && JSON.stringify(last) === JSON.stringify(h.present)) return h;
      return { past: [...h.past, h.present].slice(-100), present: h.present, future: [] };
    }
    case 'UNDO': {
      if (!h.past.length) return h;
      const prev = h.past[h.past.length - 1];
      return { past: h.past.slice(0, -1), present: prev, future: [h.present, ...h.future] };
    }
    case 'REDO': {
      if (!h.future.length) return h;
      const next = h.future[0];
      return { past: [...h.past, h.present], present: next, future: h.future.slice(1) };
    }
    case 'RESET_ALL': {
      return { past: [...h.past, h.present], present: DEFAULT_STATE, future: [] };
    }
    case 'RESTORE': {
      return { past: [], present: action.state, future: [] };
    }
    default:
      return h;
  }
}

// Helpers to update sub-slices
export function updateAdjust(state, key, value) {
  return { ...state, adjust: { ...state.adjust, [key]: value } };
}
export function updateTransform(state, patch) {
  return { ...state, transform: { ...state.transform, ...patch } };
}
export function updateFilter(state, patch) {
  return { ...state, filter: { ...state.filter, ...patch } };
}
