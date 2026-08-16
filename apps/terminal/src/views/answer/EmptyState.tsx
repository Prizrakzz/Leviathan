import { useQuery } from '@tanstack/react-query';
import { getGallery, type GalleryItem } from '@/api/client';
import { Composer } from '@/shell/Composer';
import { EMPTY_VOCAB, useCompose } from '@/store/compose';
import { useSession } from '@/store/session';

/** D-AM-16 — the starters now come from the deterministic prompt gallery (GET /v1/gallery: authored
 *  templates filled server-side from the warm convergence catalog) instead of four frozen strings and a
 *  per-landing /v1/suggest call. Both of the things it replaces were wrong for this surface: the frozen
 *  strings named markets the book may no longer track, and the suggester spends a model call plus a slot of
 *  the daily suggest quota to produce a landing page nobody has asked a question on yet. The gallery is
 *  free, reproducible, and answerable-by-construction (its slots only ever carry tracked contracts, live
 *  near-firing regimes, and census-realizable pairs). The suggester keeps its real job: follow-ups under a
 *  finished answer, where the last turn is what makes it worth the spend. */

/** D-SG S1 — THREE starters, one per category. The landing page was a 2-column board of 8 chips under 7
 *  category headings; that reads as a menu to study rather than a question to ask, and the hero composer
 *  (the thing the page exists to point at) lost the eye to it. Three unlabelled chips is the whole surface
 *  now. Round-robin stays BREADTH FIRST — one starter from a category before any category gets a second —
 *  so growing the yaml can never let one category crowd the page. */
const PER_CATEGORY = 1;
const MAX_STARTERS = 3;

/** Days since Jan 1 of the same UTC year. UTC, not local: the gallery's doctrine is that two users on the
 *  same book on the same day see the same gallery (the server fills the slots from one warm matrix per
 *  day), and a local-midnight rotation would break that across zones. Exported for the test. */
export function utcDayOfYear(now: Date = new Date()): number {
  const midnight = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((midnight - Date.UTC(now.getUTCFullYear(), 0, 1)) / 86_400_000);
}

/** Category order is the SERVER's (gallery.yaml file order), never sorted here: the authored order is a
 *  curation decision and the file is where it is reviewed. What DOES move is where the round starts:
 *  clamping to 3 without rotation would freeze the landing page onto the first three categories forever,
 *  so the start offset walks the categories by UTC day. Deterministic by construction — same day, same
 *  three shapes — while the chip TEXT keeps varying with the live warm catalog. Exported for the test. */
export function pickStarters(
  items: GalleryItem[],
  max = MAX_STARTERS,
  day = utcDayOfYear(),
): GalleryItem[] {
  const byCat = new Map<string, GalleryItem[]>();
  // An unfilled entry still carries its `{slot}` blanks (cold catalog). D-UX-1 made the click PREFILL rather
  // than submit, so a blank is no longer a hazard — but this row is a one-glance menu of questions the book
  // can answer today, and a fill-in-the-blank belongs in the top-bar template library (where the slot bar
  // makes the blanks fillable). Unchanged: drop them here.
  for (const it of items.filter((i) => i.filled !== false)) {
    const bucket = byCat.get(it.category);
    if (bucket) bucket.push(it);
    else byCat.set(it.category, [it]);
  }
  const buckets = [...byCat.values()];
  if (!buckets.length) return [];
  const start = ((day % buckets.length) + buckets.length) % buckets.length;
  const picked: GalleryItem[] = [];
  for (let round = 0; round < PER_CATEGORY && picked.length < max; round++) {
    for (let i = 0; i < buckets.length && picked.length < max; i++) {
      const it = buckets[(start + i) % buckets.length]?.[round];
      if (it) picked.push(it);
    }
  }
  return picked;
}

/** The new-thread landing (5.6 W4): a centered hero composer + starter prompts, ChatGPT-style,
 *  so the first thing a user sees is WHERE TO TYPE — not an empty panel. D-UX-1: a starter click PREFILLS
 *  that composer and stops there (`onAsk` is now reached only by pressing Enter in the box). */
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
  const starters = pickStarters(galleryQ.data?.items ?? []);
  const vocab = galleryQ.data?.vocab ?? EMPTY_VOCAB;
  // D-UX-1 REVERTS the click-submits starter. A starter is a DRAFT, not a decision: it lands in the hero
  // composer with its slot bar attached, and the analyst edits the contract (or any word of it) and presses
  // Enter. Same prefill path as the top-bar library, so there is one behaviour to learn and one to test.
  const choose = (it: GalleryItem) =>
    useCompose.getState().prefillTemplate(it.template || it.question, it.slots ?? {}, vocab);
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 p-8" data-testid="empty-state">
      <div className="text-center">
        <div className="font-mono text-11 uppercase tracking-wider text-text-dim">leviathan terminal</div>
        <div className="mt-1 font-sans text-18 font-semibold text-text">
          ask a fundamental-convexity question
        </div>
      </div>
      <Composer onSubmit={onAsk} streaming={false} hero />
      {/* D-SG S1: ONE unlabelled row. With a single starter per category the headings labelled nothing —
          they just told the reader which drawer the question came out of, which is the yaml's concern, not
          the analyst's. The category is still what CHOOSES the three; it is no longer what frames them. */}
      {starters.length > 0 && (
        <div className="flex w-full max-w-3xl flex-wrap justify-center gap-2" data-testid="prompt-gallery">
          {starters.map((it) => (
            <button
              key={it.id}
              onClick={() => choose(it)}
              className="rounded-chip border border-line px-2.5 py-1 text-left font-sans text-12 text-text-dim hover:border-cyan hover:text-text"
            >
              {it.question}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
