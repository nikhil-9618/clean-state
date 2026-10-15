import { ArrowRight } from "lucide-react";

import { MetadataTable } from "@/components/metadata-table";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Comparison } from "@/lib/api";

export interface ComparisonViewProps {
  comparison: Comparison;
}

export function ComparisonView({ comparison }: ComparisonViewProps) {
  return (
    <Tabs defaultValue="removed">
      <TabsList>
        <TabsTrigger value="removed">
          Removed <span className="ml-2 text-xs text-muted-foreground">{comparison.removed.length}</span>
        </TabsTrigger>
        <TabsTrigger value="retained">
          Retained <span className="ml-2 text-xs text-muted-foreground">{comparison.retained.length}</span>
        </TabsTrigger>
        <TabsTrigger value="changed">
          Changed <span className="ml-2 text-xs text-muted-foreground">{comparison.changed.length}</span>
        </TabsTrigger>
        <TabsTrigger value="added">
          Added <span className="ml-2 text-xs text-muted-foreground">{comparison.added.length}</span>
        </TabsTrigger>
      </TabsList>

      <TabsContent value="removed">
        <MetadataTable
          entries={comparison.removed}
          emptyMessage="No metadata fields were present that could be removed."
          caption="Fields that existed in the original file and are absent from the sanitized copy."
        />
      </TabsContent>

      <TabsContent value="retained">
        <MetadataTable
          entries={comparison.retained}
          emptyMessage="Nothing was retained unchanged."
          caption="Fields with identical values before and after. Structural fields and anything kept by design appear here."
        />
      </TabsContent>

      <TabsContent value="changed">
        {comparison.changed.length === 0 ? (
          <p className="text-sm text-muted-foreground">No field values changed.</p>
        ) : (
          <div className="rounded-lg border border-border/70">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-40">Tag</TableHead>
                  <TableHead>Before</TableHead>
                  <TableHead className="w-8" />
                  <TableHead>After</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {comparison.changed.map((entry) => (
                  <TableRow key={entry.key}>
                    <TableCell className="font-mono text-xs text-mint-300">{entry.key}</TableCell>
                    <TableCell className="break-all text-xs text-muted-foreground">{entry.value}</TableCell>
                    <TableCell>
                      <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
                    </TableCell>
                    <TableCell className="break-all text-xs">{entry.value_after}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </TabsContent>

      <TabsContent value="added">
        {comparison.added.length === 0 ? (
          <p className="text-sm text-muted-foreground">The sanitizer did not add any field.</p>
        ) : (
          <>
            <p className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
              <Badge variant="medium">review</Badge>
              The engine wrote these fields while rewriting the file. They are listed rather than hidden.
            </p>
            <MetadataTable entries={comparison.added} />
          </>
        )}
      </TabsContent>
    </Tabs>
  );
}
