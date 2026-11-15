import { cn } from "@/lib/cn";

/** One taste axis as a position on its scale.
 *
 * Form: a three-segment METER, not a bar — the value is an ordinal position, not a
 * magnitude, and there is nothing to compare it against. One series, so no legend: the
 * label beside it names what this is, and the words carry the value. The meter is
 * redundant encoding, which is exactly what makes it safe.
 *
 * Marks: thin (4px), 2px gaps in the surface colour doing the separating, outer
 * data-ends rounded, track one step off the surface and recessive. The fill is neutral
 * ink rather than the brand accent: six of these on five cards would spend the whole
 * accent budget on decoration, and the accent's job is the style dot.
 *
 * A HEDGED reading (server confidence below the threshold) is drawn at reduced
 * opacity, never in amber. Amber means "needs your attention"; an honest hedge on a
 * normal day is not a warning, and colouring it like one would teach the user that
 * candour is a problem.
 */
export function AxisMeter({
  levels,
  index,
  hedged,
}: {
  levels: number;
  index: number;
  hedged?: boolean;
}) {
  return (
    <div
      className="flex h-1 w-20 shrink-0 items-stretch gap-0.5"
      aria-hidden
      /* aria-hidden: the value is already in the text beside it, and announcing
         "position 3 of 3" twice is noise to a screen reader. */
    >
      {Array.from({ length: levels }).map((_, step) => (
        <span
          key={step}
          className={cn(
            "flex-1",
            step === 0 && "rounded-l-full",
            step === levels - 1 && "rounded-r-full",
            step === index ? (hedged ? "bg-muted/45" : "bg-muted") : "bg-line",
          )}
        />
      ))}
    </div>
  );
}
