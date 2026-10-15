import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { TagEntry } from "@/lib/api";
import { cn } from "@/lib/utils";

type Filter = "all" | "high" | "medium" | "low";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "high", label: "High risk" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

function sensitivityVariant(sensitivity: string) {
  if (sensitivity === "high") return "high" as const;
  if (sensitivity === "medium") return "medium" as const;
  return "low" as const;
}

export interface MetadataTableProps {
  entries: TagEntry[];
  emptyMessage?: string;
  caption?: string;
}

export function MetadataTable({ entries, emptyMessage = "No fields to show.", caption }: MetadataTableProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entries.filter((entry) => {
      if (filter !== "all" && entry.sensitivity !== filter) return false;
      if (!needle) return true;
      return (
        entry.tag.toLowerCase().includes(needle) ||
        entry.group.toLowerCase().includes(needle) ||
        entry.key.toLowerCase().includes(needle)
      );
    });
  }, [entries, filter, query]);

  const counts = useMemo(
    () => ({
      high: entries.filter((entry) => entry.sensitivity === "high").length,
      medium: entries.filter((entry) => entry.sensitivity === "medium").length,
      low: entries.filter((entry) => entry.sensitivity === "low").length,
    }),
    [entries],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1">
          {FILTERS.map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant={filter === option.value ? "secondary" : "ghost"}
              onClick={() => setFilter(option.value)}
              aria-pressed={filter === option.value}
            >
              {option.label}
              {option.value !== "all" ? (
                <span className="ml-1 text-xs text-muted-foreground">{counts[option.value]}</span>
              ) : (
                <span className="ml-1 text-xs text-muted-foreground">{entries.length}</span>
              )}
            </Button>
          ))}
        </div>
        <label className="relative flex items-center">
          <Search className="pointer-events-none absolute left-2 size-4 text-muted-foreground" aria-hidden />
          <span className="sr-only">Filter metadata fields</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by tag or group"
            className="h-9 w-full rounded-md border border-input bg-background/60 pl-8 pr-3 text-sm placeholder:text-muted-foreground sm:w-64"
            data-testid="metadata-filter"
          />
        </label>
      </div>

      <div className="rounded-lg border border-border/70">
        <Table>
          {caption ? <caption className="px-3 py-2 text-left text-xs text-muted-foreground">{caption}</caption> : null}
          <TableHeader>
            <TableRow>
              <TableHead className="w-32">Group</TableHead>
              <TableHead className="w-56">Tag</TableHead>
              <TableHead>Value</TableHead>
              <TableHead className="w-24">Risk</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-sm text-muted-foreground">
                  {emptyMessage}
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((entry) => (
                <TableRow key={`${entry.key}-${entry.value.slice(0, 12)}`}>
                  <TableCell className="font-mono text-xs text-muted-foreground">{entry.group}</TableCell>
                  <TableCell className="font-mono text-xs text-mint-300">{entry.tag}</TableCell>
                  <TableCell
                    className={cn("max-w-[36rem] break-all text-xs", entry.sensitivity === "high" && "text-red-200")}
                    title={entry.value}
                  >
                    {entry.value.length > 220 ? `${entry.value.slice(0, 220)}…` : entry.value}
                  </TableCell>
                  <TableCell>
                    <Badge variant={sensitivityVariant(entry.sensitivity)}>{entry.sensitivity}</Badge>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
