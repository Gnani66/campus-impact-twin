"use client";

import { Html } from "@react-three/drei";

import type { Sensor } from "@/lib/types";
import type { LatestTelemetryReading } from "@/lib/types";
import {
  formatReadingAge,
  formatValue,
  isSimulated,
} from "@/lib/telemetry";

import {
  formatMarkerLabel,
  type MarkerStyle,
} from "@/lib/twin/config";

interface SensorMarkerProps {
  sensor: Sensor;
  marker: MarkerStyle;
  /**
   * Latest stored reading for this sensor, if one exists.
   * Absent means "no stored data", never a value to guess.
   */
  reading?: LatestTelemetryReading;
  /**
   * Passed in by the page rather than read from the clock in
   * render, so every marker in one frame agrees on the time.
   */
  now: number | null;
}

export default function SensorMarker({
  sensor,
  marker,
  reading,
  now,
}: SensorMarkerProps) {
  const inactive =
    sensor.status !== "active";

  // A missing or unusable reading is shown as such, never as
  // zero.
  const hasReading =
    reading !== undefined &&
    Number.isFinite(reading.value);

  const simulated = isSimulated(reading);

  const label = hasReading
    ? formatValue(reading)
    : "no data";

  return (
    <group
      position={marker.position}
      userData={{ sensorCode: sensor.code }}
    >
      <mesh>
        <sphereGeometry
          args={[0.11, 24, 24]}
        />

        <meshStandardMaterial
          color={marker.color}
          emissive={marker.color}
          emissiveIntensity={
            inactive ? 0.1 : hasReading ? 0.7 : 0.25
          }
          opacity={inactive ? 0.4 : 1}
          transparent={inactive}
        />
      </mesh>

      {!inactive && (
        <pointLight
          color={marker.color}
          intensity={0.8}
          distance={3}
        />
      )}

      <Html
        center
        distanceFactor={14}
        zIndexRange={[10, 0]}
      >
        <div className="pointer-events-none whitespace-nowrap rounded-md border border-white/15 bg-slate-950/85 px-2 py-1 text-[11px] leading-tight text-white shadow-lg">
          <span
            className="font-semibold"
            style={{ color: marker.color }}
          >
            {sensor.code}
          </span>

          <span className="ml-1.5 text-slate-400">
            {formatMarkerLabel(
              sensor.sensor_type,
            )}
          </span>

          <div className="mt-0.5 font-medium text-white">
            {label}
          </div>

          <div className="text-[10px] text-slate-500">
            {hasReading && reading
              ? now !== null
                ? formatReadingAge(reading.timestamp, now)
                : "age unknown"
              : "no stored reading"}

            {simulated ? (
              <span className="ml-1 text-amber-400/90">
                simulated
              </span>
            ) : null}
          </div>
        </div>
      </Html>
    </group>
  );
}
