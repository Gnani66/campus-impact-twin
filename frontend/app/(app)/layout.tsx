import { AppShell } from "@/components/shell/AppShell";

/**
 * The signed-in surface.
 *
 * A route group, so every page inside keeps its public URL
 * (`/dashboard`, `/copilot`, ...) while sharing one shell. The
 * landing page sits outside this group because it is a marketing
 * surface with no navigation of its own.
 */
export default function AppLayout({
  children,
}: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
