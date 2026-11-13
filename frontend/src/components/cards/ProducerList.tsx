import { Pill } from "@/components/ui/Badge";
import { isSigned } from "@/lib/review";

/** FR-11. An empty list is a real state to design for, not missing data — and this is
 *  the single most important piece of honesty on the card. A producer is exactly the
 *  field a language model invents, so it is verified in review or left out, and saying
 *  so is better than an empty section the user reads as a loading failure.
 *
 *  Names being present is therefore not enough: a `fixture` row carries names that no
 *  person has signed off. Showing those as bare pills would say "verified" by omission,
 *  which is the same lie the empty state exists to avoid — so unsigned names ship with
 *  the caveat attached rather than silently looking like checked data.
 *
 *  Note what is absent even when names ARE present: no price, no stock, no link to
 *  buy. These are names to look for, not a catalogue. */
export function ProducerList({
  producers,
  reviewStatus,
}: {
  producers: string[];
  reviewStatus: string;
}) {
  const signed = isSigned(reviewStatus);
  return (
    <div>
      <h4 className="mb-1.5 text-micro font-medium uppercase tracking-wide text-subtle">
        Producers to look for
      </h4>
      {producers.length ? (
        <>
          <div className="flex flex-wrap gap-1.5">
            {producers.map((producer) => (
              <Pill key={producer}>{producer}</Pill>
            ))}
          </div>
          {signed ? null : (
            <p className="mt-1.5 text-micro leading-relaxed text-caution-fg">
              Example names, not yet checked by a person — start here, but confirm before you
              buy.
            </p>
          )}
        </>
      ) : (
        <p className="text-chip leading-relaxed text-subtle">
          None listed. Producer names are the easiest thing to get wrong, so they are verified
          by a person during review or left out entirely.
        </p>
      )}
    </div>
  );
}
