import type { Meta, StoryObj } from '@storybook/react';
import { useState } from 'react';
import { TopBar } from './TopBar';

const meta: Meta<typeof TopBar> = { title: 'Shell/TopBar', component: TopBar };
export default meta;

export const Default: StoryObj<typeof TopBar> = {
  render: () => {
    const [cmd, setCmd] = useState('KC frost 2021');
    return (
      <div className="w-[900px]">
        <TopBar cmd={cmd} setCmd={setCmd} onSubmit={() => {}} streaming={false} />
      </div>
    );
  },
};
