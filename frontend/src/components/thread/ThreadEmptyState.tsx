import { Wordmark } from "@/components/shell/Wordmark";

/** First run. Says what this will ask and what it will not do, and offers three
 *  openers in plain words — free text is a first-class input, so showing what one
 *  looks like is worth more than hiding it to push people towards the chips. */
export function ThreadEmptyState({ onPick }: { onPick: (text: string) => void }) {
  const openers = [
    "a smooth red, nothing too sour",
    "something crisp and not sweet",
    "I want something sweet for after dinner",
  ];

  return (
    <div className="mx-auto flex max-w-measure flex-col items-start px-4 py-10 sm:py-16">
      <Wordmark compact className="mb-5" />
      <h1 className="text-display font-semibold tracking-tight text-ink">
        What do you feel like drinking?
      </h1>
      <p className="mt-3 max-w-xl text-prose text-muted">
        Three questions — what you are in the mood for, how sweet you want it, and one more —
        and you get grape varieties that match, with what each tastes like and where to look.
        Say it however you like, or tap the options.
      </p>

      <div className="mt-6 flex flex-wrap gap-2">
        {openers.map((text) => (
          <button
            key={text}
            type="button"
            onClick={() => onPick(text)}
            className="rounded-full border border-line bg-surface px-3.5 py-2 text-chip text-muted transition-colors hover:border-line-strong hover:text-ink"
          >
            {text}
          </button>
        ))}
      </div>

      <p className="mt-8 max-w-xl text-micro leading-relaxed text-subtle">
        No prices, no stock and no vintages — and no scores either. This suggests what fits your
        taste, not what a critic rated highly.
      </p>
    </div>
  );
}
