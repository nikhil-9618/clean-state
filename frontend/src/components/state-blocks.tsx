import { AlertCircle, Clock, FileSearch, RefreshCcw, ServerCrash } from "lucide-react";
import type { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CleanSlateApiError } from "@/lib/api";

export function EmptyState({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon?: ReactNode;
}) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
        <div className="text-mint-400">{icon ?? <FileSearch className="size-8" aria-hidden />}</div>
        <p className="text-base font-medium">{title}</p>
        <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

export function LoadingCard({ label }: { label: string }) {
  return (
    <Card>
      <CardContent className="space-y-3 p-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Clock className="size-4" aria-hidden />
          {label}
        </div>
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </CardContent>
    </Card>
  );
}

export function ErrorBlock({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const isApi = error instanceof CleanSlateApiError;
  const code = isApi ? error.code : "unknown";
  const retryAfter = isApi ? error.retryAfterSeconds : null;

  const title =
    code === "tool_unavailable" || code === "processor_busy"
      ? "The processing engine is not available right now"
      : code === "rate_limited"
        ? "Too many requests from this connection"
        : code === "network_error"
          ? "The CleanSlate API could not be reached"
          : "That request failed";

  return (
    <Alert variant="destructive" data-testid="error-block">
      <ServerCrash />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="space-y-2">
        <p>{error.message}</p>
        {retryAfter ? <p>Retry after about {retryAfter} seconds.</p> : null}
        <p className="text-xs opacity-80">
          Reference: <code className="font-mono">{code}</code>
          {isApi && error.status ? ` · HTTP ${error.status}` : ""}
        </p>
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCcw />
            Try again
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

export function InlineNote({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}
