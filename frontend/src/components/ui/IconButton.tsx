import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required: an icon alone is not a label. */
  label: string;
  children: ReactNode;
  tone?: "neutral" | "brand" | "danger";
}

const TONES = {
  neutral: "text-muted hover:text-ink hover:bg-sunken",
  brand: "text-brand-700 hover:bg-brand-50",
  danger: "text-danger-fg hover:bg-danger-bg",
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { className, label, children, tone = "neutral", type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-control transition-colors duration-150",
        "disabled:cursor-not-allowed disabled:text-subtle disabled:hover:bg-transparent",
        TONES[tone],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
});
