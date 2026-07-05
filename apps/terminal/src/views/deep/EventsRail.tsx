import type { components } from '@/api/types.gen';
import { recentEvents } from './order';

type EventsFeed = components['schemas']['EventsFeed'];

/** The live event rail (design §3.2 / §4.7) — recent trusted-source items for the contract. Point-in-time:
 *  the backend only returns events dated ≤ the as-of. */
export function EventsRail({ feed }: { feed: EventsFeed }) {
  const events = recentEvents(feed.events ?? []);
  return (
    <div className="rounded-panel border border-line bg-bg-1 p-2" data-testid="events">
      <div className="mb-1 flex items-center justify-between font-mono text-11">
        <span className="uppercase tracking-wider text-text-dim">Events</span>
        <span className={feed.live ? 'text-live' : 'text-text-faint'}>
          {feed.live ? 'live' : `as of ${feed.asof}`}
        </span>
      </div>
      {events.length === 0 ? (
        <div className="font-mono text-12 text-text-faint">no events at {feed.asof}.</div>
      ) : (
        <ul className="space-y-1.5">
          {events.map((e, i) => (
            <li key={i} className="font-mono text-12">
              <div className="flex items-baseline gap-2">
                <span className="shrink-0 tabular-nums text-text-faint">{e.date}</span>
                {e.url ? (
                  <a
                    href={e.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-cyan hover:underline"
                  >
                    {e.title}
                  </a>
                ) : (
                  <span className="text-text">{e.title}</span>
                )}
              </div>
              {e.summary ? <div className="mt-0.5 font-sans text-12 text-text-dim">{e.summary}</div> : null}
              <div className="text-11 text-text-faint">
                {e.source}
                {e.driver_id ? ` · ${e.driver_id}` : ''}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
