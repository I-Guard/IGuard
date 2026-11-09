import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button } from "./ui";

export function Modal({ open, title, onClose, children, footer, wide }: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input,select,textarea,button:not([data-close])");
    (first ?? ref.current)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Tab" && ref.current) { // simple focus trap
        const f = Array.from(ref.current.querySelectorAll<HTMLElement>("a[href],button:not(:disabled),input:not(:disabled),select,textarea,[tabindex]:not([tabindex='-1'])"));
        if (!f.length) return;
        const a = f[0], z = f[f.length - 1];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); previous?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className={`max-h-[90vh] w-full overflow-auto rounded-lg border border-line bg-bg-raised shadow-2xl ${wide ? "max-w-2xl" : "max-w-md"}`}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 id={titleId} className="text-base font-semibold">{title}</h2>
          <button data-close aria-label="Close dialog" className="rounded p-1 text-ink-dim hover:bg-bg-hover" onClick={onClose}>✕</button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel = "Confirm", danger, loading, onConfirm, onCancel, children }: {
  open: boolean; title: string; message: ReactNode; confirmLabel?: string; danger?: boolean; loading?: boolean;
  onConfirm: () => void; onCancel: () => void; children?: ReactNode;
}) {
  return (
    <Modal open={open} title={title} onClose={onCancel}
      footer={<><Button onClick={onCancel} disabled={loading}>Cancel</Button><Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>{confirmLabel}</Button></>}>
      <div className="text-sm text-ink-dim">{message}</div>
      {children}
    </Modal>
  );
}
