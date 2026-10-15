import { Compass } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/state-blocks";

export function NotFoundPage() {
  return (
    <div className="container space-y-6 py-16">
      <EmptyState
        title="That page does not exist"
        description="The link may be outdated. CleanSlate has four real destinations: metadata inspection, metadata cleaning, the browser exposure dashboard, and the documented limitations."
        icon={<Compass className="size-8" aria-hidden />}
      />
      <div className="flex flex-wrap justify-center gap-3">
        <Button asChild variant="secondary">
          <Link to="/metadata/inspect">Inspect metadata</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link to="/metadata/sanitize">Clean a file</Link>
        </Button>
        <Button asChild variant="ghost">
          <Link to="/fingerprint">Browser exposure</Link>
        </Button>
      </div>
    </div>
  );
}
