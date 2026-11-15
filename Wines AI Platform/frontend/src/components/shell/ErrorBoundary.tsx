import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";

interface State {
  error: Error | null;
}

/** NFR-7's client half: no stack trace reaches a user. The message is fixed, the
 *  detail goes to the console for whoever is debugging. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[wines-ai] render failed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="flex min-h-dvh items-center justify-center bg-canvas px-4">
        <div className="max-w-md rounded-card border border-line bg-surface p-6 text-center shadow-pop">
          <h1 className="text-lg font-semibold text-ink">Something went wrong</h1>
          <p className="mt-2 text-why text-muted">
            The page could not be rendered. Reloading usually clears it; nothing you typed is
            lost from the conversation.
          </p>
          <Button variant="primary" className="mt-5" onClick={() => window.location.reload()}>
            Reload
          </Button>
        </div>
      </main>
    );
  }
}
