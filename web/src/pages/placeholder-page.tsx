import { Rocket } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function PlaceholderPage({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Card className="">
      <CardHeader>
        <Badge>Coming Soon</Badge>
        <CardTitle className="text-[30px] text-foreground">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-secondary/70 p-8">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Rocket className="h-6 w-6" />
          </div>
          <p className="mt-5 max-w-xl text-sm leading-7 text-muted-foreground">
            这块能力已经预留进信息架构，等后端 API 准备就绪后可以直接接入，不需要再改导航体系。
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
