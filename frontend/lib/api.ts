import type {
  Building,
  Campus,
  Equipment,
  Floor,
  Incident,
  Sensor,
  Zone,
} from "@/lib/types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export interface CampusTwinData {
  campus: Campus;
  buildings: Building[];
  floors: Floor[];
  zones: Zone[];
  equipment: Equipment[];
  sensors: Sensor[];
  incidents: Incident[];
}

export async function getCampusTwin(
  campusCode = "CIT-MAIN",
): Promise<CampusTwinData> {
  const response = await fetch(
    `${API_URL}/api/v1/campus/${campusCode}/twin`,
    {
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(
      `Campus Twin API failed: ${response.status}`,
    );
  }

  return response.json();
}
