import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

interface ToastItem { id: number; tone: "ok" | "crit" | "info"; text: string }
interface ToastApi { success: (t: string) => void; error: (t: string) => void; info: (t: string) => void }
const Ctx = createContext<ToastApi | null>(null);
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((tone: ToastItem["tone"], text: string) => {
    const id = ++seq;
    setItems((x) => [...x, { id, tone, text }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), tone === "crit" ? 8000 : 4500);
  }, []);
  const api = useMemo<ToastApi>(() => ({ success: (t) => push("ok", t), error: (t) => push("crit", t), info: (t) => push("info", t) }), [push]);
  const color = { ok: "border-ok/50", crit: "border-crit/60", info: "border-info/50" };
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {items.map((i) => (
          <div key={i.id} role={i.tone === "crit" ? "alert" : "status"} className={`pointer-events-auto rounded-md border bg-bg-raised px-3 py-2 text-sm shadow-lg ${color[i.tone]}`}>{i.text}</div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast must be used inside <ToastProvider>");
  return v;
}
