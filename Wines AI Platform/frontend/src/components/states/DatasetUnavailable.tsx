import { CloudOff, DatabaseZap, Hourglass } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Wordmark } from "@/components/shell/Wordmark";
import type { UnavailableReason } from "@/lib/unavailable";

const COPY = {
  dataset: {
    Icon: DatabaseZap,
    title: "Recommendations unavailable",
    body:
      "The wine dataset is not loaded, so nothing can be recommended from it. Every answer " +
      "here has to trace back to a reviewed row — with no dataset, there is no answer to give.",
  },
  rate_limited: {
    Icon: Hourglass,
    title: "Too many requests — one moment",
    body:
      "This browser has sent more requests in the last minute than the server allows. " +
      "Nothing is broken, and nothing you have done is lost.",
  },
  unreachable: {
    Icon: CloudOff,
    title: "Can't reach Wines AI",
    body:
      "The server did not answer. It may be restarting, or your connection may have dropped.",
  },
} as const;

export function DatasetUnavailable({
  onRetry,
  reason = { kind: "dataset" },
}: {
  onRetry?: () => void;
  reason?: UnavailableReason;
}) {
  const { Icon, title, body } = COPY[reason.kind];
  const wait =
    reason.kind === "rate_limited" && reason.retryAfter
      ? `Trying again in about ${reason.retryAfter}s — this page recovers on its own.`
      : "This page is checking again every few seconds and will recover on its own.";

  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-lg">
        <Wordmark className="mb-8" />
        <div
          role="alert"
          data-reason={reason.kind}
          className="rounded-card border border-line bg-surface p-6 shadow-pop"
        >
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-caution-bg text-caution-fg">
            <Icon size={18} />
          </span>
          <h1 className="mt-4 text-lg font-semibold text-ink">{title}</h1>
          <p className="mt-2 text-why text-muted">{body}</p>
          <p className="mt-2 text-why text-subtle">{wait}</p>
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
