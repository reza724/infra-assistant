import { Chat } from "@/components/chat/chat";

export default function Page() {
  return (
    <main className="min-h-screen">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <h1 className="text-lg font-bold">دستیار هوشمند زیرساخت <span className="text-primary">لیارا</span></h1>
          <span className="hidden text-xs text-muted-foreground sm:inline">کارهای حساس فقط با تأیید شما انجام می‌شوند</span>
        </div>
      </header>
      <Chat />
    </main>
  );
}
