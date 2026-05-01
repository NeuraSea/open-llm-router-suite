import { createContext, useContext, type ReactNode } from "react";

import type { UiConfig, UiSession } from "@/lib/types";

interface UiShellContextValue {
  config: UiConfig;
  session: UiSession;
}

const UiShellContext = createContext<UiShellContextValue | null>(null);

export function UiShellProvider({
  value,
  children,
}: {
  value: UiShellContextValue;
  children: ReactNode;
}) {
  return <UiShellContext.Provider value={value}>{children}</UiShellContext.Provider>;
}

export function useUiShell() {
  const value = useContext(UiShellContext);
  if (!value) {
    throw new Error("useUiShell must be used within UiShellProvider");
  }
  return value;
}
