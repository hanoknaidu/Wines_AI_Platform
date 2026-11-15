import { levelLabel, useTasteAxes } from "@/hooks/useTasteAxes";

const DOTS: Record<string, string> = {
  red: "bg-style-red",
  white: "bg-style-white",
  rose: "bg-style-rose",
  sparkling: "bg-style-sparkling",
  dessert: "bg-style-dessert",
};

/** The dot is never alone: five hues cannot distinguish five styles for anyone
 *  colour-blind, so the style is always also spelled out — in the server's own words,
 *  never a label this client invented. */
export function StyleDot({ style }: { style: string }) {
  const { data: axes } = useTasteAxes();
  const label = levelLabel(axes, "style", style) ?? style;
  return (
    <span className="inline-flex items-center gap-1.5 text-micro text-muted">
      <span
        aria-hidden
        className={`h-2 w-2 shrink-0 rounded-full ${DOTS[style] ?? "bg-line-strong"}`}
      />
      {label}
    </span>
  );
}
