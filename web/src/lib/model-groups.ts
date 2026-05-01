import { formatModelGroupLabel } from "@/lib/provider-labels";
import type { UiModelRecord } from "@/lib/types";

export function groupModelsByProvider(models: UiModelRecord[]): [string, UiModelRecord[]][] {
  const groups = new Map<string, UiModelRecord[]>();
  for (const model of models) {
    const source = model.source ?? "catalog";
    const providerLabel = formatModelGroupLabel(model.provider, model.provider_alias);
    const label = model.provider_alias ? providerLabel : source === "byok" ? `${providerLabel} (BYOK)` : providerLabel;
    const existing = groups.get(label) ?? [];
    existing.push(model);
    groups.set(label, existing);
  }
  return [...groups.entries()].sort(([a], [b]) => {
    const aIsByok = a.includes("(BYOK)") ? 1 : 0;
    const bIsByok = b.includes("(BYOK)") ? 1 : 0;
    if (aIsByok !== bIsByok) return aIsByok - bIsByok;
    return a.localeCompare(b);
  });
}
