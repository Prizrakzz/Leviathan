import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { getGallery } from '@/api/client';
import type { GalleryItem } from '@/api/schema';
import { EMPTY_VOCAB, useCompose } from '@/store/compose';
import { useSession } from '@/store/session';

/**
 * D-UX-1 — the TEMPLATE LIBRARY: the prompt gallery as a recurring desk tool instead of an onboarding
 * screen. It lives in the top bar (the notifications/user-menu popover idiom) so it is reachable in EVERY
 * app state — mid-thread, over a chart tab, on a landing page — which is the whole critique that opened this
 * wave: the gallery was only ever visible on an empty thread, i.e. exactly once per session.
 *
 * Choosing a row PREFILLS the composer (store/compose) and CLOSES the panel. It never submits. What lands in
 * the box is the row's authored template with the server's own fill — the true near-firing pairing the
 * gallery advertises — and a slot bar of comboboxes above the box for retargeting it. So the default is a
 * question the engine can answer, and the edit path is fenced by the same census gate that built the list.
 *
 * The rows render the TEMPLATE, blanks and all (`{contract}` as a chip), not the filled example: this is a
 * library of question SHAPES, and showing the shape is what tells the reader they are about to fill it in.
 * The filled values show up the moment they choose, in the slot bar and in the box.
 *
 * Same `['gallery']` query key as the landing page: one cached read serves both surfaces, and this panel
 * adds no request of its own (the route is free and deterministic — no model, no quota — but it is still a
 * network call, and the two surfaces are often on screen within a second of each other).
 */
export function TemplateLibrary() {
  const ready = useSession((s) => s.ready);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const q = useQuery({
    queryKey: ['gallery'],
    queryFn: getGallery,
    enabled: ready,
    staleTime: 900_000, // the convergence warmer behind it re-fires every 900s
  });

  // Outside-click closes (the NotificationBell/UserMenu convention).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const items = q.data?.items ?? [];
  const vocab = q.data?.vocab ?? EMPTY_VOCAB;

  // Grouped in SERVER order (gallery.yaml file order) — the authored curation is the running order, and the
  // file is where it gets reviewed. Unlike the landing row there is no clamp: this is the full library.
  const groups: [string, GalleryItem[]][] = [];
  for (const it of items) {
    const g = groups.find(([c]) => c === it.category);
    if (g) g[1].push(it);
    else groups.push([it.category, [it]]);
  }

  const choose = (it: GalleryItem) => {
    // `template` is optional on the wire (an older server omits it) — then the filled question IS the
    // template: a starter with no blanks, still prefilled, still never submitted.
    useCompose.getState().prefillTemplate(it.template || it.question, it.slots ?? {}, vocab);
    setOpen(false);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        aria-label="template library"
        title="template library — prompt shapes the engine answers well"
        data-testid="template-library-button"
        className="flex items-center text-text-dim hover:text-cyan"
        onClick={() => setOpen((o) => !o)}
      >
        <LibraryIcon />
      </button>
      {open && (
        <div
          data-testid="template-library"
          className="absolute right-0 top-7 z-30 max-h-[460px] w-[26rem] overflow-y-auto rounded-panel border border-line bg-bg-1 p-2 shadow-lg"
        >
          <div className="px-2 pb-1 font-mono text-11 uppercase tracking-wider text-text-faint">
            templates
          </div>
          {groups.length === 0 ? (
            <div className="px-2 py-3 font-sans text-12 text-text-dim">
              {q.isLoading ? 'loading…' : 'no templates'}
            </div>
          ) : (
            groups.map(([category, rows]) => (
              <div key={category} className="mt-1.5">
                <div className="px-2 font-mono text-11 uppercase tracking-wider text-text-faint">
                  {category.replace(/_/g, ' ')}
                </div>
                {rows.map((it) => (
                  <button
                    key={it.id}
                    data-testid={`template-row-${it.id}`}
                    onClick={() => choose(it)}
                    className="mt-1 w-full rounded-chip border border-line px-2 py-1.5 text-left font-sans text-12 text-text-dim hover:border-cyan hover:text-text"
                  >
                    <TemplateText text={it.template || it.question} />
                  </button>
                ))}
              </div>
            ))
          )}
          <div className="mt-2 px-2 pb-1 font-mono text-11 text-text-faint">
            choosing one fills the ask box — edit the blanks, then press enter
          </div>
        </div>
      )}
    </div>
  );
}

/** The authored wording with its `{slots}` as chips, so a row reads as a form rather than a broken sentence. */
function TemplateText({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\{\w+\})/g).map((part, i) =>
        /^\{\w+\}$/.test(part) ? (
          <span key={i} className="rounded-chip bg-bg-2 px-1 font-mono text-11 text-cyan">
            {part.slice(1, -1)}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

function LibraryIcon() {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" role="img" aria-hidden="true">
      <path
        d="M4 5h6v14H4zM14 5h6v14h-6M14 9h6M14 15h6"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
