import { useQuery } from "@tanstack/react-query";
import { getTasteAxes } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { AxisSpec, TasteAxesResponse } from "@/types/api";

/** The vocabulary, fetched once. No component hardcodes a wine word; everything it
 *  shows about taste comes from here or from a `chips` frame. */
export function useTasteAxes() {
  return useQuery({
    queryKey: qk.tasteAxes,
    queryFn: getTasteAxes,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

export function findAxis(axes: TasteAxesResponse | undefined, axisId: string): AxisSpec | null {
  return axes?.axes.find((axis) => axis.id === axisId) ?? null;
}

/** The consumer label for a stored axis value — "dry" -> "Not sweet at all". */
export function levelLabel(
  axes: TasteAxesResponse | undefined,
  axisId: string,
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  const axis = findAxis(axes, axisId);
  return axis?.levels.find((level) => level.value === value)?.label ?? value;
}

/** Which axes this style is actually asked about, in question order. Dessert has two;
 *  everything else has three.
 *
 *  Before a style is chosen, only the axes that apply to EVERY style are counted —
 *  body and oak are alternatives decided by the style answer, so listing both would
 *  make a three-question interview look like a four-question one. */
export function askedAxisIds(
  axes: TasteAxesResponse | undefined,
  style: string | null | undefined,
): string[] {
  if (!axes) return [];
  const styleCount = findAxis(axes, "style")?.levels.length ?? 5;
  return axes.axes
    .filter((axis) => {
      if (!axis.asked) return false;
      if (style) return axis.applies_to.includes(style);
      return axis.applies_to.length >= styleCount;
    })
    .sort((a, b) => (a.question_order ?? 99) - (b.question_order ?? 99))
    .map((axis) => axis.id);
}

export function unaskedAxisIds(axes: TasteAxesResponse | undefined): string[] {
  return (axes?.axes ?? []).filter((axis) => !axis.asked).map((axis) => axis.id);
}
