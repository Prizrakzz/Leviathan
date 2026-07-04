import type { Meta, StoryObj } from '@storybook/react';
import { MOCK_RESULT } from '@/api/mock';
import { Note } from './Note';

const meta: Meta<typeof Note> = {
  title: 'Answer/Note',
  component: Note,
  args: { result: MOCK_RESULT, onOpenReceipts: () => {} },
};
export default meta;

export const Default: StoryObj<typeof Note> = {};
