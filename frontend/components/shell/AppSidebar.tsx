"use client";

import { usePathname } from "next/navigation";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";

import {
  DECISION_NAVIGATION,
  PRIMARY_NAVIGATION,
  SYSTEM_NAVIGATION,
  type NavigationItem,
} from "@/lib/navigation";

import { SystemStatus } from "./SystemStatus";

/**
 * The application sidebar.
 *
 * Compact on purpose: five destinations, a decision queue and a
 * system line. A campus operator opening this mid-shift needs the
 * current state, not a tour of the product.
 */
export function AppSidebar() {
  const pathname = usePathname();

  return (
    <Sidebar collapsible="icon" className="border-r">
      <SidebarHeader>
        <div className="flex items-center gap-2.5 px-1">
          <Mark />

          <div className="min-w-0 leading-tight group-data-[collapsible=icon]:hidden">
            <p className="truncate text-sm font-semibold tracking-tight">
              Smart Campus
            </p>

            <p className="truncate text-[11px] text-muted-foreground">
              Real-time intelligence
            </p>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <NavGroup
          label="Campus"
          items={PRIMARY_NAVIGATION}
          pathname={pathname}
        />

        <NavGroup
          label="Decisions"
          items={DECISION_NAVIGATION}
          pathname={pathname}
        />

        <NavGroup
          label="System"
          items={SYSTEM_NAVIGATION}
          pathname={pathname}
          className="mt-auto"
        />
      </SidebarContent>

      <SidebarFooter>
        <SystemStatus />
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}

function NavGroup({
  label,
  items,
  pathname,
  className,
}: {
  label: string;
  items: NavigationItem[];
  pathname: string;
  className?: string;
}) {
  return (
    <SidebarGroup className={className}>
      <SidebarGroupLabel>{label}</SidebarGroupLabel>

      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const active =
              !item.disabled &&
              (pathname === item.href ||
                pathname.startsWith(`${item.href}/`));

            const icon = (
              <item.icon
                aria-hidden
                className="size-4 shrink-0"
              />
            );

            return (
              <SidebarMenuItem key={item.href}>
                {item.disabled ? (
                  /*
                   * Rendered as a disabled button rather than a
                   * link to a page that does not exist. The reason
                   * is in the tooltip, so the gap reads as a known
                   * boundary instead of a mistake.
                   */
                  <SidebarMenuButton
                    disabled
                    tooltip={item.reason}
                    className="opacity-60"
                  >
                    {icon}

                    <span>{item.title}</span>
                  </SidebarMenuButton>
                ) : (
                  <SidebarMenuButton
                    isActive={active}
                    tooltip={item.description}
                    render={<a href={item.href} />}
                  >
                    {icon}

                    <span>{item.title}</span>
                  </SidebarMenuButton>
                )}
              </SidebarMenuItem>
            );
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

/**
 * The brand mark.
 *
 * Inline SVG rather than an icon-font or an imported image: it has
 * to inherit `currentColor` so it stays correct in both the
 * expanded sidebar and the collapsed rail, at any size, with no
 * extra request.
 */
function Mark() {
  return (
    <span
      aria-hidden
      className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground group-data-[collapsible=icon]:size-9"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="size-4"
      >
        <path d="M3 20V9l6-4 6 4v11" />
        <path d="M15 20V11l6-3v12" />
        <path d="M3 20h18" />
        <path d="M6.5 12.5h.01M9.5 12.5h.01M6.5 16h.01M9.5 16h.01" />
      </svg>
    </span>
  );
}
