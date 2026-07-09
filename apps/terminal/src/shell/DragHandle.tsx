/** P1.5-T4: the chat panel's draggable top border. Pure presentational — behavior comes from
 *  usePanelDrag's handlers. WAI-ARIA separator; arrow keys resize; double-click resets. */
export function DragHandle({
  onPointerDown,
  onDoubleClick,
  onKeyDown,
}: {
  onPointerDown: (e: React.PointerEvent<HTMLElement>) => void;
  onDoubleClick: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => void;
}) {
  return (
    <div
      role="separator"
      aria-orientation="horizontal"
      aria-label="resize chat panel (drag, arrow keys, double-click to reset)"
      tabIndex={0}
      data-testid="drag-handle"
      onPointerDown={onPointerDown}
      onDoubleClick={onDoubleClick}
      onKeyDown={onKeyDown}
      className="group flex h-1.5 w-full shrink-0 cursor-row-resize items-center justify-center border-y border-line bg-bg-0 hover:bg-bg-2 focus:outline-none focus:ring-1 focus:ring-cyan"
    >
      <div className="h-0.5 w-8 rounded bg-line group-hover:bg-cyan" />
    </div>
  );
}
