import { useState } from 'react';

/** A toggle chip (markets / seat selection) — pressed = accent-outlined. Shared by Settings + Onboarding. */
export function ToggleChip({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`rounded-chip border px-2 py-0.5 font-mono text-11 transition-colors ${
        on ? 'border-cyan bg-bg-2 text-cyan' : 'border-line text-text-dim hover:border-text-faint hover:text-text'
      }`}
    >
      {label}
    </button>
  );
}

/** Free-text add/remove list (regions, notes). Enter adds; each item has an ✕. Capped at 12 to match the
 *  server's fact bound (the extra would be silently dropped by sanitize). */
export function ChipList({
  items,
  onChange,
  placeholder,
}: {
  items: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
}) {
  const [draft, setDraft] = useState('');
  const add = () => {
    const v = draft.trim();
    if (v && !items.includes(v) && items.length < 12) onChange([...items, v]);
    setDraft('');
  };
  return (
    <div>
      {items.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {items.map((it) => (
            <span
              key={it}
              className="flex items-center gap-1 rounded-chip border border-line bg-bg-2 px-2 py-0.5 font-mono text-11 text-text"
            >
              {it}
              <button
                type="button"
                aria-label={`remove ${it}`}
                onClick={() => onChange(items.filter((x) => x !== it))}
                className="text-text-faint hover:text-neg"
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
        placeholder={placeholder}
        maxLength={140}
        className="w-full rounded-chip border border-line bg-bg-0 px-2 py-1 font-mono text-12 text-text placeholder:text-text-faint focus:border-cyan focus:outline-none"
      />
    </div>
  );
}
