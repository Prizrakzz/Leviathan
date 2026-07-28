import { memo, useMemo, useRef, useState, type ReactNode } from 'react';
import { hasFindings, type Findings } from '@/api/partials';
import { useAutoScroll } from '@/shell/useAutoScroll';

/**
 * F7 — the LIVE FINDINGS FEED.
 *
 * A hybrid turn is 40–49s warm and a reasoning turn 60–67s, of which synthesis alone is 24–50s. Everything
 * before the writer starts — dispatch, the cascade walk, the regime probes, the quantify seam, the chain
 * hops — is finished, correct, and today completely invisible: time-to-first-substance is ~156s at p95.
 * This renders that work as it lands, so the wait becomes the answer arriving rather than a progress bar.
 *
 * Every row is DETERMINISTIC ENGINE OUTPUT (slugs, table names, numbers, dates) — never LLM prose, never a
 * model estimate — which is why a finding needs no verifier reconciliation and can be trusted the instant
 * it appears. An engine cannot fabricate its own firing.
 *
 * Jank rules this file obeys:
 *   - Rows APPEND at the bottom of their own scroll box; nothing above ever reflows.
 *   - The box is height-CAPPED, so an 8-regime turn moves the page exactly as much as a 1-regime turn.
 *   - On `drafting` the feed COLLAPSES (an animated grid-rows transition, not a disappearance) into a
 *     one-line summary that stays with the answer — the findings are provenance the analyst may want back,
 *     one click away, for the whole life of the turn.
 *   - Only opacity/transform animate on row entry; motion is opt-out via the global
 *     `prefers-reduced-motion` rule in styles/global.css plus the explicit rules for these classes.
 *   - No findings (an older server that emits no partials) → renders NOTHING, and the view is as it was.
 */

type FeedProps = {
  /** The live turn's accumulated findings (TurnState extends Findings). Partial + defensive: a turn
   *  restored from an older state shape has none of these keys, and must render as if there were none. */
  findings: Partial<Findings>;
};

type Row = { key: string; seq: number; kind: string; head: ReactNode; sub?: ReactNode };

const KIND_CLASS: Record<string, string> = {
  plan: 'text-text-dim',
  walk: 'text-text-dim',
  regime: 'text-amber',
  number: 'text-cyan',
  chain: 'text-amber',
  evidence: 'text-text-dim',
};

/**
 * Direction is engine vocabulary, and the engines speak two dialects: the firing rules emit a SIGN
 * (`+`/`-`, what `fired_regimes[].direction` carries) while some map rows carry a word (`bullish`).
 * Both normalise to one scannable mark; an unrecognised token is shown verbatim rather than guessed at.
 */
function directionMark(d: string): { text: string; cls: string } | null {
  const t = d.trim();
  if (!t) return null;
  if (/^\+|^(bull|up|tight|higher|positive)/i.test(t)) return { text: '▲', cls: 'text-pos' };
  if (/^-|^(bear|down|loose|lower|negative)/i.test(t)) return { text: '▼', cls: 'text-neg' };
  return { text: t, cls: 'text-text-dim' };
}

const slug = (s: string) => s.replace(/_/g, ' ');

function fmtValue(v: number | string): string {
  return typeof v === 'number' ? String(v) : v;
}

/** Build the chronological row list. Sorted by ARRIVAL (`seq`), so the feed reads as a log of what the
 *  engines decided, in the order they decided it; an upserted row keeps its original slot (no reorder). */
