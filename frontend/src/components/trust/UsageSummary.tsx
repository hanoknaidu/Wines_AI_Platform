import { useUsage } from "@/hooks/useDatasetVersion";
import { formatCost, formatCount } from "@/lib/format";

/** Session spend. Cost is only ever controlled if something reports it — and $0.00 is
 *  a real number here, not a placeholder: the Phase-1 engine runs no model at all. */
export function UsageSummary() {
  const { data } = useUsage();
  if (!data) return null;

  return (
    <dl className="space-y-1 text-micro">
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-subtle">Turns this session</dt>
        <dd className="tabular text-muted">{formatCount(data.turns)}</dd>
      </div>
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-subtle">Spend</dt>
        <dd className="tabular text-muted">
          {formatCost(data.cost_usd)}
          <span className="text-subtle"> / {formatCost(data.ceiling_per_session_usd)}</span>
        </dd>
      </div>
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-subtle">Engine</dt>
        <dd className="text-muted">{data.engine}</dd>
      </div>
      {data.cost_usd === 0 ? (
        <p className="pt-1 leading-relaxed text-subtle">
          No model runs in the request path yet, so every turn costs nothing.
        </p>
      ) : null}
    </dl>
  );
}
