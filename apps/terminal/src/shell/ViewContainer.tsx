import type { TurnState } from '@/api/useTurn';
import { useUI } from '@/store/ui';
import { AnswerView } from '@/views/AnswerView';
import { ConvergenceView } from '@/views/ConvergenceView';
import { DeepDiveView } from '@/views/DeepDiveView';

/** The view container — renders the active opinionated view (design §3.2). */
export function ViewContainer({ turn }: { turn: TurnState }) {
  const view = useUI((s) => s.view);
  return (
    <main className="flex-1 overflow-auto bg-bg-0 p-4" data-testid="view" data-view={view}>
      {view === 'answer' && <AnswerView turn={turn} />}
      {view === 'convergence' && <ConvergenceView />}
      {view === 'deep' && <DeepDiveView />}
    </main>
  );
}
