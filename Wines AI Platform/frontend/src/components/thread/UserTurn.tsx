import type { Block } from "@/lib/reducer";

export function UserTurn({ blocks, pending }: { blocks: Block[]; pending?: boolean }) {
  const text = blocks
    .filter((block): block is Extract<Block, { kind: "text" }> => block.kind === "text")
    .map((block) => block.text)
    .join("\n");

  return (
    <div className="flex justify-end">
      <div
        className="max-w-[85%] rounded-card rounded-br-sm border border-line bg-surface px-3.5 py-2.5 text-prose text-ink"
        aria-busy={pending}
        style={pending ? { opacity: 0.72 } : undefined}
      >
        <p className="whitespace-pre-wrap">{text}</p>
      </div>
    </div>
  );
}
