import { cn } from "@/lib/cn";

/** One text run. Pre-wrap rather than a markdown renderer: this engine writes plain
 *  sentences, and a renderer would be the only place markup could enter. */
export function TextRun({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <p className={cn("whitespace-pre-wrap text-prose text-ink", streaming && "stream-cursor")}>
      {text}
    </p>
  );
}
