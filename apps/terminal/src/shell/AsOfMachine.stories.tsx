import type { Meta, StoryObj } from '@storybook/react';
import { useEffect } from 'react';
import { useAsOf } from '@/store/asof';
import { AsOfMachine } from './AsOfMachine';

const meta: Meta<typeof AsOfMachine> = { title: 'Shell/AsOfMachine', component: AsOfMachine };
export default meta;

export const Live: StoryObj<typeof AsOfMachine> = {
  render: () => {
    useEffect(() => useAsOf.getState().goLive(), []);
    return <AsOfMachine />;
  },
};

export const Backtest: StoryObj<typeof AsOfMachine> = {
  render: () => {
    useEffect(() => useAsOf.getState().setAsOf('2021-07-20'), []);
    return <AsOfMachine />;
  },
};
