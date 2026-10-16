import { Suspense } from "react";

import { DashboardView } from "@/components/dashboard/DashboardView";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The overview page.
 *
 * A server component that renders almost nothing: the dashboard
 * reads live state, so it is a client island. Keeping the island
 * small means the shell, the header and this heading arrive as
 * static HTML and paint before any request is made.
 */

export default function DashboardPage() {
  return (
    <main>
      <Suspense fallback={<DashboardSkeleton />}>
        <DashboardView />
      </Suspense>
    </main>
  );
}

function DashboardSkeleton() {
  return (
    <div className="mx-auto max-w-[1600px] space-y-5 py-6">
      <div className="space-y-2">
        <Skeleton className="h-7 w-56" />

        <Skeleton className="h-4 w-72" />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton
            key={index}
            className="h-[86px] w-full"
          />
        ))}
      </div>

      <Skeleton className="h-[520px] w-full xl:h-[640px]" />
    </div>
  );
}
