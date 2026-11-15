import { Database } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Popover } from "@/components/ui/Popover";
import { Skeleton } from "@/components/ui/Skeleton";
import { useDatasetVersion } from "@/hooks/useDatasetVersion";
import { formatCount } from "@/lib/format";

/** Which artifact is being served, and what has not been checked about it.
 *
 * This is the most important badge in the product: every card's claim traces to a row
 * in this version, and hiding what is unverified about that version would make the UI
 * quietly dishonest.
 *
 * Two things here are load-bearing:
 *
 * 1. **`unverified`, not `unreviewed`.** The tone and the warning key off reviewed vs
 *    everything-else, so an artifact of `fixture` rows (producer names present, nobody's
 *    signature on them) still reads as caution. Keying off `unreviewed` alone turned
 *    this badge green for the demo artifact and dropped the warning entirely.
 * 2. **The warning text is derived, never hardcoded.** It used to state that no producer
 *    names were listed anywhere, which was true of the seed and became a lie the moment
 *    any artifact carried names. It now says which of the two situations it is. */
export function DatasetBadge() {
  const { data, isLoading, isError } = useDatasetVersion();

  if (isLoading) return <Skeleton className="h-6 w-36" />;
  if (isError || !data) return null;

  const counts = data.review_status_counts;
  const at = (key: string) => counts[key] ?? 0;

  const reviewed = at("reviewed") + at("corrected");
  const fixture = at("fixture");
  const unreviewed = at("unreviewed");
  // Anything the client does not recognise counts as unverified, matching
  // `reviewStatusOf`: an unknown status must never be summed into `reviewed`.
  const known = new Set(["reviewed", "corrected", "fixture", "unreviewed"]);
  const unknown = Object.entries(counts).reduce(
    (total, [key, n]) => (known.has(key) ? total : total + n),
    0,
  );
  const unverified = fixture + unreviewed + unknown;

  return (
    <Popover
      align="end"
      trigger={
        <button
          type="button"
          className="inline-flex items-center rounded-full outline-none focus-visible:outline-2 focus-visible:outline-brand-600"
          aria-label="About this dataset"
        >
          <Badge tone={unverified > 0 ? "caution" : "ok"}>
            <Database size={11} />
            <span className="tabular">
              {formatCount(data.row_count)} rows · {data.dataset_version}
            </span>
          </Badge>
        </button>
      }
    >
      <h3 className="text-chip font-semibold text-ink">Where these answers come from</h3>
      <p className="mt-2 text-why leading-relaxed">
        Every card is served from one row of a fixed dataset — {formatCount(data.row_count)}{" "}
        grape varieties and styles, version{" "}
        <span className="tabular">{data.dataset_version}</span>. Nothing is written while you
        wait, so what this can say was decided before you arrived.
      </p>

      <dl className="mt-3 space-y-1.5 border-t border-line pt-3 text-micro">
        <Row label="Reviewed by a person" value={formatCount(reviewed)} />
        {fixture > 0 ? (
          <Row label="Example data, unverified" value={formatCount(fixture)} tone="caution" />
        ) : null}
        <Row label="Not yet reviewed" value={formatCount(unreviewed)} tone="caution" />
        {unknown > 0 ? (
          <Row label="Unrecognised status" value={formatCount(unknown)} tone="caution" />
        ) : null}
        {data.built_at ? (
          <Row label="Built" value={new Date(data.built_at).toLocaleDateString()} />
        ) : null}
        <Row label="Checksum" value={data.checksum.slice(0, 18)} mono />
      </dl>

      {unverified > 0 ? (
        <p className="mt-3 rounded-control border border-caution-br bg-caution-bg px-2.5 py-2 text-micro leading-relaxed text-caution-fg">
          {fixture > 0
            ? "This is the demo artifact. The taste readings are the real ones, but the producer names on these cards are illustrative examples that no person has checked — a producer is the one field that gets invented, so treat those names as a place to start looking rather than verified fact."
            : "These rows have not been through human review yet, and no producer names are listed anywhere — a producer is the one field that gets invented, so they are verified in review or left out. Treat the taste readings as a solid starting point, not a checked fact."}
        </p>
      ) : null}
    </Popover>
  );
}

function Row({
  label,
  value,
  tone,
  mono,
}: {
  label: string;
  value: string;
  tone?: "caution";
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-subtle">{label}</dt>
      <dd
        className={[
          "tabular",
          mono ? "font-mono text-[0.6875rem]" : "",
          tone === "caution" ? "text-caution-fg" : "text-muted",
        ].join(" ")}
      >
        {value}
      </dd>
    </div>
  );
}
