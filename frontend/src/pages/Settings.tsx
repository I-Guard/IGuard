import { useState } from "react";
import { QueryBoundary, errorMessage } from "../components/feedback";
import { useToast } from "../components/Toast";
import { Can } from "../components/RequireRole";
import { Badge, Button, Card, Input, PageHeader } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { useAction, useSettings } from "../hooks/queries";
import { api } from "../services/api";
import type { Setting } from "../types/api";
import { formatDateTime } from "../utils/format";

function validate(s: Setting, raw: string): string | null {
  if (s.type === "bool") return null;
  const n = Number(raw);
  if (raw.trim() === "" || Number.isNaN(n)) return "Enter a number";
  if (s.type === "int" && !Number.isInteger(n)) return "Must be a whole number";
  if (s.minimum !== null && n < s.minimum) return `Min ${s.minimum}`;
  if (s.maximum !== null && n > s.maximum) return `Max ${s.maximum}`;
  return null;
}

export default function Settings() {
  const q = useSettings();
  const toast = useToast();
  const { hasRole } = useAuth();
  const admin = hasRole("ADMIN");
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const save = useAction((values: Record<string, number | boolean>) => api.patch("/settings", { values }), ["settings"]);
  return (
    <>
      <PageHeader title="Settings" subtitle="Runtime thresholds and behavior. Secrets live in the environment, never here." />
      <QueryBoundary query={q}>
        {(items) => {
          const dirty = items.filter((s) => draft[s.key] !== undefined && String(draft[s.key]) !== String(s.value));
          const errors = Object.fromEntries(dirty.map((s) => [s.key, typeof draft[s.key] === "boolean" ? null : validate(s, String(draft[s.key]))]));
          const hasErr = Object.values(errors).some(Boolean);
          const submit = () => {
            const values: Record<string, number | boolean> = {};
            dirty.forEach((s) => { const v = draft[s.key]; values[s.key] = s.type === "bool" ? Boolean(v) : Number(v); });
            save.mutate(values, { onSuccess: () => { toast.success("Settings saved"); setDraft({}); }, onError: (e) => toast.error(errorMessage(e)) });
          };
          return (
            <Card padded={false}>
              <ul className="divide-y divide-line/60">
                {items.map((s) => {
                  const cur = draft[s.key] ?? s.value;
                  return (
                    <li key={s.key} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                      <div className="min-w-0 max-w-xl"><label htmlFor={`set-${s.key}`} className="text-sm font-medium">{s.key}</label>
                        <p className="text-xs text-ink-dim">{s.description}</p>
                        <p className="text-xs text-ink-faint">Default {String(s.default)}{s.minimum !== null && ` · min ${s.minimum}`}{s.maximum !== null && ` · max ${s.maximum}`}{s.updated_at && ` · changed ${formatDateTime(s.updated_at)}${s.updated_by ? ` by ${s.updated_by}` : ""}`}</p></div>
                      <div className="w-40">
                        {s.type === "bool"
                          ? <input id={`set-${s.key}`} type="checkbox" disabled={!admin} checked={Boolean(cur)} onChange={(e) => setDraft({ ...draft, [s.key]: e.target.checked })} />
                          : <Input id={`set-${s.key}`} type="number" step={s.type === "float" ? "any" : 1} disabled={!admin} value={String(cur)} onChange={(e) => setDraft({ ...draft, [s.key]: e.target.value })} aria-invalid={!!errors[s.key]} />}
                        {errors[s.key] && <p role="alert" className="mt-1 text-xs text-crit">{errors[s.key]}</p>}
                      </div>
                    </li>
                  );
                })}
              </ul>
              <Can role="ADMIN"><div className="flex items-center justify-end gap-3 border-t border-line p-3">{dirty.length > 0 && <Badge tone="warn">{dirty.length} unsaved</Badge>}<Button onClick={() => setDraft({})} disabled={!dirty.length}>Reset</Button><Button variant="primary" disabled={!dirty.length || hasErr} loading={save.isPending} onClick={submit}>Save changes</Button></div></Can>
              {!admin && <p className="border-t border-line p-3 text-xs text-ink-faint">Read-only: only administrators can change settings.</p>}
            </Card>
          );
        }}
      </QueryBoundary>
    </>
  );
}
