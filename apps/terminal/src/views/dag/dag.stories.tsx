import type { Meta, StoryObj } from '@storybook/react';
import { MOCK_GRAPH, MOCK_REGIMES } from '@/api/mock';
import { CascadeDAG } from './CascadeDAG';
import { ConvexityGauge } from './ConvexityGauge';

const dagMeta: Meta<typeof CascadeDAG> = { title: 'Answer/CascadeDAG', component: CascadeDAG };
export default dagMeta;

export const Fired: StoryObj<typeof CascadeDAG> = {
  args: {
    topo: MOCK_GRAPH,
    firedRegimes: [{ matched: ['frost', 'low_stocks'] }],
    drivers: ['frost', 'low_stocks'],
  },
};

export const Dormant: StoryObj<typeof CascadeDAG> = { args: { topo: MOCK_GRAPH } };

export const Gauge: StoryObj<typeof ConvexityGauge> = {
  render: () => (
    <div className="flex gap-3">
      <ConvexityGauge regime={MOCK_REGIMES.regimes[0]!} />
      <ConvexityGauge regime={MOCK_REGIMES.regimes[1]!} />
    </div>
  ),
};
