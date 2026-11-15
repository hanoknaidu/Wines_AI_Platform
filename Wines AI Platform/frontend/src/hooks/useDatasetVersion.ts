import { useQuery } from "@tanstack/react-query";
import { getDatasetVersion, getReady, getUsage } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export function useDatasetVersion() {
  return useQuery({
    queryKey: qk.datasetVersion,
    queryFn: getDatasetVersion,
    staleTime: 5 * 60_000,
    retry: 1,
  });
}

export function useUsage() {
  return useQuery({ queryKey: qk.usage, queryFn: getUsage, staleTime: 0 });
}

/** The dataset either loaded or it did not. While it has not, the product cannot
 *  answer at all, so this gates the app and recovers on its own. */
export function useReady() {
  return useQuery({
    queryKey: qk.ready,
    queryFn: getReady,
    retry: false,
    refetchInterval: (query) => (query.state.data?.status === "ready" ? false : 3000),
  });
}
