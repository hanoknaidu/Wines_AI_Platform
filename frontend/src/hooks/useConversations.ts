import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  patchConversation,
} from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import { qk } from "@/lib/queryKeys";
import type { ConversationPage } from "@/types/api";

export function useConversations(archived: boolean, q: string) {
  return useInfiniteQuery<ConversationPage>({
    queryKey: qk.conversations(archived, q),
    queryFn: ({ pageParam }) =>
      listConversations({ cursor: pageParam as string | null, limit: PAGE_SIZE, archived, q }),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 15_000,
  });
}

export function useConversation(cid: string | null) {
  return useQuery({
    queryKey: qk.conversation(cid ?? "none"),
    queryFn: () => getConversation(cid as string),
    enabled: Boolean(cid),
    retry: false,
  });
}

export function useCreateConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (title?: string) => createConversation(title),
    onSuccess: () => client.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useRenameConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ cid, title }: { cid: string; title: string }) =>
      patchConversation(cid, { title }),
    onSuccess: (row) => {
      client.invalidateQueries({ queryKey: ["conversations"] });
      client.invalidateQueries({ queryKey: qk.conversation(row.id) });
    },
  });
}

export function useArchiveConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ cid, archived }: { cid: string; archived: boolean }) =>
      patchConversation(cid, { archived }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useDeleteConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (cid: string) => deleteConversation(cid),
    onSuccess: (_data, cid) => {
      client.invalidateQueries({ queryKey: ["conversations"] });
      client.removeQueries({ queryKey: qk.conversation(cid) });
    },
  });
}
