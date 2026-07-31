import type { Metadata } from "next";
import "./globals.css";
import { TopNav } from "@/components/layout/TopNav";
import { BottomTabBar } from "@/components/layout/BottomTabBar";

export const metadata: Metadata = {
  title: "Text-to-SQL Agent",
  description: "用自然语言查询你的数据",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-[var(--color-bg-subtle)] text-[var(--color-text-primary)]">
        <TopNav />
        <main className="min-h-[calc(100vh-3.5rem)] pb-14 md:pb-0">
          {children}
        </main>
        <BottomTabBar />
      </body>
    </html>
  );
}
