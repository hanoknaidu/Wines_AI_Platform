import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Composer, type ComposerHandle } from "@/components/composer/Composer";
import { ThreadEmptyState } from "@/components/thread/ThreadEmptyState";
import { useToasts } from "@/components/ui/Toast";
import { useCreateConversation } from "@/hooks/useConversations";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { ApiProblem, isProblem } from "@/lib/problem";

/** A draft conversation: nothing is created until there is something to say.
 *
 * The architecture has `/` redirect to the most recent conversation or a new one, but
 * creating a row on every visit to the root leaves the sidebar full of empty
 * conversations nobody started. The first send creates it and hands the message
 * straight to the real screen.
 */
export function NewConversationScreen() {
  const [value, setValue] = useState("");
  const navigate = useNavigate();
  const create = useCreateConversation();
  const push = useToasts((state) => state.push);
  const composerRef = useRef<ComposerHandle | null>(null);

  useKeyboardShortcuts({ onFocusComposer: () => composerRef.current?.focus() });

  const start = (content: string) => {
    const text = content.trim();
    if (!text || create.isPending) return;
    create.mutate(undefined, {
      onSuccess: (conversation) =>
        navigate(`/c/${conversation.id}`, { state: { firstMessage: text } }),
      onError: (failure) => {
        if (isProblem(failure, "age_not_confirmed")) {
          navigate("/age", { state: { from: "/" } });
          return;
        }
        const problem = failure instanceof ApiProblem ? failure : null;
        push({
          tone: "danger",
          title: problem?.title ?? "The conversation could not be started",
          detail: problem?.detail ?? "The server could not be reached.",
          requestId: problem?.requestId,
        });
      },
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ThreadEmptyState onPick={start} />
      </div>
      <div className="shrink-0 border-t border-line bg-canvas">
        <Composer
          ref={composerRef}
          value={value}
          onChange={setValue}
          onSend={() => start(value)}
          onStop={() => {}}
          streaming={false}
          disabledReason={create.isPending ? "Starting the conversation…" : null}
        />
      </div>
    </div>
  );
}
