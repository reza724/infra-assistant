import type { Metadata } from "next";
import "@fontsource/vazirmatn/400.css";
import "@fontsource/vazirmatn/500.css";
import "@fontsource/vazirmatn/700.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "دستیار زیرساخت لیارا",
  description: "دستیار هوشمند دیپلوی، پایش و عیب‌یابی سایت روی لیارا",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <body className="font-sans">{children}</body>
    </html>
  );
}
