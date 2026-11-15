import "@testing-library/jest-dom/vitest";

/** jsdom implements neither of these, and both are load-bearing for the shell: the
 *  layout asks for its breakpoints, and the sidebar pages on scroll. */
if (typeof window !== "undefined") {
  if (!window.matchMedia) {
    // A wide desktop viewport, so tests exercise the sidebar + panel layout.
    window.matchMedia = ((query: string) => ({
      matches: /min-width/.test(query),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }

  if (!("IntersectionObserver" in window)) {
    class NoopObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
      readonly root = null;
      readonly rootMargin = "";
      readonly thresholds: number[] = [];
    }
    (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
      NoopObserver;
    (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
      NoopObserver;
  }
}
