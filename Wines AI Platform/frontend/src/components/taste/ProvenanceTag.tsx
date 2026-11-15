import { Check, Sparkles, Wand2 } from "lucide-react";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/cn";

/** How a slot was learned. Worth showing because `taste_profile.confidence` carries it
 *  and because an inference the user never made is the one thing they should be able
 *  to catch immediately. */
export function ProvenanceTag({ provenance }: { provenance?: string }) {
  const map = {
    asked: {
      label: "you chose this",
      icon: <Check size={10} />,
      className: "text-subtle",
      hint: "You picked this from the options.",
    },
    inferred: {
      label: "read from your words",
      icon: <Sparkles size={10} />,
      className: "text-info-fg",
      hint: "Taken from something you typed rather than something you were asked. Say so if it is wrong and it will be corrected.",
    },
    refined: {
      label: "adjusted after results",
      icon: <Wand2 size={10} />,
      className: "text-brand-700",
      hint: "Changed by a refine adjustment rather than by the interview.",
    },
  } as const;

  const entry = map[(provenance ?? "asked") as keyof typeof map] ?? map.asked;

  return (
    <Tooltip content={entry.hint}>
      <span
        className={cn(
          "inline-flex cursor-help items-center gap-1 text-[0.6875rem] leading-none",
          entry.className,
        )}
      >
        {entry.icon}
        {entry.label}
      </span>
    </Tooltip>
  );
}
