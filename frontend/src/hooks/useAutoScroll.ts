import { useCallback, useEffect, useRef, useState } from "react";

/** Follow the stream only while the reader is already at the bottom.
 *
 * Yanking someone back down while they are reading an earlier card is the single most
 * irritating thing a streaming chat UI can do, so "pinned" is a state we track rather
 * than assume.
 */
export function useAutoScroll<T>(dependency: T) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(true);

  const onScroll = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    setPinned(distance < 80);
  }, []);

  useEffect(() => {
    const element = ref.current;
    if (!element || !pinned) return;
    element.scrollTop = element.scrollHeight;
  }, [dependency, pinned]);

  const scrollToBottom = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    setPinned(true);
  }, []);

  return { ref, pinned, onScroll, scrollToBottom };
}
