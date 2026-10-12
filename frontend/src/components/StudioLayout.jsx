import { Outlet, useLocation, Link } from 'react-router-dom';
import Sidebar from './Sidebar';
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels';
import CommandPalette from './CommandPalette';
import LiveAppPreviewModal from './LiveAppPreviewModal';
import { useState } from 'react';
import { ArrowLeft, Menu, MonitorPlay, Sparkles, X } from 'lucide-react';
import { MODULE_REGISTRY } from '../platform/moduleRegistry';

export default function StudioLayout() {
  const location = useLocation();
  const isDashboard = location.pathname === '/studio/dashboard' || location.pathname === '/studio';
  const [sidebarDrawer, setSidebarDrawer] = useState(false);
  const [showLivePreview, setShowLivePreview] = useState(false);

  const activeModule = MODULE_REGISTRY.find((m) => location.pathname.startsWith(m.route));
  const activeToolName = activeModule?.name || 'Studio Tool';

  return (
    <div className="min-h-screen w-full overflow-visible bg-ink-950 lumina-noise text-foreground">
      {/* Universal Top Bar when inside any AI Tool */}
      {!isDashboard && (
        <header className="sticky top-0 z-40 flex items-center justify-between border-b border-white/[0.08] bg-ink-950/95 px-4 py-2.5 backdrop-blur-md shadow-md">
          <div className="flex items-center gap-3">
            <Link
              to="/studio/dashboard"
              data-testid="header-back-button"
              className="inline-flex items-center gap-2 rounded-lg border border-gold/40 bg-gold/15 px-3.5 py-1.5 text-xs font-bold text-gold transition hover:bg-gold hover:text-black shadow-sm"
              title="Επιστροφή στην Αρχική Οθόνη (Dashboard)"
            >
              <ArrowLeft className="h-4 w-4" />
              <span>← Επιστροφή στην Αρχική</span>
            </Link>
            <button
              type="button"
              onClick={() => setSidebarDrawer((v) => !v)}
              data-testid="tools-menu-drawer-btn"
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs text-white/80 transition hover:bg-white/10 hover:text-white"
              title="Εμφάνιση / Απόκρυψη όλων των εργαλείων"
            >
              <Menu className="h-4 w-4 text-gold" />
              <span className="hidden sm:inline">Μενού Εργαλείων</span>
            </button>
            <div className="hidden h-4 w-px bg-white/15 md:block" />
            <span className="flex items-center gap-1.5 rounded-full border border-white/15 bg-white/[0.03] px-3 py-0.5 text-xs font-semibold text-white">
              <Sparkles className="h-3.5 w-3.5 text-gold" />
              {activeToolName}
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => setShowLivePreview(true)}
              data-testid="topbar-live-preview-btn"
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-bold text-emerald-300 transition hover:bg-emerald-500 hover:text-black shadow-sm"
              title="Ζωντανή Προεπισκόπηση της Εφαρμογής"
            >
              <MonitorPlay className="h-3.5 w-3.5" />
              <span>Ζωντανή Προεπισκόπηση</span>
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            </button>
            <span className="hidden text-[11px] uppercase tracking-widest text-emerald-400 font-mono xl:inline">● Focus Mode</span>
          </div>
        </header>
      )}

      {/* Slide-out Drawer for Tools Menu when in Focus Mode */}
      {sidebarDrawer && (
        <div className="fixed inset-0 z-50 flex">
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setSidebarDrawer(false)} />
          <div className="relative z-10 w-72 max-w-[85vw] border-r border-white/10 bg-ink-950 shadow-2xl flex flex-col">
            <div className="flex items-center justify-between border-b border-white/10 p-3.5 gap-2">
              <Link
                to="/studio/dashboard"
                onClick={() => setSidebarDrawer(false)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gold/40 bg-gold/15 px-3 py-1.5 text-xs font-bold text-gold hover:bg-gold hover:text-black transition"
                title="Επιστροφή στην Αρχική Οθόνη"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                <span>Επιστροφή στην Αρχική</span>
              </Link>
              <button
                onClick={() => setSidebarDrawer(false)}
                className="rounded p-1.5 text-white/60 hover:text-white hover:bg-white/10 transition"
                title="Κλείσιμο μενού"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <Sidebar
                onClose={() => setSidebarDrawer(false)}
                onOpenLivePreview={() => {
                  setSidebarDrawer(false);
                  setShowLivePreview(true);
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Universal Live App Preview Modal */}
      <LiveAppPreviewModal
        isOpen={showLivePreview}
        onClose={() => setShowLivePreview(false)}
        initialPath={location.pathname}
      />

      <PanelGroup direction="horizontal" className="!h-auto min-h-screen w-full !overflow-visible">
        {isDashboard ? (
          <>
            <Panel defaultSize={16} minSize={12} maxSize={22} className="min-h-screen !overflow-visible">
              <Sidebar onOpenLivePreview={() => setShowLivePreview(true)} />
            </Panel>
            <PanelResizeHandle className="w-px bg-white/[0.06] hover:bg-gold/40 transition-colors" />
          </>
        ) : null}
        <Panel minSize={40} className="min-h-screen !overflow-visible">
          <main className="min-h-screen w-full overflow-visible">
            <Outlet />
            <CommandPalette />
          </main>
        </Panel>
      </PanelGroup>
    </div>
  );
}
