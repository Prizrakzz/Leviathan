import type { Meta, StoryObj } from '@storybook/react';
import { Shell } from './Shell';

const meta: Meta<typeof Shell> = {
  title: 'Shell/Shell',
  component: Shell,
  parameters: { layout: 'fullscreen' },
};
export default meta;

export const Default: StoryObj<typeof Shell> = {
  render: () => (
    <div style={{ height: '600px' }}>
      <Shell />
    </div>
  ),
};
