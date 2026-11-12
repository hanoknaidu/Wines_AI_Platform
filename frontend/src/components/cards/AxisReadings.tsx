import { Tooltip } from "@/components/ui/Tooltip";
import { findAxis, useTasteAxes } from "@/hooks/useTasteAxes";
import { axisIdToTitle } from "@/lib/format";
import type { AxisReading } from "@/types/api";
import { AxisMeter } from "./AxisMeter";

/** The asked axes get meters; the rest get one quiet line.
 *
 * The hierarchy is the point: sweetness and the style's third axis are what the user
 * actually answered, so a mismatch there matters and deserves the space. Tannin,
 * acidity and fruit/savoury are the vocabulary of refining — worth showing, not worth
 * six meters per card.
 */
export function AxisReadings({
  axes,
  threshold,
}: {
  axes: Record<string, AxisReading>;
  threshold: number;
}) {
  const { data: meta } = useTasteAxes();
  const entries = Object.entries(axes);
  if (!entries.length) return null;

  const asked = entries.filter(([id]) => findAxis(meta, id)?.asked);
  const rest = entries.filter(([id]) => !findAxis(meta, id)?.asked);

  return (
    <div className="space-y-2">
      {asked.map(([id, reading]) => {
        const spec = findAxis(meta, id);
        const index = spec?.levels.findIndex((level) => level.value === reading.value) ?? -1;
        const hedged = reading.confidence < threshold;
        return (
          <div key={id} className="flex items-center gap-3">
            <span className="w-20 shrink-0 text-micro capitalize text-subtle">
              {axisIdToTitle(id)}
            </span>
            <AxisMeter
              levels={spec?.levels.length ?? 3}
              index={index < 0 ? 0 : index}
              hedged={hedged}
            />
            <Reading reading={reading} hedged={hedged} />
          </div>
        );
      })}

      {rest.length ? (
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 pt-0.5 text-chip text-muted">
          {rest.map(([id, reading], position) => (
            <span key={id} className="inline-flex items-baseline gap-2">
              {position > 0 ? <span className="text-line-strong">·</span> : null}
              <Reading reading={reading} hedged={reading.confidence < threshold} />
            </span>
          ))}
        </p>
      ) : null}
    </div>
  );
}

/** The server already decided the wording: "likely sweet" is not "sweet". The client
 *  renders `label` verbatim and never upgrades it. */
function Reading({ reading, hedged }: { reading: AxisReading; hedged: boolean }) {
  if (!hedged) return <span className="text-chip text-ink">{reading.label}</span>;
  return (
    <Tooltip
      content={`The dataset is less certain about this reading (${reading.confidence.toFixed(
        2,
      )} confidence), so it is worded as a likelihood rather than a fact.`}
    >
      <span className="hedged cursor-help text-chip text-muted">{reading.label}</span>
    </Tooltip>
  );
}
