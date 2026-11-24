/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** REST API base URL, default http://localhost:8000/v2. */
  readonly VITE_API_BASE?: string;
  /** "1" serves the contract fixtures in the browser instead of calling the API. */
  readonly VITE_MOCK?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
