import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { ApiProblem } from "@/lib/problem";

function createClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        // A problem+json response is an answer, not a flake: retrying a 403 or a 404
        // only delays the screen that should already be showing.
        retry: (failureCount, error) =>
          error instanceof ApiProblem ? false : failureCount < 2,
        staleTime: 10_000,
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  // Created once per mounted app rather than once per module: a client that outlives
  // the component tree carries one app instance's cache into the next.
  const [client] = useState(createClient);

  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}
