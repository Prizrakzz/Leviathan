import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { Landing } from './Landing';

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Landing />
    </MemoryRouter>,
  );
}

describe('Landing sign-in note (D-TW-7)', () => {
  it('explains the bounce when TerminalGate sent the user here with ?signin=1', () => {
    at('/?signin=1');
    expect(screen.getByTestId('signin-note')).toHaveTextContent('please sign in to continue');
  });

  it('stays clean on a direct visit — the note is a consequence, not decoration', () => {
    at('/');
    expect(screen.queryByTestId('signin-note')).toBeNull();
  });
});
