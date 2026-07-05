/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_MOCK?: string;
  // Stage 4 Cognito + Google sign-in (absent -> auth disabled, /app open for local/mock).
  readonly VITE_COGNITO_AUTHORITY?: string;
  readonly VITE_COGNITO_CLIENT_ID?: string;
  readonly VITE_COGNITO_REDIRECT_URI?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
