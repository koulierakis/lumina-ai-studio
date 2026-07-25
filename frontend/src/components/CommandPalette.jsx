import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { apiGet } from '../lib/api';
import { MODULE_REGISTRY } from '../platform/moduleRegistry';

export default function CommandPalette() {
  const [open, setOpen] = useState(false); const [query, setQuery] = useState(''); const [items, setItems] = useState([]); const navigate = useNavigate(); const input = useRef();
  useEffect(() => { const key = (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setOpen(true); } if (event.key === 'Escape') setOpen(false); }; window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key); }, []);
  useEffect(() => { if (open) setTimeout(() => input.current?.focus(), 0); }, [open]);
  useEffect(() => { let live = true; if (!query.trim()) { setItems(MODULE_REGISTRY.map((item) => ({ label: item.name, route: item.route }))); return; } const timer = setTimeout(async () => { try { const data = await apiGet('/workspace/search', { params: { q: query } }); if (live) setItems(Object.values(data).flat().map((item) => ({ label: item.name || item.title || item.prompt || item.id, route: item.route || (item.id && item.name ? `/studio/projects/${item.id}` : '/studio/search') }))); } catch { if (live) setItems([]); } }, 200); return () => { live = false; clearTimeout(timer); }; }, [query, open]);
  if (!open) return null;
  return <div className="fixed inset-0 z-[200] bg-black/65 p-5" onClick={() => setOpen(false)}><div className="mx-auto mt-[12vh] max-w-xl rounded-xl border border-white/10 bg-ink-950 p-3 shadow-2xl" onClick={(event) => event.stopPropagation()}><div className="flex items-center gap-2 border-b border-white/10 px-2"><Search className="h-4 w-4 text-gold" /><input ref={input} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search LUMINA or run a command" className="w-full bg-transparent py-4 text-sm text-white outline-none" /></div><div className="max-h-80 overflow-y-auto py-2">{items.map((item, index) => <button key={`${item.label}-${index}`} onClick={() => { setOpen(false); navigate(item.route); }} className="block w-full rounded px-3 py-3 text-left text-sm text-white/70 hover:bg-white/5">{item.label}</button>)}{!items.length && <p className="p-4 text-sm text-white/40">No matching private workspace items.</p>}</div></div></div>;
}
