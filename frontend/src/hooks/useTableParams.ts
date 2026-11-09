import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/** Table state (page, sort, filters) lives in the URL: shareable, back-button friendly. */
export function useTableParams(defaults: { sort?: string; page_size?: number } = {}) {
  const [sp, setSp] = useSearchParams();
  const page = Math.max(1, Number(sp.get("page") ?? 1) || 1);
  const sort = sp.get("sort") ?? defaults.sort ?? "";
  const filters = useMemo(() => {
    const o: Record<string, string> = {};
    sp.forEach((v, k) => { if (k !== "page" && k !== "sort") o[k] = v; });
    return o;
  }, [sp]);
  const update = useCallback((patch: Record<string, string | number | null>, resetPage = true) => {
    setSp((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch)) { if (v === null || v === "" || v === undefined) next.delete(k); else next.set(k, String(v)); }
      if (resetPage && !("page" in patch)) next.delete("page");
      return next;
    }, { replace: true });
  }, [setSp]);
  return {
    page, sort, filters, page_size: defaults.page_size ?? 25,
    setPage: (p: number) => update({ page: p }, false),
    setSort: (s: string) => update({ sort: s }),
    setFilter: (k: string, v: string) => update({ [k]: v }),
    query: { page, page_size: defaults.page_size ?? 25, sort: sort || undefined, ...filters },
  };
}
