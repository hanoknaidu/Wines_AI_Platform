import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Wordmark } from "@/components/shell/Wordmark";
import { useAgeStatus, useConfirmAge } from "@/hooks/useAgeGate";
import { ResponsibilityNote } from "./ResponsibilityNote";

/** FR-1: confirmed before any recommendation is shown, and re-checked server-side on
 *  every call afterwards. Wine is a regulated product; a demo that ignores that is
 *  making a statement it does not mean to.
 *
 *  Deliberately plain: no photography, no glasses being raised, nothing that could
 *  read as marketing to someone who should not be here. */
export function AgeGateScreen() {
  const [declined, setDeclined] = useState(false);
  const { data: status } = useAgeStatus();
  const confirm = useConfirmAge();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "confirmed" && !confirm.isPending) return <Navigate to={from} replace />;

  if (declined) {
    return (
      <Frame>
        <h1 className="text-display font-semibold tracking-tight text-ink">
          Come back when you are 21.
        </h1>
        <p className="mt-3 text-prose text-muted">
          Wines AI is for people of legal drinking age. There is nothing here for you before
          then, and that is the whole of it.
        </p>
      </Frame>
    );
  }

  return (
    <Frame>
      <h1 className="text-display font-semibold tracking-tight text-ink">
        Are you 21 or older?
      </h1>
      <p className="mt-3 text-prose text-muted">
        Wines AI suggests wine, which is an age-restricted product. Confirm your age to continue
        — it is kept for this browser only.
      </p>

      <div className="mt-6 flex flex-wrap gap-3">
        <Button
          variant="primary"
          onClick={() =>
            confirm.mutate(undefined, { onSuccess: () => navigate(from, { replace: true }) })
          }
          disabled={confirm.isPending}
        >
          {confirm.isPending ? "One moment…" : "Yes, I am 21 or older"}
        </Button>
        <Button variant="ghost" onClick={() => setDeclined(true)}>
          No, I am under 21
        </Button>
      </div>

      {confirm.isError ? (
        <p className="mt-4 rounded-control border border-danger-br bg-danger-bg px-3 py-2 text-why text-danger-fg">
          That did not go through. Check your connection and try again.
        </p>
      ) : null}

      <ResponsibilityNote className="mt-8" />
    </Frame>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-lg">
        <Wordmark className="mb-8" />
        <div className="rounded-card border border-line bg-surface p-6 shadow-pop sm:p-8">
          {children}
        </div>
      </div>
    </main>
  );
}
