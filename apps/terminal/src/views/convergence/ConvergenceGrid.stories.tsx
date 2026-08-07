import type { Meta, StoryObj } from '@storybook/react';
import type { components } from '@/api/types.gen';
import { ConvergenceGrid } from './ConvergenceGrid';

type Row = components['schemas']['ConvergenceRow'];
type Card = components['schemas']['RegimeCard'];

const rc = (over: Partial<Card>): Card => ({
  name: 'regime',
  direction: '+',
  matched: [],
  threshold: 2,
  fired: false,
  n_active: 0,
  proximity: 0,
  ...over,
});

const ROWS: Row[] = [
  {
    contract: 'arabica_coffee',
    drivers: [],
    regimes: [
      rc({ name: 'bullish_supply_squeeze', direction: '+', threshold: 2, n_active: 2, fired: true, proximity: 1 }),
      rc({ name: 'demand_led_tightening', direction: '+', threshold: 2, n_active: 1, proximity: 0.5 }),
    ],
  },
  {
    contract: 'raw_sugar',
    drivers: [],
    regimes: [
      rc({ name: 'ethanol_pull', direction: '+', threshold: 3, n_active: 2, proximity: 0.66 }),
      rc({ name: 'monsoon_shortfall', direction: '+', threshold: 2, n_active: 1, proximity: 0.4 }),
    ],
  },
  {
    contract: 'corn',
    drivers: [],
    regimes: [
      rc({ name: 'export_glut', direction: '-', threshold: 2, n_active: 1, proximity: 0.3 }),
      rc({ name: 'drought_stress', direction: '+', threshold: 3, n_active: 0, proximity: 0.05 }),
    ],
  },
  {
    contract: 'chicago_wheat',
    drivers: [],
    regimes: [rc({ name: 'black_sea_risk', direction: '+', threshold: 2, n_active: 0, proximity: 0.1 })],
  },
];

const meta: Meta<typeof ConvergenceGrid> = {
  title: 'Convergence/Grid',
  component: ConvergenceGrid,
  args: { rows: ROWS, asof: '2021-07-20', onPick: () => {} },
};
export default meta;

export const Default: StoryObj<typeof ConvergenceGrid> = {};

export const Empty: StoryObj<typeof ConvergenceGrid> = { args: { rows: [] } };
