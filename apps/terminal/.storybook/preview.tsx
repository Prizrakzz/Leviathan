import type { Preview } from '@storybook/react';
import React, { useEffect } from 'react';
import { injectTokens } from '../src/tokens/tokens';
import '../src/styles/global.css';

// Every story renders on the terminal's near-black canvas with the design tokens injected — components are
// reviewed in the real skin (the anti-vibe-coded discipline), never against a default Storybook white.
const withTokens = (Story: React.ComponentType) => {
  useEffect(() => injectTokens(document.documentElement), []);
  return (
    <div className="min-h-screen bg-bg-0 text-text font-sans" style={{ padding: 24 }}>
      <Story />
    </div>
  );
};

const preview: Preview = {
  parameters: {
    backgrounds: { disable: true },
    controls: { matchers: { color: /(?:background|color)$/i, date: /Date$/i } },
  },
  decorators: [withTokens],
};
export default preview;
