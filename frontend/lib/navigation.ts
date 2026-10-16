import {
  Boxes,
  ClipboardCheck,
  LayoutDashboard,
  LineChart,
  Settings,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import type { LucideIcon } from "lucide-react";

/**
 * Navigation.
 *
 * One list, so the sidebar, the mobile drawer and any command
 * palette render the same set of destinations from one source. A
 * route that is not navigable is either absent or explicitly
 * `disabled` with a reason - never a link to a page that does not
 * exist.
 */

export interface NavigationItem {
  title: string;
  href: string;
  icon: LucideIcon;
  description: string;

  /**
   * Present but not clickable, with `reason` explaining what is
   * missing. Used for surfaces the backend cannot honestly back
   * yet, rather than a link that would 404.
   */
  disabled?: boolean;
  reason?: string;
}

export const PRIMARY_NAVIGATION: NavigationItem[] = [
  {
    title: "Overview",
    href: "/dashboard",
    icon: LayoutDashboard,
    description: "What is happening on campus right now.",
  },
  {
    title: "Digital Twin",
    href: "/digital-twin",
    icon: Boxes,
    description: "The live 3D model and every entity behind it.",
  },
  {
    title: "Incidents",
    href: "/incidents",
    icon: TriangleAlert,
    description: "What the rules raised, and the evidence for it.",
  },
  {
    title: "Analytics",
    href: "/analytics",
    icon: LineChart,
    description: "Trends over time.",
    disabled: true,
    reason:
      "Needs a telemetry history endpoint. The API exposes latest readings only, so any trend drawn today would be invented.",
  },
  {
    title: "AI Copilot",
    href: "/copilot",
    icon: Sparkles,
    description: "Ask what needs attention, and why.",
  },
];

export const DECISION_NAVIGATION: NavigationItem[] = [
  {
    title: "Approvals",
    href: "/approvals",
    icon: ClipboardCheck,
    description:
      "Recommendations waiting on a person. Nothing acts without one.",
  },
];

export const SYSTEM_NAVIGATION: NavigationItem[] = [
  {
    title: "Settings",
    href: "/settings",
    icon: Settings,
    description: "Campus configuration.",
    disabled: true,
    reason:
      "Configuration is served from the campus record today; there is no settings API to bind to.",
  },
];

export const ALL_NAVIGATION: NavigationItem[] = [
  ...PRIMARY_NAVIGATION,
  ...DECISION_NAVIGATION,
  ...SYSTEM_NAVIGATION,
];

/** The title shown in the header for a pathname. */
export function navigationTitle(pathname: string): string {
  const match = ALL_NAVIGATION.find(
    (item) =>
      !item.disabled &&
      (pathname === item.href ||
        pathname.startsWith(`${item.href}/`)),
  );

  return match?.title ?? "Smart Campus";
}
