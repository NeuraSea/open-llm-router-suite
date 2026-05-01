import { useEffect, useRef, useState } from "react";
import { MethodBadge } from "./method-badge";
import type { CategoryDef, EndpointDef } from "@/lib/api-reference-data";

function useActiveSection(ids: string[]): string {
  const [active, setActive] = useState(ids[0] ?? "");
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    if (observerRef.current) observerRef.current.disconnect();

    const handleIntersection = (entries: IntersectionObserverEntry[]) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          setActive(entry.target.id);
          break;
        }
      }
    };

    observerRef.current = new IntersectionObserver(handleIntersection, {
      rootMargin: "-10% 0px -75% 0px",
    });

    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) observerRef.current.observe(el);
    }

    return () => observerRef.current?.disconnect();
  }, [ids]);

  return active;
}

export function ApiSidebar({
  categories,
  endpoints,
}: {
  categories: CategoryDef[];
  endpoints: EndpointDef[];
}) {
  const allIds = endpoints.map((e) => e.id);
  const activeId = useActiveSection(allIds);

  const endpointsByCategory = (catId: string) =>
    endpoints.filter((e) => e.category === catId);

  return (
    <nav className="sticky top-6 max-h-[calc(100vh-3rem)] overflow-y-auto space-y-4 pr-2 text-sm">
      {categories.map((cat) => {
        const catEndpoints = endpointsByCategory(cat.id);
        if (catEndpoints.length === 0) return null;
        return (
          <div key={cat.id}>
            <a
              href={`#cat-${cat.id}`}
              className="block text-[10px] font-semibold uppercase tracking-widest text-muted-foreground hover:text-foreground mb-1.5 transition-colors"
            >
              {cat.title}
            </a>
            <ul className="space-y-0.5">
              {catEndpoints.map((ep) => {
                const isActive = activeId === ep.id;
                return (
                  <li key={ep.id}>
                    <a
                      href={`#${ep.id}`}
                      className={`flex items-center gap-1.5 rounded px-2 py-1 transition-colors ${
                        isActive
                          ? "bg-primary/10 text-primary font-medium"
                          : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                      }`}
                      onClick={(e) => {
                        e.preventDefault();
                        document.getElementById(ep.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
                      }}
                    >
                      <MethodBadge method={ep.method} />
                      <span className="truncate text-xs">{ep.title}</span>
                    </a>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
