import type { HttpMethod } from "@/lib/api-reference-data";

const METHOD_STYLES: Record<HttpMethod, string> = {
  GET: "bg-green-500/15 text-green-700 dark:text-green-400",
  POST: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  PATCH: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  DELETE: "bg-red-500/15 text-red-700 dark:text-red-400",
};

export function MethodBadge({ method }: { method: HttpMethod }) {
  return (
    <span
      className={`inline-block font-mono text-[11px] font-bold uppercase px-1.5 py-0.5 rounded ${METHOD_STYLES[method]}`}
    >
      {method}
    </span>
  );
}
