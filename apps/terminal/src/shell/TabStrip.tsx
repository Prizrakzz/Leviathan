import { useUI } from '@/store/ui';

/** The workspace tab strip (P1.5): chip-styled tabs above the document area. Renders NOTHING with zero
 *  tabs (the chat panel owns the full height — today's look). Close = ✕ or middle-click; a11y = tablist. */
export function TabStrip() {
  const tabs = useUI((s) => s.tabs);
  const activeTabId = useUI((s) => s.activeTabId);
  if (tabs.length === 0) return null;
  return (
    <div
      role="tablist"
      aria-label="open documents"
      className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-line bg-bg-0 px-2 py-1"
      data-testid="tab-strip"
    >
      {tabs.map((t) => {
        const active = t.id === activeTabId;
        return (
          <div
            key={t.id}
            role="tab"
            aria-selected={active}
            onAuxClick={(e) => {
              if (e.button === 1) useUI.getState().closeTab(t.id); // middle-click close
            }}
            className={`flex shrink-0 cursor-pointer items-center gap-1.5 rounded-chip border px-2.5 py-1 font-mono text-11 ${
              active
                ? 'border-cyan bg-bg-1 text-cyan'
                : 'border-line text-text-dim hover:border-cyan hover:text-text'
            }`}
          >
            <button onClick={() => useUI.getState().setActiveTab(t.id)} className="max-w-[180px] truncate">
              {t.title}
            </button>
            <button
              aria-label={`close ${t.title}`}
              onClick={(e) => {
                e.stopPropagation();
                useUI.getState().closeTab(t.id);
              }}
              className="text-text-faint hover:text-neg"
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
