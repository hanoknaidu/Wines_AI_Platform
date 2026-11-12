import { DatabaseZap } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Wordmark } from "@/components/shell/Wordmark";

/** The one failure where the product cannot answer at all: with no dataset loaded
 *  there is nothing to ground a recommendation in, and the honest move is to say so
 *  rather than to answer from nowhere. Recovers on its own — `useReady` keeps polling. */
export function DatasetUnavailable({ onRetry }: { onRetry?: () => void }) {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-lg">
        <Wordmark className="mb-8" />
        <div className="rounded-card border border-line bg-surface p-6 shadow-pop">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-caution-bg text-caution-fg">
            <DatabaseZap size={18} />
          </span>
          <h1 className="mt-4 text-lg font-semibold text-ink">Recommendations unavailable</h1>
          <p className="mt-2 text-why text-muted">
            The wine dataset is not loaded, so nothing can be recommended from it. Every answer
            here has to trace back to a reviewed row — with no dataset, there is no answer to
            give.
          </p>
          <p className="mt-2 text-why text-subtle">
            This page is checking again every few seconds and will recover on its own.
          </p>
          {onRetry ? (
            <Button variant="secondary" className="mt-5" onClick={onRetry}>
              Check now
            </Button>
          ) : null}
        </div>
      </div>
    </main>
  );
}
