/** WCAG contrast, computed rather than eyeballed.
 *
 * The styleguide renders this over every pairing the UI actually uses, so a token
 * change that breaks AA fails in front of whoever made it instead of in front of a
 * user. 4.5:1 for body text, 3:1 for large text and for non-text marks.
 */

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const clean = hex.replace("#", "");
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean;
  const r = Number.parseInt(full.slice(0, 2), 16);
  const g = Number.parseInt(full.slice(2, 4), 16);
  const b = Number.parseInt(full.slice(4, 6), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrast(foreground: string, background: string): number {
  const a = luminance(foreground);
  const b = luminance(background);
  const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  return Math.round(ratio * 100) / 100;
}

export type ContrastNeed = "body" | "large" | "mark";

const FLOORS: Record<ContrastNeed, number> = { body: 4.5, large: 3, mark: 3 };

export function passes(ratio: number, need: ContrastNeed): boolean {
  return ratio >= FLOORS[need];
}

export function floorFor(need: ContrastNeed): number {
  return FLOORS[need];
}
