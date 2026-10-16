import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Smart Campus — Real-time intelligence",
    template: "%s · Smart Campus",
  },
  description:
    "Real-time intelligence for a smarter, safer and more sustainable campus: environmental, energy and infrastructure, connected through live IoT.",
};

export default function RootLayout({
  children,
}: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        {/*
          Tooltips are used sparingly, mostly for icon-only
          controls in the sidebar and the twin. The provider is
          mounted once here rather than repeated per component.
        */}
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
