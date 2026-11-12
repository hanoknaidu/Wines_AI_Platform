import { Suspense, lazy } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AgeGateScreen } from "@/components/agegate/AgeGateScreen";
import { AppShell } from "@/app/layouts/AppShell";
import { DatasetUnavailable } from "@/components/states/DatasetUnavailable";
import { NotFound } from "@/components/states/NotFound";
import { SkeletonText } from "@/components/ui/Skeleton";
import { useAgeStatus } from "@/hooks/useAgeGate";
import { useReady } from "@/hooks/useDatasetVersion";
import { ConversationScreen } from "@/screens/ConversationScreen";
import { NewConversationScreen } from "@/screens/NewConversationScreen";

/** Dev only, and dead code in a production build: `import.meta.env.DEV` is replaced
 *  with `false`, so the dynamic import is unreachable and the styleguide — along with
 *  the mock engine and the dataset it renders cards from — never reaches the bundle. */
const Styleguide = import.meta.env.DEV
  ? lazy(() => import("@/dev/Styleguide").then((module) => ({ default: module.Styleguide })))
  : null;

/** Two gates, in this order: the dataset either loaded or the product cannot answer,
 *  and the age is either confirmed or nothing else is reachable (FR-1). */
function Gate() {
  const location = useLocation();
  const ready = useReady();
  const age = useAgeStatus();

  if (ready.isLoading) return <Booting />;
  if (ready.data?.status !== "ready" || age.data === "unavailable") {
    return <DatasetUnavailable onRetry={() => void ready.refetch()} />;
  }
  if (age.isLoading) return <Booting />;
  if (age.data === "required") {
    return <Navigate to="/age" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

function Booting() {
  return (
    <div className="mx-auto max-w-measure px-4 py-10">
      <SkeletonText lines={3} />
    </div>
  );
}

export function Router() {
  return (
    <Routes>
      <Route path="/age" element={<AgeGateScreen />} />
      {Styleguide ? (
        <Route
          path="/dev/styleguide"
          element={
            <Suspense fallback={<Booting />}>
              <Styleguide />
            </Suspense>
          }
        />
      ) : null}
      <Route element={<Gate />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<NewConversationScreen />} />
          <Route path="/c/:cid" element={<ConversationScreen />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
