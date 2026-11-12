import { useMutation } from "@tanstack/react-query";
import { sendMessage } from "@/lib/api";

export interface SendArgs {
  cid: string;
  content: string;
  chipId?: string | null;
  /** Minted once per send and REUSED on retry. A fresh key on retry would start a
   *  second turn; the same key with different content is a 409. */
  idempotencyKey: string;
}

export function useSendTurn() {
  return useMutation({
    mutationFn: ({ cid, content, chipId, idempotencyKey }: SendArgs) =>
      sendMessage(cid, { content, selected_chip_id: chipId ?? null }, idempotencyKey),
  });
}
