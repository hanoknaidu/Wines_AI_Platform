import { AlertTriangle } from "lucide-react";

/** An `error` frame mid-turn. Rendered under whatever already streamed, never
 *  replacing it: partial content the user watched arrive is not a lie, and discarding
 *  it would look like the app had rewritten history. */
export function StreamErrorNotice({ title, detail }: { title: string | null; detail: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-card border border-danger-br bg-danger-bg px-3.5 py-2.5">
      <AlertTriangle size={15} className="mt-0.5 shrink-0 text-danger-fg" />
      <div>
        <p className="text-why font-medium text-danger-fg">
          {title ?? "The answer could not be completed"}
        </p>
        <p className="mt-0.5 text-why text-danger-fg/90">{detail}</p>
      </div>
    </div>
  );
}
