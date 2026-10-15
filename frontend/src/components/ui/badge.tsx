import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/15 text-mint-300",
        outline: "border-border text-muted-foreground",
        high: "border-destructive/40 bg-destructive/15 text-red-300",
        medium: "border-amber-500/40 bg-amber-500/10 text-amber-300",
        low: "border-border bg-muted/60 text-muted-foreground",
        success: "border-primary/40 bg-primary/10 text-mint-300",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
