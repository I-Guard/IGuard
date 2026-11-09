import type { ReactNode } from "react";
import type { Page } from "../types/api";
import { EmptyState } from "./feedback";
import { Button, cx } from "./ui";

export interface Column<T> { key: string; header: string; render: (row: T) => ReactNode; sortKey?: string; className?: string }

export function DataTable<T>({ columns, rows, rowKey, sort, onSort, onRowClick, empty }: {
  columns: Column<T>[]; rows: T[]; rowKey: (r: T) => string; sort?: string; onSort?: (s: string) => void; onRowClick?: (r: T) => void;
  empty?: { title: string; hint?: string };
}) {
  if (!rows.length) return <EmptyState title={empty?.title ?? "Nothing to show"} hint={empty?.hint} />;
  const active = sort?.replace(/^-/, "");
  const desc = sort?.startsWith("-");
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-faint">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cx("whitespace-nowrap px-3 py-2 font-medium", c.className)}
                aria-sort={c.sortKey && active === c.sortKey ? (desc ? "descending" : "ascending") : undefined}>
                {c.sortKey && onSort ? (
                  <button className="inline-flex items-center gap-1 hover:text-ink" onClick={() => onSort(active === c.sortKey && !desc ? `-${c.sortKey}` : c.sortKey!)}>
                    {c.header}<span aria-hidden>{active === c.sortKey ? (desc ? "▼" : "▲") : "↕"}</span>
                  </button>
                ) : c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={rowKey(r)} tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              onKeyDown={onRowClick ? (e) => { if (e.key === "Enter") onRowClick(r); } : undefined}
              className={cx("border-b border-line/60 last:border-0", onRowClick && "cursor-pointer hover:bg-bg-hover")}>
              {columns.map((c) => <td key={c.key} className={cx("px-3 py-2.5 align-top", c.className)}>{c.render(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pagination({ page, onPage }: { page: Pick<Page<unknown>, "page" | "pages" | "total" | "page_size">; onPage: (p: number) => void }) {
  const from = page.total === 0 ? 0 : (page.page - 1) * page.page_size + 1;
  const to = Math.min(page.page * page.page_size, page.total);
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-xs text-ink-dim">
      <span>{from}–{to} of {page.total}</span>
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>Previous</Button>
        <span aria-current="page">Page {page.page} / {page.pages}</span>
        <Button size="sm" disabled={page.page >= page.pages} onClick={() => onPage(page.page + 1)}>Next</Button>
      </div>
    </nav>
  );
}
