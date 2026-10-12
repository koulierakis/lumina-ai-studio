import { useState } from 'react';
import {
  ExternalLink,
  Laptop,
  Maximize2,
  Minimize2,
  MonitorPlay,
  RefreshCw,
  Smartphone,
  Tablet,
  X,
} from 'lucide-react';

const PRESET_ROUTES = [
  { label: 'Αρχική (Dashboard)', path: '/studio/dashboard' },
  { label: 'Google Code Builder', path: '/studio/code-builder' },
  { label: 'LUMINA Mind', path: '/studio/mind' },
  { label: 'Image Studio', path: '/studio/generate' },
  { label: 'Video Studio', path: '/studio/video-studio' },
  { label: 'Έγγραφα', path: '/studio/documents' },
];

export default function LiveAppPreviewModal({ isOpen, onClose, initialPath = '/studio/dashboard' }) {
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [inputPath, setInputPath] = useState(initialPath);
  const [viewport, setViewport] = useState('desktop'); // desktop, tablet, mobile
  const [iframeKey, setIframeKey] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);

  if (!isOpen) return null;

  const handleNavigate = (path) => {
    setCurrentPath(path);
    setInputPath(path);
    setIframeKey((k) => k + 1);
  };

  const handleInputSubmit = (e) => {
    e.preventDefault();
    let target = inputPath.trim();
    if (!target) target = '/studio/dashboard';
    if (!target.startsWith('/') && !target.startsWith('http')) {
      target = `/${target}`;
    }
    setCurrentPath(target);
    setIframeKey((k) => k + 1);
  };

  const reloadIframe = () => {
    setIframeKey((k) => k + 1);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div
        className={`flex flex-col bg-ink-950 border border-white/15 rounded-2xl shadow-2xl overflow-hidden transition-all duration-200 ${
          isFullscreen
            ? 'w-full h-full'
            : 'w-full max-w-[1500px] h-[92vh] max-h-[920px]'
        }`}
      >
        {/* ─── MODAL HEADER & BROWSER TOOLBAR ─── */}
        <div className="flex flex-col border-b border-white/10 bg-white/[0.03] p-3 gap-2.5">
          {/* Row 1: Title, Status & Actions */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-3 py-1 text-xs font-bold text-emerald-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                <span>ΖΩΝΤΑΝΗ ΠΡΟΕΠΙΣΚΟΠΗΣΗ ΕΦΑΡΜΟΓΗΣ (LIVE PREVIEW)</span>
              </span>
              <span className="hidden md:inline text-xs text-white/50">
                Πραγματικός χρόνος εκτέλεσης της web εφαρμογής
              </span>
            </div>

            <div className="flex items-center gap-2">
              {/* Viewport switchers */}
              <div className="flex items-center rounded-lg border border-white/10 bg-black/40 p-1 text-xs">
                <button
                  type="button"
                  onClick={() => setViewport('desktop')}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md transition ${
                    viewport === 'desktop' ? 'bg-gold text-black font-semibold' : 'text-white/60 hover:text-white'
                  }`}
                  title="Desktop προβολή (100%)"
                >
                  <Laptop className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Desktop</span>
                </button>
                <button
                  type="button"
                  onClick={() => setViewport('tablet')}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md transition ${
                    viewport === 'tablet' ? 'bg-gold text-black font-semibold' : 'text-white/60 hover:text-white'
                  }`}
                  title="Tablet προβολή (768px)"
                >
                  <Tablet className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Tablet</span>
                </button>
                <button
                  type="button"
                  onClick={() => setViewport('mobile')}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md transition ${
                    viewport === 'mobile' ? 'bg-gold text-black font-semibold' : 'text-white/60 hover:text-white'
                  }`}
                  title="Mobile προβολή (375px)"
                >
                  <Smartphone className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Mobile</span>
                </button>
              </div>

              {/* Open in new tab */}
              <a
                href={currentPath}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-lg border border-gold/40 bg-gold/10 px-3 py-1.5 text-xs font-semibold text-gold hover:bg-gold hover:text-black transition"
                title="Άνοιγμα σε νέα καρτέλα browser"
              >
                <span>Νέα Καρτέλα</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </a>

              {/* Fullscreen toggle */}
              <button
                type="button"
                onClick={() => setIsFullscreen((v) => !v)}
                className="p-1.5 rounded-lg border border-white/10 bg-white/[0.04] text-white/70 hover:text-white hover:bg-white/10 transition"
                title={isFullscreen ? 'Σμίκρυνση παραθύρου' : 'Πλήρης οθόνη'}
              >
                {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>

              {/* Close button */}
              <button
                type="button"
                onClick={onClose}
                className="p-1.5 rounded-lg border border-white/10 bg-white/[0.04] text-white/70 hover:text-white hover:bg-red-500/20 hover:border-red-400/40 transition"
                title="Κλείσιμο προεπισκόπησης"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Row 2: Address Bar and Presets */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={reloadIframe}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 text-xs text-white/80 hover:bg-white/10 hover:text-white transition"
              title="Ανανέωση σελίδας"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Ανανέωση</span>
            </button>

            {/* URL input */}
            <form onSubmit={handleInputSubmit} className="flex-1 min-w-[240px]">
              <div className="flex items-center rounded-lg border border-white/15 bg-black/70 px-3 py-1.5 focus-within:border-gold/60">
                <span className="text-[11px] font-mono text-white/40 mr-1.5">URL:</span>
                <input
                  type="text"
                  value={inputPath}
                  onChange={(e) => setInputPath(e.target.value)}
                  placeholder="/studio/dashboard"
                  className="w-full bg-transparent text-xs font-mono text-gold outline-none"
                />
                <button
                  type="submit"
                  className="ml-2 text-[10px] uppercase font-semibold tracking-wider text-white/50 hover:text-gold"
                >
                  Go
                </button>
              </div>
            </form>

            {/* Quick route buttons */}
            <div className="hidden lg:flex items-center gap-1">
              {PRESET_ROUTES.map((route) => (
                <button
                  key={route.path}
                  type="button"
                  onClick={() => handleNavigate(route.path)}
                  className={`px-2.5 py-1 rounded text-xs transition ${
                    currentPath === route.path
                      ? 'bg-gold text-black font-semibold'
                      : 'bg-white/[0.04] text-white/60 hover:text-white hover:bg-white/[0.08]'
                  }`}
                >
                  {route.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ─── LIVE APP IFRAME VIEWPORT CONTAINER ─── */}
        <div className="flex-1 w-full bg-black/90 flex items-center justify-center overflow-auto p-2 sm:p-4">
          <div
            className={`h-full bg-ink-950 rounded-xl overflow-hidden shadow-2xl border border-white/10 transition-all duration-300 flex flex-col ${
              viewport === 'desktop'
                ? 'w-full'
                : viewport === 'tablet'
                ? 'w-[768px]'
                : 'w-[375px]'
            }`}
          >
            <iframe
              key={iframeKey}
              src={currentPath}
              title="Lumina Application Live Preview"
              className="w-full h-full border-0 bg-background"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
