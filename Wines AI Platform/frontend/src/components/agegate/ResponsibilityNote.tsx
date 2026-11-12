import { cn } from "@/lib/cn";

/** The regulated-product posture, in one place: no health claims in either direction,
 *  no purchase path, no price. Said once, quietly, rather than repeated as a banner. */
export function ResponsibilityNote({ className }: { className?: string }) {
  return (
    <p className={cn("text-micro leading-relaxed text-subtle", className)}>
      Please enjoy wine responsibly. Wines AI suggests grape varieties to look for — it sells
      nothing, lists no prices, and gives no health advice in either direction.
    </p>
  );
}