function buildRows(f: Partial<Findings>): Row[] {
  const rows: Row[] = [];
  if (f.plan)
    rows.push({
      key: 'plan',
      seq: f.plan.seq,
      kind: 'plan',
      head: (
        <>
          <span className="text-text">{f.plan.intent}</span>
          {f.plan.contracts.length > 0 && (
            <span className="text-text-dim"> · {f.plan.contracts.map(slug).join(', ')}</span>
          )}
        </>
      ),
    });
  if (f.walk)
    rows.push({
      key: 'walk',
      seq: f.walk.seq,
      kind: 'walk',
      head: (
        <span className="text-text-dim">
          <span className="text-text">{f.walk.nodes}</span> nodes · depth{' '}
          <span className="text-text">{f.walk.depth}</span>
        </span>
      ),
    });
  for (const r of f.regimes ?? []) {
    // A verbatim (unrecognised) direction is dropped when the slug already says it — `bullish_supply_squeeze
    // bullish` reads as a stutter. The ▲/▼ mark is never dropped: it is what makes a column of regimes scan.
    const dir = directionMark(r.direction);
    const showDir =
      dir && (dir.text === '▲' || dir.text === '▼' || !r.regime.toLowerCase().includes(dir.text.toLowerCase()));
    rows.push({
      key: `regime:${r.key}`,
      seq: r.seq,
      kind: 'regime',
      head: (
        <>
          {showDir && dir && <span className={`${dir.cls} mr-1`}>{dir.text}</span>}
          <span className="text-text">{slug(r.regime)}</span>
          <span className="text-text-faint"> · {slug(r.contract)}</span>
        </>
      ),
      // The dated basis is the whole point: a regime the user can date is a regime the user can check.
      sub: r.basis.length > 0 && (
        <>
          {r.basis.map((b, i) => (
            <span key={b.driver}>
              {i > 0 && <span className="text-text-faint"> · </span>}
              {slug(b.driver)}
              {b.date && <span className="text-text-faint"> {b.date}</span>}
              {b.source && <span className="text-text-faint"> ({slug(b.source)})</span>}
            </span>
          ))}
        </>
      ),
    });
  }
  for (const n of f.numbers ?? [])
    rows.push({
      key: `number:${n.key}`,
      seq: n.seq,
      kind: 'number',
      head: (
        <>
          <span className="text-text-dim">{slug(n.metric)}</span>{' '}
          <span className="text-text" data-numeric>
            {fmtValue(n.value)}
          </span>
          {n.unit && <span className="text-text-dim"> {n.unit}</span>}
          <span className="text-text-faint">
            {' '}
            · {n.table}
            {n.asof && ` · as of ${n.asof}`}
          </span>
        </>
      ),
    });
  for (const c of f.chains ?? [])
    rows.push({
      key: `chain:${c.key}`,
      seq: c.seq,
      kind: 'chain',
      head: (
        <>
          <span className="text-text">{c.hops.map(slug).join(' → ')}</span>
          <span className="text-text-faint"> · {c.chain_id}</span>
        </>
      ),
    });
  for (const e of f.evidence ?? [])
    rows.push({
      key: `evidence:${e.key}`,
      seq: e.seq,
      kind: 'evidence',
      head: (
        <span className="text-text-dim">
          <span className="text-text">{e.kept}</span> kept · {slug(e.node)}
        </span>
      ),
    });
  return rows.sort((a, b) => a.seq - b.seq);
}

/** The one-line summary the collapsed feed keeps on screen (and the expanded feed's header). */
function summary(f: Partial<Findings>, rowCount: number): string {
  const bits: string[] = [];
  const n = (x: number, one: string, many = `${one}s`) => `${x} ${x === 1 ? one : many}`;
  if (f.regimes?.length) bits.push(n(f.regimes.length, 'regime'));
  if (f.numbers?.length) bits.push(n(f.numbers.length, 'number'));
  if (f.chains?.length) bits.push(n(f.chains.length, 'chain'));
  if (f.keptTotal) bits.push(`${f.keptTotal} props kept`);
  if (!bits.length) bits.push(n(rowCount, 'finding'));
  return bits.join(' · ');
}

