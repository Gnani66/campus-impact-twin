"use client";

import { usePathname } from "next/navigation";

import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";

import { navigationTitle } from "@/lib/navigation";

import { LiveIndicator } from "./LiveIndicator";

/**
 * The header.
 *
 * Deliberately thin. It answers two questions - where am I, and is
 * this data fresh - and gets out of the way of the twin, which is
 * the thing being looked at.
 */
export function AppHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-6 lg:px-8">
        <SidebarTrigger
          className="-ml-1 lg:hidden"
          aria-label="Open navigation"
        />

        <h1 className="truncate text-sm font-semibold tracking-tight">
          {navigationTitle(pathname)}
        </h1>

        <Separator
          orientation="vertical"
          className="hidden h-4 sm:block"
        />

        <LiveIndicator />

        <div className="ml-auto flex items-center gap-2" />
      </div>
    </header>
  );
}
