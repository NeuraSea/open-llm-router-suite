import { CopyButton } from "@/components/copy-button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ResponseExample({
  value,
  statusCode = 200,
}: {
  value: string;
  statusCode?: number;
}) {
  return (
    <Card className="bg-foreground text-background border-transparent">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0 pb-2">
        <div>
          <CardTitle className="text-sm text-background">响应示例</CardTitle>
          <p className="mt-1 text-xs text-background/50">HTTP {statusCode}</p>
        </div>
        <CopyButton
          value={value}
          className="border-background/30 text-background hover:bg-background/10"
        />
      </CardHeader>
      <CardContent>
        <pre className="overflow-auto whitespace-pre-wrap rounded-md bg-black/20 p-3 font-mono text-xs leading-5 text-background/85">
          {value}
        </pre>
      </CardContent>
    </Card>
  );
}