function FindingsFeedInner({ findings }: FeedProps) {
  // Hooks first: this component returns null for the no-partials path, and hook order must not depend on it.
  const [pin, setPin] = useState<boolean | null>(null); // null = follow the phase; true/false = user's choice
  const scrollRef = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => buildRows(findings), [findings]);
  useAutoScroll(scrollRef, rows.length);

  if (!hasFindings(findings)) return null; // older server, no partials → the view is exactly as it was

  const phase = findings.phase ?? 'idle';
  const drafting = phase === 'drafting' || phase === 'verified';
  const open = pin ?? !drafting; // expanded while the engines work; collapses when the writer takes over
  const strips = findings.strips;

  return (
    <section
      className="rounded-panel border border-line bg-bg-1"
      data-testid="findings-feed"
      data-phase={phase}
      data-open={open}
      aria-label="live findings"
    >
      <button
        type="button"
        onClick={() => setPin(!open)}
        aria-expanded={open}
        data-testid="findings-toggle"
        className="flex w-full items-baseline gap-2 px-3 py-2 text-left font-mono text-11 hover:bg-bg-2"
      >
        <span className={`transition-transform duration-hover ${open ? 'rotate-90' : ''} text-text-faint`}>▸</span>
        <span className="uppercase tracking-wider text-text-dim">findings</span>
        <span className="flex-1 truncate text-text-faint" data-testid="findings-summary">
          {summary(findings, rows.length)}
        </span>
        {/* The verifier's own number, shown only once it is real — the count of unbacked citations removed. */}
        {strips != null && (
          <span className="text-text-faint" data-testid="findings-strips">
            {strips} stripped
          </span>
        )}
      </button>

      {/* grid-rows 1fr↔0fr: a height transition that needs no measured pixel height, so it can never
          fight the content it is animating (the classic max-height jank). */}
      <div
        className="grid transition-[grid-template-rows] duration-panel ease-out motion-reduce:transition-none"
        style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div
            ref={scrollRef}
            data-testid="findings-rows"
            role="log"
            aria-live="polite"
            aria-relevant="additions"
            // Collapsed rows stay MOUNTED (the analyst reopens them) but leave the a11y tree: a screen
            // reader should not read 30 clipped rows, nor keep announcing into a closed disclosure.
            aria-hidden={!open}
            // Capped + scrollable: the page moves the same amount whether 3 findings land or 30.
            className="max-h-64 overflow-y-auto border-t border-line px-3 py-2 font-mono text-11 leading-relaxed"
          >
            {rows.map((r) => (
              <div key={r.key} className="lv-finding flex items-baseline gap-2 py-0.5" data-testid="finding-row" data-kind={r.kind}>
                <span className={`inline-block w-16 shrink-0 ${KIND_CLASS[r.kind] ?? 'text-text-dim'}`}>{r.kind}</span>
                {/* Row height must stay BOUNDED at every width. The label column is a fixed w-16, so on a
                    narrow panel the value gets a very thin column and long content (a regime basis, a chain's
                    hops) wraps into a wall of text: measured in a real browser at a 375px viewport, single
                    findings rendered 1738px and 1023px tall, 5091px of content inside a 240px scroll box.
                    jsdom has no layout engine (every height is 0), so the unit-test jank gates cannot see
                    this class of defect at all. line-clamp bounds each part to 2 lines; on desktop nothing
                    changes (rows already measure 22px, the two-line regime row 40px), and the full text
                    stays in the DOM for the a11y tree and for tests. */}
                <span className="min-w-0 flex-1 break-words">
                  <span className="line-clamp-2">{r.head}</span>
                  {r.sub && <div className="line-clamp-2 text-text-dim">{r.sub}</div>}
                </span>
              </div>
            ))}
            {/* Reserve a little room while the engines are still reporting, so the next row lands in space
                that already exists instead of pushing the layout down a line at a time. */}
            {!drafting && <div aria-hidden="true" className="h-8" />}
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * MEMOISED, and load-bearing. Findings ride the SAME turn object as the synthesis draft, so `findings`
 * takes a NEW identity on every `token` delta — thousands of them across a 24-50s synthesis, every one of
 * them arriving while the typewriter needs frames. Measured before this wrapper: 400 token deltas
 * committed the feed 400 times and rebuilt all 54 rows each time (~780ms of pure waste in jsdom, for a
 * feed whose content had not changed).
 *
 * The reducer returns the SAME array reference when a partial moves nothing, and a NEW one the instant a
 * finding lands, so reference equality over the findings fields is both exact and O(1): the feed now
 * commits only when the engines actually decided something.
 */
export const FindingsFeed = memo(FindingsFeedInner, (a, b) => {
  const x = a.findings;
  const y = b.findings;
  return (
    x.phase === y.phase &&
    x.plan === y.plan &&
    x.walk === y.walk &&
    x.regimes === y.regimes &&
    x.numbers === y.numbers &&
    x.chains === y.chains &&
    x.evidence === y.evidence &&
    x.keptTotal === y.keptTotal &&
    x.strips === y.strips
  );
});
