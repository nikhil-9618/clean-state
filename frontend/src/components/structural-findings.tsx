import { Badge } from "@/components/ui/badge";
import type { StructuralReport } from "@/lib/api";

function severityVariant(severity: string) {
  if (severity === "warning") return "medium" as const;
  if (severity === "notice") return "default" as const;
  return "outline" as const;
}

export interface StructuralFindingsProps {
  report: StructuralReport;
  title?: string;
  emptyMessage?: string;
}

export function StructuralFindings({ report, title, emptyMessage }: StructuralFindingsProps) {
  const counters = Object.entries(report.counters);

  return (
    <div className="space-y-3">
      {title ? <p className="text-sm font-medium">{title}</p> : null}
      {report.findings.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {emptyMessage ?? "No container-level issues were detected in this file."}
        </p>
      ) : (
        <ul className="space-y-2">
          {report.findings.map((finding) => (
            <li key={finding.id} className="rounded-md border border-border/60 bg-card/40 p-3">
              <div className="flex items-center gap-2">
                <Badge variant={severityVariant(finding.severity)}>{finding.severity}</Badge>
                <code className="font-mono text-xs text-muted-foreground">{finding.id}</code>
              </div>
              <p className="mt-1.5 text-sm">{finding.detail}</p>
            </li>
          ))}
        </ul>
      )}

      {counters.length > 0 ? (
        <details className="rounded-md border border-border/60 bg-card/30 p-3">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Raw container counters ({counters.length})
          </summary>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            {counters.map(([key, value]) => (
              <div key={key} className="flex justify-between gap-2">
                <dt className="font-mono text-muted-foreground">{key}</dt>
                <dd className="font-mono text-mint-300">{value}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  );
}
