import { describe, expect, it } from 'vitest';
import { newThreadId, useThread } from './thread';

describe('newThreadId', () => {
  it('is prefixed and unique', () => {
    const a = newThreadId();
    const b = newThreadId();
    expect(a).toMatch(/^t-[a-z0-9]+$/i);
    expect(a).not.toBe(b);
  });
});

describe('useThread store', () => {
  it('setTitleIfEmpty only sets the first time', () => {
    useThread.setState({ threadId: 't-x', title: null });
    useThread.getState().setTitleIfEmpty('first question');
    expect(useThread.getState().title).toBe('first question');
    useThread.getState().setTitleIfEmpty('second question');
    expect(useThread.getState().title).toBe('first question'); // unchanged
  });

  it('newThread resets id + title', () => {
    useThread.setState({ threadId: 't-x', title: 'old' });
    const before = useThread.getState().threadId;
    useThread.getState().newThread();
    expect(useThread.getState().title).toBeNull();
    expect(useThread.getState().threadId).not.toBe(before);
  });

  it('openThread sets id + title', () => {
    useThread.getState().openThread('t-saved', 'saved thread');
    expect(useThread.getState().threadId).toBe('t-saved');
    expect(useThread.getState().title).toBe('saved thread');
  });
});
