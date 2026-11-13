/** /dev/styleguide — every token, primitive and state on one page.
 *
 * It exists for three jobs: to show the system to someone in one screen, to make
 * token drift visible rather than theoretical, and to reach states that are otherwise
 * awkward to produce — a dropped stream mid-run, a 429, an unloaded dataset.
 */

import { useState } from "react";
import { RecommendationCard } from "@/components/cards/RecommendationCard";
import { ChipRecord } from "@/components/chips/ChipRecord";
import { ChipRow } from "@/components/chips/ChipRow";
import { AbstentionNotice } from "@/components/states/AbstentionNotice";
import { OutOfScopeNotice } from "@/components/states/OutOfScopeNotice";
import { CardSkeleton } from "@/components/cards/CardSkeleton";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { TextRun } from "@/components/thread/TextRun";
import { TurnDetails } from "@/components/thread/TurnDetails";
import { DegradedNotice } from "@/components/trust/DegradedNotice";
import { StaleVersionNotice } from "@/components/trust/StaleVersionNotice";
import { Badge, Pill } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { Tooltip } from "@/components/ui/Tooltip";
import { ROWS } from "@/mocks/engine";
import * as copy from "@/mocks/engine/copy";
import { REFINE_CHIPS } from "@/mocks/engine/axes";
import type { MockControls } from "@/mocks/browser";
import type { Card } from "@/types/api";
import { Flame, Trash2 } from "lucide-react";
import { contrast, floorFor, passes, type ContrastNeed } from "./contrast";

const controls = () => (window as unknown as { waMock?: MockControls }).waMock;

/** Cards are built from real rows through the real copy templates — the styleguide
 *  does not get its own wine data any more than the app does. */
function cardFor(rowId: string, profile: Record<string, string>): Card {
  const row = ROWS.find((r) => r.row_id === rowId) ?? ROWS[0];
  return {
    row_id: row.row_id,
    variety: row.variety,
    style: row.style,
    axes: copy.axisReadings(row),
    description: row.description,
    why_it_matches: copy.whyItMatches(row, profile),
    typical_regions: [...row.typical_regions],
    example_producers: [...row.example_producers],
    review_status: row.review_status,
    dataset_version: row.dataset_version,
  };
}

const COLOURS: [string, string][] = [
  ["canvas", "#FAF8F5"],
  ["surface", "#FFFFFF"],
  ["sunken", "#F2EEE8"],
  ["line", "#E6E0D8"],
  ["line-strong", "#D2C9BC"],
  ["ink", "#1C1917"],
  ["muted", "#57534E"],
  ["subtle", "#857E75"],
  ["brand-900", "#4A1324"],
  ["brand-700", "#6B1B30"],
  ["brand-600", "#8A2440"],
  ["brand-500", "#A8384F"],
  ["brand-100", "#F7E4E7"],
  ["brand-50", "#FCF3F4"],
  ["style-red", "#8A2440"],
  ["style-white", "#96761B"],
  ["style-rose", "#C05470"],
  ["style-sparkling", "#46707F"],
  ["style-dessert", "#8A5520"],
  ["ok-fg", "#15803D"],
  ["caution-fg", "#92400E"],
  ["danger-fg", "#991B1B"],
  ["info-fg", "#1D4ED8"],
];

const PAIRS: [string, string, string, string, ContrastNeed][] = [
  ["ink on canvas", "#1C1917", "#FAF8F5", "body text", "body"],
  ["muted on canvas", "#57534E", "#FAF8F5", "secondary text", "body"],
  ["subtle on canvas", "#857E75", "#FAF8F5", "metadata", "large"],
  ["muted on sunken", "#57534E", "#F2EEE8", "sidebar text", "body"],
  ["white on brand-700", "#FFFFFF", "#6B1B30", "primary button", "body"],
  ["brand-700 on brand-50", "#6B1B30", "#FCF3F4", "selected chip", "body"],
  ["brand-900 on brand-50", "#4A1324", "#FCF3F4", "active sidebar row", "body"],
  ["ok-fg on ok-bg", "#15803D", "#F0FDF4", "reviewed badge", "body"],
  ["caution-fg on caution-bg", "#92400E", "#FFFBEB", "unreviewed badge", "body"],
  ["danger-fg on danger-bg", "#991B1B", "#FEF2F2", "error notice", "body"],
  ["info-fg on info-bg", "#1D4ED8", "#EFF6FF", "stale notice", "body"],
  ["muted mark on surface", "#57534E", "#FFFFFF", "axis meter fill", "mark"],
  ["line on surface", "#E6E0D8", "#FFFFFF", "meter track", "mark"],
  ["style-rose on surface", "#C05470", "#FFFFFF", "style dot (mark only)", "mark"],
  ["style-white on surface", "#96761B", "#FFFFFF", "style dot (mark only)", "mark"],
];

