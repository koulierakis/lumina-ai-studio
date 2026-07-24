// Custom filter presets saved by the user, per-owner (local, private).
const KEY = 'lumina_custom_filters';

export function loadCustomPresets() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveCustomPreset(name, snapshot) {
  const list = loadCustomPresets();
  const next = [...list.filter((x) => x.name !== name), { name, snapshot, ts: Date.now() }];
  localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

export function deleteCustomPreset(name) {
  const list = loadCustomPresets().filter((x) => x.name !== name);
  localStorage.setItem(KEY, JSON.stringify(list));
  return list;
}
