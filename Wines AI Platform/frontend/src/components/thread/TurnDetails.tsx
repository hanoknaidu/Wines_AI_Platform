import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { DegradedNotice } from "@/components/trust/DegradedNotice";
import { formatCost, formatCount, formatLatency } from "@/lib/format";
import type { UsageFrame } from "@/types/sse";

/** What the turn actually did: which intent it routed to, how long it took, whether it
 *  was a cache replay, what it cost.
 *
 * Collapsed by default and deliberately quiet, but visible rather than hidden behind a
 * flag: in a group demo this is the proof that nothing was generated on the way to the
 * screen. Only available for a turn this client watched run — the transcript does not
 * carry per-turn usage, so a reloaded conversation shows nothing here.
 */
export function TurnDetails({ usage }: { usage: UsageFrame }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-control py-0.5 text-micro text-subtle transition-colors hover:text-muted"
      >
        <ChevronRight
          size={11}
          className={open ? "rotate-90 transition-transform" : "transition-transform"}
        />
        {open ? "Hide" : "What this turn did"}
      </button>

      {open ? (
        <div className="mt-2 space-y-2">
          {usage.degraded || usage.degraded_reason ? (
            <DegradedNotice reason={usage.degraded_reason} />
          ) : null}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-control border border-line bg-surface px-3 py-2.5 text-micro sm:grid-cols-4">
            <Item label="Routed to" value={usage.intent.replace(/_/g, " ")} />
            <Item label="Confidence" value={usage.intent_confidence.toFixed(2)} />
            <Item label="Took" value={formatLatency(usage.latency_ms)} />
            <Item label="Engine" value={usage.engine} />
            <Item label="Tokens in" value={formatCount(usage.tokens_in)} />
            <Item label="Tokens out" value={formatCount(usage.tokens_out)} />
            <Item label="Cost" value={formatCost(usage.cost_usd)} />
            <Item label="Cache" value={usage.cache_hit ? "replayed" : "miss"} />
            <Item label="Model" value={usage.model} />
          </dl>
        </div>
      ) : null}
    </div>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-subtle">{label}</dt>
      <dd className="tabular text-muted">{value}</dd>
    </div>
  );
}
