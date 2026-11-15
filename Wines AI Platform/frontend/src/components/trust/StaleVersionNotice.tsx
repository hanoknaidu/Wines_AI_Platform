import { History } from "lucide-react";

/** The conversation was pinned to one artifact and a different one is being served
 *  now. Reported rather than silently re-served under a new version, because the cards
 *  above were written from the older rows. */
export function StaleVersionNotice({ pinned, served }: { pinned: string; served: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-card border border-info-br bg-info-bg px-3.5 py-2.5">
      <History size={15} className="mt-0.5 shrink-0 text-info-fg" />
      <p className="text-why leading-relaxed text-info-fg">
        This conversation was answered from dataset <span className="tabular">{pinned}</span>.
        The current version is <span className="tabular">{served}</span>, so a new answer here
        may differ from the cards above.
      </p>
    </div>
  );
}
