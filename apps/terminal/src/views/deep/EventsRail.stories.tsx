import type { Meta, StoryObj } from '@storybook/react';
import { MOCK_EVENTS } from '@/api/mock';
import { EventsRail } from './EventsRail';

const meta: Meta<typeof EventsRail> = {
  title: 'DeepDive/EventsRail',
  component: EventsRail,
  args: { feed: MOCK_EVENTS },
};
export default meta;

export const Default: StoryObj<typeof EventsRail> = {};

export const Empty: StoryObj<typeof EventsRail> = {
  args: { feed: { ...MOCK_EVENTS, events: [] } },
};
