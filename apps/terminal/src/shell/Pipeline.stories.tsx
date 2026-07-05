import type { Meta, StoryObj } from '@storybook/react';
import type { StampedStage } from '@/api/useTurn';
import { Pipeline } from './Pipeline';

const t0 = 0;
const STREAMING: StampedStage[] = [
  { stage: 'planning', intent: 'hybrid', contracts: ['arabica_coffee'], ts: t0 },
  { stage: 'walking', ts: t0 + 400 },
  { stage: 'retrieving', done: 3, total: 7, ts: t0 + 2600 },
  { stage: 'numbers', calls: 1, running: true, table: 'silver_psd', ts: t0 + 3100 },
];
const DONE: StampedStage[] = [
  ...STREAMING,
  { stage: 'walking', nodes: 7, regimes: 2, ts: t0 + 5200 },
  { stage: 'retrieving', props: 24, ts: t0 + 5300 },
  { stage: 'numbers', calls: 2, ts: t0 + 6100 },
  { stage: 'synthesizing', ts: t0 + 6400 },
  { stage: 'verifying', checked: 4, stripped: 0, ts: t0 + 21100 },
];

const meta: Meta<typeof Pipeline> = { title: 'Shell/Pipeline', component: Pipeline };
export default meta;

export const Streaming: StoryObj<typeof Pipeline> = { args: { stages: STREAMING, done: false } };
export const Complete: StoryObj<typeof Pipeline> = { args: { stages: DONE, done: true } };
