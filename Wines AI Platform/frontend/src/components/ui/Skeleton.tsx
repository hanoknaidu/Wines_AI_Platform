import { cn } from "@/lib/cn";

/** Shaped blocks only — never sample text. A skeleton that reads as a wine name is a
 *  skeleton that has invented a wine. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("shimmer rounded-control", className)} />;
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn(
            "h-3.5",
            index === lines - 1 ? "w-2/5" : index % 2 ? "w-4/5" : "w-full",
          )}
        />
      ))}
    </div>
  );
}
