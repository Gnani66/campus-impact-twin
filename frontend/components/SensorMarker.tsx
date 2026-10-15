"use client";

import { Html } from "@react-three/drei";

import type { Sensor } from "@/lib/types";

import {
  formatMarkerLabel,
  type MarkerStyle,
} from "@/lib/twin/config";
interface SensorMarkerProps {
  sensor: Sensor;
  marker: MarkerStyle;
}

export default function SensorMarker({
  sensor,
  marker,
}: SensorMarkerProps) {
  const inactive =
    sensor.status !== "active";

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
            inactive ? 0.1 : 0.7
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
        </div>
      </Html>
    </group>
  );
}
