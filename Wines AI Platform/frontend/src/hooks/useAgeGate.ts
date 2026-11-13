import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { confirmAge, listConversations } from "@/lib/api";
import { isProblem } from "@/lib/problem";
import { qk } from "@/lib/queryKeys";

export type AgeStatus = "confirmed" | "required" | "unavailable" | "unknown";

/** The age cookie is httpOnly, so the client cannot read it — it has to ASK. One
 *  cheap guarded call answers it, and the server stays the only authority (FR-1). */
export function useAgeStatus() {
  return useQuery<AgeStatus>({
    queryKey: qk.ageStatus,
    queryFn: async () => {
      try {
        await listConversations({ limit: 1 });
        return "confirmed";
      } catch (error) {
        if (isProblem(error, "age_not_confirmed")) return "required";
        if (isProblem(error, "dataset_unavailable")) return "unavailable";
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
    // The gate tells the user it "recovers on its own" after a 429 or an outage; that is
    // only true if this check is retried. Without it the gate stays stuck after the
    // backend is healthy again.
    refetchInterval: (query) => (query.state.status === "error" ? 3000 : false),
  });
}

export function useConfirmAge() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: confirmAge,
    onSuccess: async () => {
      client.setQueryData(qk.ageStatus, "confirmed");
      await client.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}
