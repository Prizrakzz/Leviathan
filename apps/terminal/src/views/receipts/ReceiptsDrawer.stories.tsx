import type { Meta, StoryObj } from '@storybook/react';
import { MOCK_RESULT } from '@/api/mock';
import { ReceiptsDrawer } from './ReceiptsDrawer';

const meta: Meta<typeof ReceiptsDrawer> = {
  title: 'Answer/ReceiptsDrawer',
  component: ReceiptsDrawer,
  args: { result: MOCK_RESULT, open: true, onClose: () => {} },
  parameters: { layout: 'fullscreen' },
};
export default meta;

export const Open: StoryObj<typeof ReceiptsDrawer> = {};
