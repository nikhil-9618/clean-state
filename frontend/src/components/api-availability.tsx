import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useQuery } from "@/hooks/use-query";
import { fetchHealth } from "@/lib/api";

/**
 * Replaces a permanent status badge: this renders **nothing** while the
 * processing service is healthy, and only speaks up when uploads really would
 * fail. Server version strings and origins are deliberately not shown - they
 * are operator details, not visitor information.
 */
export function ApiAvailabilityNotice() {
  const health = useQuery(fetchHealth, []);

  if (health.status !== "error" && !(health.status === "ready" && !health.data.accepts_uploads)) {
    return null;
  }

  const unavailable = health.status === "ready" && !health.data.accepts_uploads;

  return (
    <Alert variant="warning" className="items-start" data-testid="api-availability-notice">
      <AlertTriangle />
      <AlertTitle>Processing is unavailable right now</AlertTitle>
      <AlertDescription>
        {unavailable
          ? "This server instance cannot run the metadata engine, so uploads are disabled. Nothing you do here will be processed."
          : "The processing service is not reachable. Free hosting sleeps after 15 minutes without traffic and needs about a minute to wake up, so a retry usually succeeds."}
      </AlertDescription>
    </Alert>
  );
}
