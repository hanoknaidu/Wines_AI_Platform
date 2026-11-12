import { useMutation } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { IconButton } from "@/components/ui/IconButton";
import { Tooltip } from "@/components/ui/Tooltip";
import { useToasts } from "@/components/ui/Toast";
import { sendFeedback } from "@/lib/api";
import { ApiProblem } from "@/lib/problem";
import type { Vote } from "@/types/api";

/** FR-9: one vote per recommendation, against the row it cited.
 *
 * The buttons wait for a message id. A card that is still only on the stream has none
 * — the frames carry a turn id, not a message id — so they enable a moment later, once
 * the transcript refetch lands. Posting a vote against a row the message never cited
 * is a 409 by design, and that is a client bug rather than something to paper over.
 */
export function FeedbackButtons({
  messageId,
  rowId,
}: {
  messageId: string | null;
  rowId: string;
}) {
  const [vote, setVote] = useState<Vote | null>(null);
  const push = useToasts((state) => state.push);

  const mutation = useMutation({
    mutationFn: (next: Vote) => sendFeedback(messageId as string, rowId, next),
    onError: (error, next) => {
      setVote((current) => (current === next ? null : current));
      const problem = error instanceof ApiProblem ? error : null;
      push({
        tone: "danger",
        title: "That vote did not save",
        detail: problem?.detail,
        requestId: problem?.requestId,
      });
    },
  });

  const cast = (next: Vote) => {
    if (!messageId) return;
    setVote(next);
    mutation.mutate(next);
  };

  const disabled = !messageId;

  return (
    <div className="flex items-center gap-0.5">
      <Tooltip
        content={
          disabled ? "Available as soon as this turn is saved." : "This matched what I wanted"
        }
      >
        <span>
          <IconButton
            label="This matched what I wanted"
            onClick={() => cast("up")}
            disabled={disabled}
            tone={vote === "up" ? "brand" : "neutral"}
            className="h-7 w-7"
          >
            <ThumbsUp size={13} />
          </IconButton>
        </span>
      </Tooltip>
      <Tooltip content={disabled ? "Available as soon as this turn is saved." : "This missed"}>
        <span>
          <IconButton
            label="This missed"
            onClick={() => cast("down")}
            disabled={disabled}
            tone={vote === "down" ? "danger" : "neutral"}
            className="h-7 w-7"
          >
            <ThumbsDown size={13} />
          </IconButton>
        </span>
      </Tooltip>
    </div>
  );
}
