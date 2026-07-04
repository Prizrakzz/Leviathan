import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Preview } from '@storybook/react';
import React, { useEffect } from 'react';
import { injectTokens } from '../src/tokens/tokens';
import '../src/styles/global.css';

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

// Every story renders on the terminal's near-black canvas with the design tokens injected + a QueryClient
// (react-query components render standalone) — reviewed in the real skin, never a default Storybook white.
const withProviders = (Story: React.ComponentType) => {
  useEffect(() => injectTokens(document.documentElement), []);
  return (
    <QueryClientProvider client={qc}>
      <div className="min-h-screen bg-bg-0 text-text font-sans" style={{ padding: 24 }}>
        <Story />
      </div>
    </QueryClientProvider>
  );
};

const preview: Preview = {
  parameters: {
    backgrounds: { disable: true },
    controls: { matchers: { color: /(?:background|color)$/i, date: /Date$/i } },
  },
  decorators: [withProviders],
};
export default preview;
