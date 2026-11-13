import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToasts } from "@/components/ui/Toast";
import {
  useArchiveConversation,
  useConversations,
  useDeleteConversation,
  useRenameConversation,
} from "@/hooks/useConversations";
import { groupConversations } from "@/lib/format";
import { ApiProblem } from "@/lib/problem";
import { ConversationItem } from "./ConversationItem";

export function ConversationList({ query, archived }: { query: string; archived: boolean }) {
  const { cid } = useParams();
  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useConversations(archived, query);
  const rename = useRenameConversation();
  const archive = useArchiveConversation();
  const remove = useDeleteConversation();
  const push = useToasts((state) => state.push);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string } | null>(
    null,
  );
  const sentinel = useRef<HTMLDivElement | null>(null);

  // Infinite scroll, 20 a page, as the architecture draws it.
  useEffect(() => {
    const element = sentinel.current;
    if (!element || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "120px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const onError = (error: unknown) => {
    const problem = error instanceof ApiProblem ? error : null;
    push({
      tone: "danger",
      title: problem?.title ?? "That did not work",
      detail: problem?.detail,
      requestId: problem?.requestId,
    });
  };

  if (isLoading) {
    return (
      <div className="space-y-1.5 px-2 py-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-9 w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <p className="px-3 py-4 text-chip text-muted">
        The conversation list could not be loaded.
      </p>
    );
  }

  const items = (data?.pages ?? []).flatMap((page) => page.items);

  if (!items.length) {
    return (
      <p className="px-3 py-6 text-chip leading-relaxed text-subtle">
        {query ? (
          <>
            No conversation titles match “{query}”.
            <br />
            Search does not cover message text yet.
          </>
        ) : archived ? (
          "Nothing archived."
        ) : (
          "No conversations yet."
        )}
      </p>
    );
  }

  return (
    <>
      <div className="pb-2">
        {groupConversations(items).map((group) => (
          <section key={group.label} className="mb-1">
            <h3 className="px-3.5 pb-1 pt-3 text-micro font-medium uppercase tracking-wide text-subtle">
              {group.label}
            </h3>
            <ul className="space-y-0.5">
              {group.items.map((conversation) => (
                <ConversationItem
                  key={conversation.id}
                  conversation={conversation}
                  active={conversation.id === cid}
                  onRename={(title) =>
                    rename.mutate({ cid: conversation.id, title }, { onError })
                  }
                  onArchive={(next) =>
                    archive.mutate({ cid: conversation.id, archived: next }, { onError })
                  }
                  onDelete={() =>
                    setPendingDelete({ id: conversation.id, title: conversation.title })
                  }
                />
              ))}
            </ul>
          </section>
        ))}
        <div ref={sentinel} aria-hidden className="h-1" />
        {isFetchingNextPage ? <Skeleton className="mx-2 h-9" /> : null}
      </div>

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title="Delete this conversation?"
        description={pendingDelete?.title}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingDelete(null)}>
              Keep it
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (pendingDelete) remove.mutate(pendingDelete.id, { onError });
                setPendingDelete(null);
              }}
            >
              Delete
            </Button>
          </>
        }
      >
        <p className="text-why text-muted">
          The transcript and the taste profile it collected go with it.
        </p>
      </Dialog>
    </>
  );
}
