import { HelpCircle } from "lucide-react";
import { useState } from "react";
import { ResponsibilityNote } from "@/components/agegate/ResponsibilityNote";
import { Dialog } from "@/components/ui/Dialog";

export function HowThisWorksButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-control px-2 py-1 text-micro text-subtle transition-colors hover:text-muted"
      >
        <HelpCircle size={12} />
        How this works
      </button>
      <Dialog open={open} onOpenChange={setOpen} title="How this works">
        <div className="space-y-4 text-why leading-relaxed text-muted">
          <section>
            <h3 className="text-chip font-semibold text-ink">Three questions</h3>
            <p className="mt-1">
              What you are in the mood for, how sweet you want it, and one more that depends on
              your first answer. They are options rather than a text box, because you should not
              need the vocabulary to answer them — though you can type instead whenever you
              prefer.
            </p>
          </section>
          <section>
            <h3 className="text-chip font-semibold text-ink">What comes back</h3>
            <p className="mt-1">
              Grape varieties, not single bottles — learning that you like Grenache is worth
              more than learning you liked one wine. Each card carries what it tastes like, why
              it matches in the words you used, and the dataset row it came from.
            </p>
          </section>
          <section>
            <h3 className="text-chip font-semibold text-ink">What it will not do</h3>
            <p className="mt-1">
              No prices, no stock, no vintages, no buying, and no health advice in either
              direction. There are no scores either: this recommends fit to your taste, not
              quality against a critic's standard.
            </p>
          </section>
          <section>
            <h3 className="text-chip font-semibold text-ink">What is not finished</h3>
            <p className="mt-1">
              The dataset has not been through human review yet, and no producer names are
              listed. Both are shown on every card rather than hidden — a producer is exactly
              the field that gets invented, so it is verified in review or left out.
            </p>
          </section>
          <ResponsibilityNote />
        </div>
      </Dialog>
    </>
  );
}
