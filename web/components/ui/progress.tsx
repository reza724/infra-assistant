import { cn } from "@/lib/utils";

/** Simple progress bar in the shadcn/ui style. Color changes with the value. */
export function Progress({ value, className }: { value: number; className?: string }) {
  const v = Math.max(0, Math.min(100, value || 0));
  const color = v >= 85 ? "bg-destructive" : v >= 65 ? "bg-warning" : "bg-primary";
  return (
    <div className={cn("relative h-2 w-full overflow-hidden rounded-full bg-secondary", className)}>
      <div className={cn("h-full transition-all", color)} style={{ width: `${v}%` }} />
    </div>
  );
}
