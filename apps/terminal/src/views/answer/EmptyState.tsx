import { useQuery } from '@tanstack/react-query';
import { getGallery, type GalleryItem } from '@/api/client';
import { Composer } from '@/shell/Composer';
import { useSession } from '@/store/session';

/** D-AM-16 — the starters now come from the deterministic prompt gallery (GET /v1/gallery: authored
 *  templates filled server-side from the warm convergence catalog) instead of four frozen strings and a
 *  per-landing /v1/suggest call. Both of the things it replaces were wrong for this surface: the frozen
 *  strings named markets the book may no longer track, and the suggester spends a model call plus a slot of
 *  the daily suggest quota to produce a landing page nobody has asked a question on yet. The gallery is
 *  free, reproducible, and answerable-by-construction (its slots only ever carry tracked contracts, live
 *  near-firing regimes, and census-realizable pairs). The suggester keeps its real job: follow-ups under a
 *  finished answer, where the last turn is what makes it worth the spend. */

/** Round-robin clamp. BREADTH FIRST — one starter from every category before any category gets a second —
 *  so growing the yaml can never let one category crowd the landing page, and the reader always sees the
 *  full range of question SHAPES the engine answers well. (SuggestionChips clamps its row to 3 for the same
 *  reason; the numbers differ because that row sits under an answer and this one IS the page.) */
const PER_CATEGORY = 2;
const MAX_STARTERS = 8;

/** Category order is the SERVER's (gallery.yaml file order), never sorted here: the authored order is a
 *  curation decision and the file is where it is reviewed. Exported for the test. */
export function pickStarters(items: GalleryItem[], max = MAX_STARTERS): [string, GalleryItem[]][] {
  const byCat = new Map<string, GalleryItem[]>();
  // An unfilled entry still carries its `{slot}` blanks (cold catalog). It is legible, but a starter CLICK
  // submits the question as-is, so offering one would fire a turn on a literal placeholder — drop them.
  for (const it of items.filter((i) => i.filled !== false)) {
    const bucket = byCat.get(it.category);
    if (bucket) bucket.push(it);
    else byCat.set(it.category, [it]);
  }
  const picked = new Map<string, GalleryItem[]>();
  let n = 0;
  for (let round = 0; round < PER_CATEGORY && n < max; round++) {
    for (const [cat, bucket] of byCat) {
      if (n >= max) break;
      const it = bucket[round];
      if (!it) continue;
      const out = picked.get(cat);
      if (out) out.push(it);
      else picked.set(cat, [it]);
      n++;
    }
  }
  return [...picked];
}

/** The new-thread landing (5.6 W4): a centered hero composer + starter prompts, ChatGPT-style,
 *  so the first thing a user sees is WHERE TO TYPE — not an empty panel. */
export function EmptyState({ onAsk }: { onAsk: (q: string) => void }) {
  const ready = useSession((s) => s.ready);
  const galleryQ = useQuery({
    queryKey: ['gallery'],
    queryFn: getGallery,
    enabled: ready,
    staleTime: 900_000, // the convergence warmer behind it re-fires every 900s; refetching faster buys nothing
  });
  // No local fallback list: while this loads (or if it fails) the starter row renders NOTHING rather than
  // four hardcoded questions the book may not be able to answer. The hero and the composer are what keep
  // the page from being empty — chips are a nicety, never an error state (the SuggestionChips doctrine).
  const groups = pickStarters(galleryQ.data?.items ?? []);
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 p-8" data-testid="empty-state">
      <div className="text-center">
        <div className="font-mono text-11 uppercase tracking-wider text-text-dim">leviathan terminal</div>
        <div className="mt-1 font-sans text-18 font-semibold text-text">
          ask a fundamental-convexity question
        </div>
      </div>
      <Composer onSubmit={onAsk} streaming={false} hero />
      {groups.length > 0 && (
        <div
          className="grid w-full max-w-3xl gap-x-6 gap-y-4 sm:grid-cols-2"
          data-testid="prompt-gallery"
        >
          {groups.map(([category, items]) => (
            <div key={category}>
              <div className="font-mono text-11 uppercase tracking-wider text-text-faint">
                {category.replace(/_/g, ' ')}
              </div>
              <div className="mt-1.5 flex flex-col gap-1.5">
                {items.map((it) => (
                  <button
                    key={it.id}
                    onClick={() => onAsk(it.question)}
                    className="rounded-chip border border-line px-2.5 py-1 text-left font-sans text-12 text-text-dim hover:border-cyan hover:text-text"
                  >
                    {it.question}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
