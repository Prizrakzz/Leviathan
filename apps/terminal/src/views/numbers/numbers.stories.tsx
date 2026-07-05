import type { Meta, StoryObj } from '@storybook/react';
import { MOCK_RESULT } from '@/api/mock';
import { Numbers } from './Numbers';

const meta: Meta<typeof Numbers> = {
  title: 'Answer/Numbers',
  component: Numbers,
  args: { calls: MOCK_RESULT.number_calls ?? [], asof: '2021-07-20' },
};
export default meta;

export const Default: StoryObj<typeof Numbers> = {};
