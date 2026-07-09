import type { TurnState } from '@/api/useTurn';
import { useUI } from '@/store/ui';
import { AnswerView } from '@/views/AnswerView';

/** The view container — renders the active opinionated view (design §3.2). The answer view owns its own
 *  scroll container (conversation column + pinned composer), so it gets overflow-hidden. Answer is the only
 *  view after the 5.6 view-prune. */
export function ViewContainer({
  turn,
  question,
  onAsk,
}: {
  turn: TurnState;
  question: string;
  onAsk: (q: string) => void;
}) {
  const view = useUI((s) => s.view);
  const cls =
    view === 'answer' ? 'flex-1 min-h-0 overflow-hidden bg-bg-0' : 'flex-1 overflow-auto bg-bg-0 p-4';
  return (
    <main className={cls} data-testid="view" data-view={view}>
      {view === 'answer' && <AnswerView turn={turn} question={question} onAsk={onAsk} />}
    </main>
  );
}
