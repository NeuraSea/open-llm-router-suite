import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { ParamDef } from "@/lib/api-reference-data";

function ParamRow({ param, depth = 0 }: { param: ParamDef; depth?: number }) {
  const [expanded, setExpanded] = useState(false);
  const hasChildren = param.children && param.children.length > 0;

  return (
    <>
      <tr className="border-b border-border last:border-0">
        <td className="py-2.5 pr-3" style={{ paddingLeft: depth === 0 ? "1rem" : `${1 + depth * 1.25}rem` }}>
          <div className="flex items-center gap-1.5">
            {hasChildren && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="flex-shrink-0 text-muted-foreground hover:text-foreground transition-colors"
                aria-label={expanded ? "折叠" : "展开"}
              >
                <ChevronRight
                  className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-90" : ""}`}
                />
              </button>
            )}
            {!hasChildren && depth > 0 && (
              <span className="w-3.5 flex-shrink-0" />
            )}
            <code className="font-mono text-xs text-foreground">{param.name}</code>
          </div>
        </td>
        <td className="py-2.5 pr-3 text-xs text-muted-foreground font-mono whitespace-nowrap">
          {param.type}
        </td>
        <td className="py-2.5 pr-3">
          {param.required ? (
            <span className="inline-block text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary/10 text-primary">
              必填
            </span>
          ) : (
            <span className="inline-block text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-secondary text-muted-foreground">
              可选
            </span>
          )}
        </td>
        <td className="py-2.5 text-xs text-muted-foreground leading-5">{param.description}</td>
      </tr>
      {hasChildren && expanded &&
        param.children!.map((child) => (
          <ParamRow key={child.name} param={child} depth={depth + 1} />
        ))}
    </>
  );
}

export function ParamTable({
  params,
  title,
}: {
  params: ParamDef[];
  title: string;
}) {
  if (params.length === 0) return null;

  return (
    <div className="mt-4">
      <h4 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2">
        {title}
      </h4>
      <div className="rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-secondary/50">
              <th className="px-4 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">参数</th>
              <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">类型</th>
              <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">必填</th>
              <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">说明</th>
            </tr>
          </thead>
          <tbody>
            {params.map((param) => (
              <ParamRow key={param.name} param={param} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
