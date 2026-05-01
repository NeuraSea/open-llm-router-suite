import { CopyButton } from "@/components/copy-button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function CodePanel({
  title,
  value,
  hint,
}: {
  title: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card className="bg-foreground text-background border-transparent">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="text-base text-background">{title}</CardTitle>
          {hint ? <p className="mt-2 text-sm text-background/60">{hint}</p> : null}
        </div>
        <CopyButton value={value} className="border-background/30 text-background hover:bg-background/10" />
      </CardHeader>
      <CardContent>
        <pre className="max-w-full overflow-auto whitespace-pre-wrap break-words [overflow-wrap:anywhere] rounded-md bg-black/20 p-4 font-mono text-sm leading-6 text-background/90">
          {value}
        </pre>
      </CardContent>
    </Card>
  );
}
