import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/* tailwind-merge only knows Tailwind's stock type scale. Left alone it reads the
 * theme's named sizes (text-chip, text-micro…) as colours, so `text-chip text-muted`
 * silently loses its size. Keep this list in step with the --text-* tokens in theme.css. */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["micro", "chip", "why", "prose", "note", "variety", "display"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
