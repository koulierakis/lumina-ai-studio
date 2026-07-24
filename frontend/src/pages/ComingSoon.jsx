export default function ComingSoon({ title = 'Coming Soon' }) {
  return (
    <div className="h-full w-full flex items-center justify-center p-10">
      <div className="text-center max-w-md">
        <div className="inline-block px-3 py-1 rounded-full text-[10px] uppercase tracking-[0.3em] text-gold border border-gold/40 mb-6">
          Phase 2
        </div>
        <h2 className="font-display text-4xl text-white tracking-tight mb-3">{title}</h2>
        <p className="text-white/50 text-sm leading-relaxed">
          This section is planned for Phase 2 of Lumina AI Desktop and will be enabled in a subsequent build.
        </p>
      </div>
    </div>
  );
}
