import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-700 text-white hover:bg-brand-600 active:bg-brand-900 disabled:bg-line-strong disabled:text-subtle",
  secondary:
    "bg-surface text-ink border border-line hover:bg-sunken hover:border-line-strong disabled:text-subtle",
  ghost: "text-muted hover:bg-sunken hover:text-ink disabled:text-subtle",
  danger:
    "bg-surface text-danger-fg border border-danger-br hover:bg-danger-bg disabled:text-subtle",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-chip rounded-control gap-1.5",
  md: "h-10 px-4 text-why rounded-control gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "secondary", size = "md", type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center font-medium transition-colors duration-150",
        "disabled:cursor-not-allowed",
        SIZES[size],
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
});
