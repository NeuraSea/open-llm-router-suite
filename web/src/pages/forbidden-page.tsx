import { ShieldX } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function ForbiddenPage() {
  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <Card className="w-full max-w-2xl ">
        <CardHeader>
          <div className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10 text-destructive">
            <ShieldX className="h-6 w-6" />
          </div>
          <CardTitle className="text-[30px] text-foreground">你没有访问这个区域的权限</CardTitle>
          <CardDescription>
            当前登录态仍然有效，你可以继续使用开发者接入页；只有管理员会看到凭证、配额和审计导航。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link to="/portal">回到开发者接入页</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
