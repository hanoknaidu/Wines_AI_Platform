/** FR-6: the explanation comes back phrased in the words the user chose, so it is
 *  quoted here rather than restyled — including the hedge the server appends when a
 *  reading it leaned on is uncertain. */
export function WhyItMatches({ text }: { text: string }) {
  return (
    <div className="rounded-control border-l-2 border-brand-100 bg-brand-50/60 px-3 py-2">
      <p className="text-why text-ink">{text}</p>
    </div>
  );
}
