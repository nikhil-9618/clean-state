import { EyeOff } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export interface UnverifiedListProps {
  items: string[];
  title?: string;
  intro?: string;
}

/**
 * The honesty section. Everything CleanSlate cannot confirm is listed here in
 * the user's words-facing report, so nobody can mistake "processed" for
 * "proven clean".
 */
export function UnverifiedList({ items, title, intro }: UnverifiedListProps) {
  return (
    <Alert variant="warning" data-testid="unverified-list">
      <EyeOff />
      <AlertTitle>{title ?? "Not verified as removed"}</AlertTitle>
      <AlertDescription>
        <p>{intro ?? "CleanSlate does not claim these categories were removed:"}</p>
        {items.length === 0 ? (
          <p className="mt-2 text-sm">No unverified categories were reported for this file.</p>
        ) : (
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </AlertDescription>
    </Alert>
  );
}
