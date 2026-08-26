import { useMemo, useState } from 'react';
import { ExternalLink, MapPinned, RefreshCw } from 'lucide-react';

const STANDALONE_DRIVE_URL = 'https://koulierakis.github.io/lumina-ai-studio/';

export default function LuminaDrive() {
  const [reloadKey, setReloadKey] = useState(0);
  const localDriveUrl = useMemo(() => `/drive/index.html?embedded=1&v=47&r=${reloadKey}`, [reloadKey]);

  return (
    <main className="flex h-full min-h-0 flex-col bg-ink-950" data-testid="lumina-drive-page">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-5 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-gold/20 bg-gold/10 text-gold">
            <MapPinned className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-[0.2em] text-gold">LUMINA Mobility</p>
            <h1 className="truncate font-display text-xl text-white">LUMINA Drive</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            className="inline-flex items-center gap-2 rounded-md border border-white/10 px-3 py-2 text-xs text-white/65 transition hover:border-gold/30 hover:text-white"
            title="Reload embedded Drive"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Reload
          </button>
          <a
            href={STANDALONE_DRIVE_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md border border-gold/25 bg-gold/10 px-3 py-2 text-xs text-gold transition hover:bg-gold/15"
            title="Open the standalone Drive deployment"
          >
            <ExternalLink className="h-3.5 w-3.5" /> Standalone
          </a>
        </div>
      </header>

      <div className="relative min-h-0 flex-1 bg-black">
        <iframe
          key={reloadKey}
          title="LUMINA Drive Assistant"
          src={localDriveUrl}
          className="absolute inset-0 h-full w-full border-0"
          allow="geolocation; microphone; autoplay"
          data-testid="lumina-drive-frame"
        />
      </div>
    </main>
  );
}
