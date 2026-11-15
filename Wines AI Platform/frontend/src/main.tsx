import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { USE_MOCKS } from "./lib/constants";
import "./styles/globals.css";

async function boot() {
  // The worker has to be listening before the first request leaves, or the age-gate
  // probe races it and the app decides the backend is unreachable.
  if (USE_MOCKS) {
    const { startMocks } = await import("./mocks/browser");
    await startMocks();
  }
  createRoot(document.getElementById("root") as HTMLElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void boot();
