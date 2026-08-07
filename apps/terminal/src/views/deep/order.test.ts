import { describe, expect, it } from 'vitest';
import type { components } from '@/api/types.gen';
import { activeDriverIds, firedRegimeOverlay, orderDrivers, orderRegimes, recentEvents } from './order';

type Driver = components['schemas']['DriverSignal'];
type Card = components['schemas']['RegimeCard'];
type Ev = components['schemas']['EventItem'];

const drv = (over: Partial<Driver>): Driver => ({
  id: 'd',
  live: false,
  verdict: null,
  z: null,
  value: null,
  unit: '',
  ref: null,
  knowledge_date: '',
  ...over,
});
const card = (over: Partial<Card>): Card => ({
  name: 'r',
  direction: '+',
  matched: [],
  threshold: 2,
  fired: false,
  n_active: 0,
  proximity: 0,
  ...over,
});
const ev = (over: Partial<Ev>): Ev => ({
  source: 's',
  title: 't',
  summary: '',
  url: '',
  date: '2021-01-01',
  ...over,
});

describe('orderDrivers', () => {
  it('live before dormant, then |z| desc', () => {
    const out = orderDrivers([
      drv({ id: 'dormant', live: false, z: 3 }),
      drv({ id: 'quiet', live: true, z: 0.1 }),
      drv({ id: 'loud', live: true, z: -2.4 }),
    ]);
    expect(out.map((d) => d.id)).toEqual(['loud', 'quiet', 'dormant']);
  });
});

describe('firedRegimeOverlay / activeDriverIds / orderRegimes', () => {
  it('overlay keeps only fired regimes with their matched drivers', () => {
    const out = firedRegimeOverlay([
      card({ fired: true, matched: ['frost'] }),
      card({ fired: false, matched: ['x'] }),
    ]);
    expect(out).toEqual([{ matched: ['frost'] }]);
  });
  it('active drivers are the live ids only', () => {
    expect(activeDriverIds([drv({ id: 'a', live: true }), drv({ id: 'b', live: false })])).toEqual(['a']);
  });
  it('regimes sort fired first then proximity desc', () => {
    const out = orderRegimes([
      card({ name: 'warm', proximity: 0.5 }),
      card({ name: 'fired', fired: true, proximity: 0.1 }),
      card({ name: 'cool', proximity: 0.2 }),
    ]);
    expect(out.map((r) => r.name)).toEqual(['fired', 'warm', 'cool']);
  });
});

describe('recentEvents', () => {
  it('sorts newest-first and caps', () => {
    const out = recentEvents(
      [ev({ date: '2021-01-01' }), ev({ date: '2021-03-01' }), ev({ date: '2021-02-01' })],
      2,
    );
    expect(out.map((e) => e.date)).toEqual(['2021-03-01', '2021-02-01']);
  });
});