export function Styleguide() {
  const [forced, setForced] = useState<string | null>(null);

  return (
    <div className="min-h-dvh bg-canvas px-6 py-10">
      <div className="mx-auto max-w-4xl space-y-12">
        <header>
          <h1 className="text-display font-semibold tracking-tight text-ink">
            Wines AI — design system
          </h1>
          <p className="mt-2 max-w-2xl text-prose text-muted">
            Warm, editorial, quiet. The garnet accent lands on roughly 5% of the pixels; the
            style accents only ever tint a dot, a 1px border or a wash, and are always
            accompanied by words.
          </p>
        </header>

        <Section title="Colour" note="Every token. Raw hex appears nowhere else in src/.">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {COLOURS.map(([name, hex]) => (
              <div key={name} className="rounded-control border border-line bg-surface p-2">
                <div
                  className="h-10 w-full rounded border border-line"
                  style={{ background: hex }}
                />
                <p className="mt-1.5 text-micro text-ink">{name}</p>
                <p className="font-mono text-[0.625rem] uppercase text-subtle">{hex}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section
          title="Contrast audit"
          note="Computed on render, not eyeballed. 4.5:1 for body, 3:1 for large text and non-text marks."
        >
          <table className="w-full text-left text-chip">
            <thead>
              <tr className="border-b border-line text-micro uppercase tracking-wide text-subtle">
                <th className="py-1.5 font-medium">Pairing</th>
                <th className="py-1.5 font-medium">Used for</th>
                <th className="py-1.5 text-right font-medium">Ratio</th>
                <th className="py-1.5 text-right font-medium">AA</th>
              </tr>
            </thead>
            <tbody>
              {PAIRS.map(([name, fg, bg, usage, need]) => {
                const ratio = contrast(fg, bg);
                const ok = passes(ratio, need);
                return (
                  <tr key={name} className="border-b border-line/60">
                    <td className="py-1.5 text-ink">{name}</td>
                    <td className="py-1.5 text-muted">{usage}</td>
                    <td className="py-1.5 text-right tabular text-muted">
                      {ratio.toFixed(2)}:1
                    </td>
                    <td className="py-1.5 text-right">
                      <Badge tone={ok ? "ok" : "danger"}>
                        {ok ? "pass" : `fail < ${floorFor(need)}`}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Section>

        <Section title="Type">
          <div className="space-y-3 rounded-card border border-line bg-surface p-5">
            <p className="text-display font-semibold text-ink">Display 28 — screen titles</p>
            <p className="text-variety font-semibold text-ink">Variety 22 — the answer</p>
            <p className="text-prose text-ink">Prose 16/1.65 — the thread reads at this size</p>
            <p className="font-note text-note text-ink">
              Note 16 serif — the tasting note, written down beforehand
            </p>
            <p className="text-why text-muted">Why 15 — why it matches, in your words</p>
            <p className="text-chip text-muted">Chip 13 — chips, axis labels, pills</p>
            <p className="font-mono text-micro text-subtle tabular">
              Micro 12 mono — w-0014 · seed-0.1
            </p>
          </div>
        </Section>

        <Section title="Controls">
          <div className="flex flex-wrap items-center gap-2 rounded-card border border-line bg-surface p-5">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Danger</Button>
            <Button variant="primary" disabled>
              Disabled
            </Button>
            <Button size="sm">Small</Button>
            <IconButton label="Delete">
              <Trash2 size={15} />
            </IconButton>
            <Tooltip content="Tooltips carry the hedge explanation and every disabled reason.">
              <span className="text-chip text-muted underline decoration-dotted">hover me</span>
            </Tooltip>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 rounded-card border border-line bg-surface p-5">
            <Badge>neutral</Badge>
            <Badge tone="ok">reviewed</Badge>
            <Badge tone="caution">not yet reviewed</Badge>
            <Badge tone="danger">failed</Badge>
            <Badge tone="info">info</Badge>
            <Badge tone="brand">brand</Badge>
            <Pill>Burgundy</Pill>
            <Pill>Willamette Valley</Pill>
          </div>
        </Section>

        <Section
          title="Chips"
          note="Labels always come from the server, never from a component."
        >
          <div className="space-y-4 rounded-card border border-line bg-surface p-5">
            <div>
              <p className="mb-2 text-micro uppercase tracking-wide text-subtle">Interview</p>
              <ChipRow
                options={[
                  { id: "sweetness:dry", label: "Not sweet at all" },
                  { id: "sweetness:off_dry", label: "Just a hint of sweetness" },
                  { id: "sweetness:sweet", label: "Properly sweet" },
                ]}
                onSelect={() => {}}
              />
            </div>
            <div>
              <p className="mb-2 text-micro uppercase tracking-wide text-subtle">Refine</p>
              <ChipRow
                options={REFINE_CHIPS.map((chip) => ({ id: chip.id, label: chip.label }))}
                onSelect={() => {}}
              />
            </div>
            <div>
              <p className="mb-2 text-micro uppercase tracking-wide text-subtle">
                Record of an older row
              </p>
              <ChipRecord
                chips={{
                  kind: "interview",
                  options: [
                    { id: "body:light", label: "Light and easy" },
                    { id: "body:medium", label: "In the middle" },
                    { id: "body:full", label: "Rich and bold" },
                  ],
                }}
                chosen="body:full"
              />
            </div>
          </div>
        </Section>

        <Section
          title="Recommendation card"
          note="Three real rows. No score, no rating, no rank, no price, no buy button — all of it from BRD §8."
        >
          <div className="space-y-3">
            <RecommendationCard
              card={cardFor("w-0001", { style: "red", sweetness: "dry", body: "full" })}
              messageId="m_demo"
            />
            <p className="text-micro text-subtle">
              Below: a row whose body reading is under the 0.75 confidence threshold, so the
              server hedged the wording and the meter is drawn softly.
            </p>
            <RecommendationCard
              card={cardFor("w-0004", { style: "red", sweetness: "dry", body: "full" })}
              messageId="m_demo"
            />
            <p className="text-micro text-subtle">
              Below: thumbs disabled, as they are for the few milliseconds before a streamed
              turn has a message id.
            </p>
            <RecommendationCard
              card={cardFor("w-0021", { style: "white", sweetness: "off_dry", oak: "none" })}
              messageId={null}
            />
            <CardSkeleton />
          </div>
        </Section>

        <Section title="Answer states" note="Framed structurally, never by reading the text.">
          <div className="space-y-4 rounded-card border border-line bg-surface p-5">
            <AbstentionNotice>
              <TextRun text={copy.emptyState({ style: "dessert", sweetness: "dry" })} />
            </AbstentionNotice>
            <OutOfScopeNotice>
              <TextRun text={copy.outOfScope("price")} />
            </OutOfScopeNotice>
            <TextRun text="A turn still being written." streaming />
            <StreamErrorNotice
              title="The recommendation could not be completed"
              detail="Something went wrong while answering. Try again."
            />
            <StaleVersionNotice pinned="seed-0.0" served="seed-0.1" />
            <DegradedNotice />
            <TurnDetails
              usage={{
                turn_id: "t_demo",
                intent: "recommend",
                intent_confidence: 0.85,
                model: "deterministic",
                engine: "deterministic",
                tokens_in: 0,
                tokens_out: 0,
                cost_usd: 0,
                cache_hit: false,
                degraded: false,
                degraded_reason: null,
                latency_ms: 412,
              }}
            />
            <div>
              <SkeletonText lines={3} />
              <Skeleton className="mt-3 h-9 w-40" />
            </div>
          </div>
        </Section>

        <Section
          title="Reach a state"
          note="The states that are otherwise awkward to produce. These drive the mock directly."
        >
          <div className="flex flex-wrap gap-2 rounded-card border border-line bg-surface p-5">
            <Button
              variant="secondary"
              onClick={() => {
                const dropped = controls()?.dropStream() ?? 0;
                setForced(`dropped ${dropped} open stream(s)`);
              }}
            >
              <Flame size={14} /> Drop the open stream
            </Button>
            {[
              "rate_limited",
              "dataset_unavailable",
              "turn_in_flight",
              "internal_error",
              "engine_unavailable",
            ].map((code) => (
              <Button
                key={code}
                variant="secondary"
                onClick={() => {
                  controls()?.forceNext(code);
                  setForced(`next mutation fails with ${code}`);
                }}
              >
                {code}
              </Button>
            ))}
            <Button
              variant="secondary"
              onClick={() => {
                controls()?.setReady(false);
                setForced("dataset marked unavailable — open the app");
              }}
            >
              dataset not ready
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                controls()?.setReady(true);
                setForced("dataset ready again");
              }}
            >
              dataset ready
            </Button>
            <Button variant="danger" onClick={() => controls()?.reseed()}>
              Reseed the mock
            </Button>
            {forced ? <p className="w-full text-micro text-subtle">{forced}</p> : null}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="text-lg font-semibold tracking-tight text-ink">{title}</h2>
      {note ? (
        <p className="mb-3 mt-1 max-w-2xl text-why text-muted">{note}</p>
      ) : (
        <div className="mb-3" />
      )}
      {children}
    </section>
  );
}
