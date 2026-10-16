"use client";

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

import { AppHeader } from "./AppHeader";
import { AppSidebar } from "./AppSidebar";

/**
 * The application shell.
 *
 * A fixed rail on desktop, a drawer on small screens. The rail is
 * collapsible rather than hidden so an operator who wants the full
 * width for the 3D model can have it without losing the navigation
 * entirely.
 */
export function AppShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <SidebarProvider>
      <AppSidebar />

      <SidebarInset className="min-w-0 bg-background">
        <AppHeader />

        <div className="flex-1 px-4 pb-10 sm:px-6 lg:px-8">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
