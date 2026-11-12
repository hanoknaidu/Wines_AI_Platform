import type { ReactNode } from "react";

/** Price, stock, vintage, buying, health. Not an error and not a refusal to be
 *  apologetic about — a plain statement of what this dataset does not contain,
 *  rendered as calmly as any other answer. */
export function OutOfScopeNotice({ children }: { children: ReactNode }) {
  return (
    <div className="border-l-2 border-line-strong pl-3.5 text-prose text-muted">{children}</div>
  );
}
