import { useEffect, useState } from "react";

/** Feature-detected rather than assumed: `matchMedia` is missing in some embedded
 *  webviews and in jsdom, and a layout hook is not worth a blank screen. Without it
 *  every query reads false, which lands on the desktop layout. */
function supported(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function";
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    supported() ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    if (!supported()) return;
    const list = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(list.matches);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** The two breakpoints the layout actually turns on. */
export const useIsNarrow = () => useMediaQuery("(max-width: 899px)");
export const useHasPanelRoom = () => useMediaQuery("(min-width: 1280px)");
