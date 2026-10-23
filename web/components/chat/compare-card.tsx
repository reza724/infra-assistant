"use client";

// Before / after card: shows the effect of an approved action with real numbers.

import { ArrowLeft, TrendingDown, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn, fmt } from "@/lib/utils";

export type CompareItem = {
  kind: "compare";
  title: string;
  before: number;
  after: number;
  unit: string;
  betterWhenLower: boolean;
};

export function CompareCard({ item }: { item: CompareItem }) {
  const improved = item.betterWhenLower ? item.after < item.before : item.after > item.before;
  const Icon = item.after < item.before ? TrendingDown : TrendingUp;
  return (
    <Card className={cn("p-3", improved ? "border-success/40 bg-success/5" : "border-destructive/40 bg-destructive/5")}>
      <p className="mb-2 text-sm font-semibold">نتیجه‌ی بررسی بعد از اقدام: {item.title}</p>
      <div className="flex items-center justify-center gap-4 text-lg font-bold">
        <span className="text-muted-foreground line-through decoration-1">{fmt(item.before, 1)} {item.unit}</span>
        <ArrowLeft className="h-5 w-5" />
        <span className={improved ? "text-success" : "text-destructive"}>{fmt(item.after, 1)} {item.unit}</span>
        <Icon className={cn("h-5 w-5", improved ? "text-success" : "text-destructive")} />
      </div>
    </Card>
  );
}
