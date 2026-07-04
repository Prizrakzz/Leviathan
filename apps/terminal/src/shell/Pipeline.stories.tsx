import type { Meta, StoryObj } from '@storybook/react';
import type { StageEvent } from '@/api/schema';
import { Pipeline } from './Pipeline';

const STREAMING: StageEvent[] = [
  { stage: 'planning', intent: 'hybrid', contracts: ['arabica_coffee'] },
  { stage: 'walking', nodes: 7, regimes: 2 },
  { stage: 'retrieving', props: 24 },
];
const DONE: StageEvent[] = [
  ...STREAMING,
  { stage: 'numbers', calls: 2 },
  { stage: 'verifying', checked: 4, stripped: 0 },
];

const meta: Meta<typeof Pipeline> = { title: 'Shell/Pipeline', component: Pipeline };
export default meta;

export const Streaming: StoryObj<typeof Pipeline> = { args: { stages: STREAMING, done: false } };
export const Complete: StoryObj<typeof Pipeline> = { args: { stages: DONE, done: true } };
