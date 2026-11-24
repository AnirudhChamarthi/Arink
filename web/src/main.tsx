import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createHttpApi, DEFAULT_API_BASE, type RiskbotApi } from "./api/client";
import "./styles.css";

async function chooseApi(): Promise<RiskbotApi> {
  if (import.meta.env.VITE_MOCK === "1" || import.meta.env.VITE_MOCK === "true") {
    // Loaded only in mock builds, so the fixtures stay out of the production bundle.
    const { createMockApi } = await import("./mocks/mockApi");
    return createMockApi();
  }
  return createHttpApi(import.meta.env.VITE_API_BASE || DEFAULT_API_BASE);
}

chooseApi().then((api) => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App api={api} />
    </StrictMode>,
  );
});
