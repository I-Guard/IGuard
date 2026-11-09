import { Link } from "react-router-dom";
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

export function cx(...c: (string | false | null | undefined)[]): string { return c.filter(Boolean).join(" "); }

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-white hover:bg-brand-strong",
  secondary: "border border-line bg-bg-raised text-ink hover:bg-bg-hover",
  danger: "bg-crit text-white hover:bg-red-600",
  ghost: "text-ink-dim hover:bg-bg-hover hover:text-ink",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: Variant; loading?: boolean; size?: "sm" | "md" }
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", loading, size = "md", className, children, disabled, type = "button", ...rest }, ref,
) {
  return (
    <button ref={ref} type={type} disabled={disabled || loading} aria-busy={loading || undefined}
      className={cx("inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm", VARIANTS[variant], className)} {...rest}>
      {loading && <Spinner className="h-3.5 w-3.5" />}
      {children}
    </button>
  );
});

export function Spinner({ className = "h-5 w-5" }: { className?: string }) {
  return <span role="status" aria-label="Loading" className={cx("inline-block animate-spin rounded-full border-2 border-ink-faint border-t-brand", className)} />;
}

export function Card({ title, actions, children, className, padded = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={cx("card", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

const TONES = {
  ok: "bg-ok/15 text-ok ring-ok/30", warn: "bg-warn/15 text-warn ring-warn/30", crit: "bg-crit/15 text-crit ring-crit/30",
  info: "bg-info/15 text-info ring-info/30", neutral: "bg-ink-faint/15 text-ink-dim ring-ink-faint/30",
};
export type Tone = keyof typeof TONES;
export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone])}>{children}</span>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-xl font-semibold text-ink">{title}</h1>{subtitle && <p className="mt-1 text-sm text-ink-dim">{subtitle}</p>}</div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Field({ label, error, hint, htmlFor, children }: { label: string; error?: string; hint?: string; htmlFor: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="label">{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
      {error && <p role="alert" className="mt-1 text-xs text-crit">{error}</p>}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cx("input", className)} {...p} />;
});
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...p }, ref) {
  return <select ref={ref} className={cx("input", className)} {...p}>{children}</select>;
});
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} className={cx("input min-h-[84px]", className)} {...p} />;
});

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k}><dt className="text-xs uppercase tracking-wide text-ink-faint">{k}</dt><dd className="mt-0.5 break-words text-sm text-ink">{v}</dd></div>
      ))}
    </dl>
  );
}

export function StatCard({ label, value, sub, tone, to }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone; to?: string }) {
  const color = tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : tone === "ok" ? "text-ok" : "text-ink";
  const body = (
    <div className="card h-full p-4">
      <div className="text-xs uppercase tracking-wide text-ink-dim">{label}</div>
      <div className={cx("mt-1 text-2xl font-semibold tabular-nums", color)}>{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-faint">{sub}</div>}
    </div>
  );
  return to ? <Link to={to} className="block rounded-lg hover:ring-1 hover:ring-brand">{body}</Link> : body;
}
