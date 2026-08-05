import type { Meta, StoryObj } from '@storybook/react';
import { useState } from 'react';
import { CommandBar } from './CommandBar';

const meta: Meta<typeof CommandBar> = { title: 'Shell/CommandBar', component: CommandBar };
export default meta;

export const Default: StoryObj<typeof CommandBar> = {
  render: () => {
    const [v, setV] = useState('');
    return (
      <div className="w-[560px]">
        <CommandBar value={v} onChange={setV} onSubmit={(x) => alert(`submit: ${x}`)} disabled={false} />
        <div className="mt-2 font-mono text-11 text-text-dim">value: {v || '—'}</div>
      </div>
    );
  },
};
