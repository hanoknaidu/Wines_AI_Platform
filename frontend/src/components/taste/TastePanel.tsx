import { useTasteAxes, askedAxisIds, levelLabel, unaskedAxisIds } from "@/hooks/useTasteAxes";
import { UsageSummary } from "@/components/trust/UsageSummary";
import { SHOW_DIAGNOSTICS } from "@/lib/constants";
import { axisIdToTitle } from "@/lib/format";
import type { TasteProfile } from "@/types/api";
import { ProvenanceTag } from "./ProvenanceTag";

/** "What I know about your taste so far."
 *
 * The axis NAME is a dataset field name, title-cased. Every VALUE shown here is the
 * server's own consumer label — the client never translates a level itself.
 */
export function TastePanel({ profile }: { profile: TasteProfile | undefined }) {
  const { data: axes } = useTasteAxes();
  const style = profile?.style ?? null;
  const asked = askedAxisIds(axes, style);
  const unasked = unaskedAxisIds(axes).filter(
    (id) => profile?.[id as keyof TasteProfile] != null,
  );

  const filled = asked.filter((id) => profile?.[id as keyof TasteProfile] != null).length;

  return (
    <aside
      aria-label="Your taste profile"
      className="flex h-full w-panel shrink-0 flex-col gap-5 overflow-y-auto border-l border-line bg-canvas px-4 py-4"
    >
      <section>
        <h2 className="text-chip font-semibold text-ink">Your taste so far</h2>
        {asked.length && style ? (
          <p className="mt-0.5 text-micro text-subtle tabular">
            {filled} of {asked.length} answered
          </p>
        ) : null}

        {filled === 0 && !unasked.length ? (
          <p className="mt-3 text-why leading-relaxed text-subtle">
            Nothing yet. Answer the first question and what the recommendations are built on
            will appear here, along with how each answer was learned.
          </p>
        ) : (
          <dl className="mt-3 space-y-3">
            {asked.map((axisId) => (
              <SlotRow
                key={axisId}
                name={axisIdToTitle(axisId)}
                value={levelLabel(
                  axes,
                  axisId,
                  profile?.[axisId as keyof TasteProfile] as string,
                )}
                provenance={profile?.confidence?.[axisId]?.provenance}
              />
            ))}
          </dl>
        )}

        {unasked.length ? (
          <>
            <h3 className="mt-5 text-micro font-medium uppercase tracking-wide text-subtle">
              Picked up from refining
            </h3>
            <dl className="mt-2 space-y-3">
              {unasked.map((axisId) => (
                <SlotRow
                  key={axisId}
                  name={axisIdToTitle(axisId)}
                  value={levelLabel(
                    axes,
                    axisId,
                    profile?.[axisId as keyof TasteProfile] as string,
                  )}
                  provenance={profile?.confidence?.[axisId]?.provenance}
                />
              ))}
            </dl>
          </>
        ) : null}
      </section>

      {SHOW_DIAGNOSTICS ? (
        <section className="mt-auto border-t border-line pt-4">
          <h2 className="mb-2 text-chip font-semibold text-ink">This session</h2>
          <UsageSummary />
        </section>
      ) : null}
    </aside>
  );
}

function SlotRow({
  name,
  value,
  provenance,
}: {
  name: string;
  value: string | null;
  provenance?: string;
}) {
  return (
    <div>
      <dt className="text-micro capitalize text-subtle">{name}</dt>
      {value ? (
        <>
          <dd className="text-why font-medium text-ink">{value}</dd>
          <div className="mt-0.5">
            <ProvenanceTag provenance={provenance} />
          </div>
        </>
      ) : (
        <dd className="text-why text-subtle">— not yet asked</dd>
      )}
    </div>
  );
}
