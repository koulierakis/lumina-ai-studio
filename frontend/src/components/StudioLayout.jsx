import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels';
import CommandPalette from './CommandPalette';

export default function StudioLayout() {
  return (
    <div className="min-h-screen w-full overflow-visible bg-ink-950 lumina-noise text-foreground">
      <PanelGroup direction="horizontal" className="!h-auto min-h-screen w-full !overflow-visible">
        <Panel defaultSize={16} minSize={12} maxSize={22} className="min-h-screen !overflow-visible">
          <Sidebar />
        </Panel>
        <PanelResizeHandle className="w-px bg-white/[0.06] hover:bg-gold/40 transition-colors" />
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
