import { useRef } from 'react';
import type { TurnState } from '@/api/useTurn';
import { usePanelDrag } from '@/hooks/usePanelDrag';
import { useUI } from '@/store/ui';
import { AnswerView } from '@/views/AnswerView';
import { DragHandle } from './DragHandle';
import TabDocument from './tabs/TabDocument';
import { TabStrip } from './TabStrip';

/**
 * P1.5: the workspace — replaces ViewContainer as Shell's main region (its `<main data-testid="view">`
 * landmark carries over). Two vertical rows: the DOCUMENT AREA (tab strip + active tab) over the CHAT
 * PANEL (the conversation — AnswerView unchanged), split by the ONE drag handle.
 *
 * ZERO TABS = today's look byte-for-byte: no strip, no handle, the chat panel takes the full height.
 * Tabs are workspace-global (thread switches swap the transcript, never the tabs).
 * STOMP RULE: the chat panel's height is owned by usePanelDrag via ref — never bound in JSX (a streaming
 * re-render mid-drag would snap the panel back to the last committed value).
 */
export function Workspace({
  turn,
  question,
  onAsk,
  onPrefill,
}: {
  turn: TurnState;
  question: string;
  onAsk: (q: string) => void;
  /** P9-E1a: threaded Shell -> AnswerView so watch chips can PREFILL the command bar (never submit). */
  onPrefill?: (q: string) => void;
}) {
  const view = useUI((s) => s.view);
  const tabs = useUI((s) => s.tabs);
  const activeTabId = useUI((s) => s.activeTabId);
  const containerRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const hasTabs = tabs.length > 0;
  const drag = usePanelDrag(containerRef, panelRef, hasTabs);
  const active = tabs.find((t) => t.id === activeTabId) ?? tabs[tabs.length - 1] ?? null;

  return (
    <main
      ref={containerRef}
      className="flex min-h-0 flex-1 flex-col overflow-hidden bg-bg-0"
      data-testid="view"
      data-view={view}
    >
      {hasTabs && (
        <>
          <TabStrip />
          <div className="min-h-0 flex-1" data-testid="document-area">
            {active && <TabDocument tab={active} />}
          </div>
          <DragHandle {...drag} />
        </>
      )}
      {/* zero tabs: no inline style -> flex-1 wins and the chat owns the full height (today's look).
          with tabs: usePanelDrag owns this element's height via ref (never JSX -- the stomp rule). */}
      <div
        ref={panelRef}
        className={hasTabs ? 'min-h-0 shrink-0 overflow-hidden' : 'min-h-0 flex-1 overflow-hidden'}
        data-testid="chat-panel"
      >
        <AnswerView turn={turn} question={question} onAsk={onAsk} onPrefill={onPrefill} />
      </div>
    </main>
  );
}
