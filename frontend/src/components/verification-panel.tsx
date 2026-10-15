import { BadgeCheck, Check, ClipboardCheck, Minus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { Verification } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface VerificationPanelProps {
  verification: Verification;
  engineNotes: string[];
}

interface CheckRow {
  label: string;
  state: "confirmed" | "attention" | "not-applicable";
}

export function VerificationPanel({ verification, engineNotes }: VerificationPanelProps) {
  const recheck = verification.structural_recheck;

  const checks: CheckRow[] = [
    {
      label: verification.metadata_removed_verified
        ? "Removed fields confirmed absent by a second read"
        : "Second read reported warnings — check the notes below",
      state: verification.metadata_removed_verified ? "confirmed" : "attention",
    },
    {
      label:
        recheck === "passed"
          ? "File structure re-checked after rewriting"
          : recheck === "flagged"
            ? "File structure re-check raised findings (see container checks)"
            : "File structure was not re-checked",
      state: recheck === "passed" ? "confirmed" : "attention",
    },
    {
      label: verification.original_upload_deleted
        ? "Uploaded original deleted from the server"
        : "Uploaded original could not be confirmed as deleted",
      state: verification.original_upload_deleted ? "confirmed" : "attention",
    },
  ];

  if (verification.revision_history_rewritten !== null) {
    checks.push({
      label: verification.revision_history_rewritten
        ? "Old PDF revisions physically removed from the file"
        : "Old PDF revisions could not be removed",
      state: verification.revision_history_rewritten ? "confirmed" : "attention",
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClipboardCheck className="size-4 text-mint-400" aria-hidden />
          What was verified
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <ul className="space-y-2">
          {checks.map((check) => (
            <li key={check.label} className="flex items-start gap-2">
              <span
                className={cn(
                  "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full",
                  check.state === "confirmed" ? "bg-mint-400/20 text-mint-300" : "bg-amber-400/20 text-amber-200",
                )}
                aria-hidden
              >
                {check.state === "confirmed" ? <Check className="size-3" /> : <Minus className="size-3" />}
              </span>
              <span className={check.state === "confirmed" ? "" : "text-amber-100"}>{check.label}</span>
            </li>
          ))}
        </ul>

        <Separator />

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="flex items-center gap-2 font-medium">
              <BadgeCheck className="size-4 text-mint-400" aria-hidden />
              Kept on purpose
            </p>
            {verification.retained_by_design.length === 0 ? (
              <p className="mt-1 text-muted-foreground">Nothing was deliberately retained.</p>
            ) : (
              <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
                {verification.retained_by_design.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <p className="font-medium">Notes</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
              {engineNotes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        </div>

        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">Engine and version details</summary>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline">engine: {verification.engine}</Badge>
            {Object.entries(verification.engine_versions).map(([tool, version]) => (
              <Badge key={tool} variant="outline">
                {tool}: {version ?? "unavailable"}
              </Badge>
            ))}
            <Badge variant="outline">{verification.reinspection_tags_read} tags re-read</Badge>
          </div>
          <p className="mt-2">{verification.method}</p>
        </details>
      </CardContent>
    </Card>
  );
}
