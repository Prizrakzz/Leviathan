import type { Meta, StoryObj } from '@storybook/react';
import { MOCK_REGIMES } from '@/api/mock';
import { DriverSignals } from './DriverSignals';

const meta: Meta<typeof DriverSignals> = {
  title: 'DeepDive/DriverSignals',
  component: DriverSignals,
  args: { drivers: MOCK_REGIMES.drivers },
};
export default meta;

export const Default: StoryObj<typeof DriverSignals> = {};
