/** "What it tastes like", straight from the row's description field and never
 *  rewritten. The serif is load-bearing: it is the one field on the card that was
 *  written down and reviewed beforehand, and setting it in a different voice from the
 *  prose around it says so without a label. */
export function TastingNote({ text }: { text: string }) {
  return <p className="font-note text-note text-ink">{text}</p>;
}
