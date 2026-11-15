import { Skeleton } from "@/components/ui/Skeleton";

/** Shaped blocks, never sample text. A skeleton that reads as a wine name has
 *  invented a wine. */
export function CardSkeleton() {
  return (
    <div className="rounded-card border border-line bg-surface p-5">
      <Skeleton className="h-6 w-44" />
      <Skeleton className="mt-2 h-3 w-24" />
      <div className="mt-4 space-y-2">
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-4/5" />
      </div>
      <Skeleton className="mt-4 h-12 w-full" />
      <div className="mt-4 space-y-2">
        <Skeleton className="h-2.5 w-3/5" />
        <Skeleton className="h-2.5 w-2/5" />
      </div>
    </div>
  );
}
