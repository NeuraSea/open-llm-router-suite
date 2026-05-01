import { ShieldAlert } from "lucide-react";
import { CodePanel } from "@/components/code-panel";
import { MethodBadge } from "./method-badge";
import { ParamTable } from "./param-table";
import { ResponseExample } from "./response-example";
import type { EndpointDef } from "@/lib/api-reference-data";

const AUTH_LABELS: Record<string, string> = {
  bearer: "Bearer token（Authorization: Bearer elp_...）",
  cookie: "Session cookie（浏览器自动携带）",
  none: "无需认证",
};

export function EndpointSection({
  endpoint,
  base,
}: {
  endpoint: EndpointDef;
  base: string;
}) {
  const curlExample = endpoint.requestExample?.replace(/\{BASE\}/g, base);

  return (
    <div id={endpoint.id} className="scroll-mt-6 border-t border-border pt-8">
      <div className="grid gap-6 xl:grid-cols-[1fr_400px]">
        {/* Left: metadata */}
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <MethodBadge method={endpoint.method} />
            <code className="font-mono text-sm text-foreground">{endpoint.path}</code>
            {endpoint.adminOnly && (
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-700 dark:text-amber-400">
                <ShieldAlert className="h-2.5 w-2.5" />
                Admin
              </span>
            )}
          </div>

          <h3 className="mt-3 text-base font-semibold text-foreground">{endpoint.title}</h3>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{endpoint.description}</p>

          <div className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="font-semibold">认证：</span>
            <span>{AUTH_LABELS[endpoint.auth] ?? endpoint.auth}</span>
          </div>

          {endpoint.pathParams && endpoint.pathParams.length > 0 && (
            <ParamTable params={endpoint.pathParams} title="路径参数" />
          )}
          {endpoint.queryParams && endpoint.queryParams.length > 0 && (
            <ParamTable params={endpoint.queryParams} title="Query 参数" />
          )}
          {endpoint.requestParams && endpoint.requestParams.length > 0 && (
            <ParamTable params={endpoint.requestParams} title="请求体参数" />
          )}
        </div>

        {/* Right: code examples */}
        <div className="flex flex-col gap-3 xl:sticky xl:top-6 xl:self-start">
          {curlExample && (
            <CodePanel title="curl 示例" value={curlExample} />
          )}
          {endpoint.responseExample && (
            <ResponseExample value={endpoint.responseExample} />
          )}
        </div>
      </div>
    </div>
  );
}
