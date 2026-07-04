import type { Meta, StoryObj } from '@storybook/react';
import { Mark } from './Mark';

const meta: Meta<typeof Mark> = { title: 'Tokens/Mark', component: Mark };
export default meta;

export const Amber: StoryObj<typeof Mark> = {
  args: { size: 64 },
  render: (args) => (
    <div className="text-amber">
      <Mark {...args} />
    </div>
  ),
};

export const Dim: StoryObj<typeof Mark> = {
  args: { size: 64 },
  render: (args) => (
    <div className="text-text-faint">
      <Mark {...args} />
    </div>
  ),
};
