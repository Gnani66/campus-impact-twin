import { IncidentsWorkspace } from "@/components/incidents/IncidentsWorkspace";

/**
 * Resolves the zone filter from the URL.
 *
 * The twin's entity panel links here as `/incidents?zone=LH01`, so
 * the parameter is a zone code. It is trimmed and length-capped
 * because it arrives straight from a URL, and passed to the backend
 * as a filter rather than trusted as a label: the backend resolves
 * it against real zones, so a made-up code narrows to nothing
 * instead of appearing in the heading.
 */
export async function IncidentsScope({
  searchParams,
}: {
  searchParams: Promise<
    Record<string, string | string[] | undefined>
  >;
}) {
  const params = await searchParams;

  const raw = params.zone;

  const zone =
    typeof raw === "string" && raw.trim()
      ? raw.trim().slice(0, 64)
      : null;

  return <IncidentsWorkspace zone={zone} />;
}
