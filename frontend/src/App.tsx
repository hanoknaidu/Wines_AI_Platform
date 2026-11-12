import { BrowserRouter } from "react-router-dom";
import { Providers } from "@/app/providers";
import { Router } from "@/app/router";
import { ErrorBoundary } from "@/components/shell/ErrorBoundary";

export default function App() {
  return (
    <ErrorBoundary>
      <Providers>
        <BrowserRouter>
          <Router />
        </BrowserRouter>
      </Providers>
    </ErrorBoundary>
  );
}
