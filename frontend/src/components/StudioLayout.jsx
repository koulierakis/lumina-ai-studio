import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels';
import CommandPalette from './CommandPalette';

export default function StudioLayout() {
  return (
    <div className="h-screen w-screen overflow-hidden bg-ink-950 lumina-noise text-foreground">
      <PanelGroup direction="horizontal" className="h-full w-full">
        <Panel defaultSize={16} minSize={12} maxSize={22} className="h-full">
          <Sidebar />
        </Panel>
        <PanelResizeHandle className="w-px bg-white/[0.06] hover:bg-gold/40 transition-colors" />
        <Panel minSize={40} className="h-full">
          <div className="h-full w-full">
            <Outlet />
            <CommandPalette />
          </div>
        </Panel>
      </PanelGroup>
    </div>
  );
}
