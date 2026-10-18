"use client";

import { DoubleSide } from "three";

/**
 * A stand-in for the lecture hall.
 *
 * Drawn at the same extent the marker layout falls back to when
 * the model is absent, so markers sit on the floor of this box
 * exactly as they would sit on the model's floor. A placeholder
 * at a different size would leave the marker row hovering in
 * empty space, which looks like a positioning bug rather than a
 * missing asset.
 *
 * Wireframe on purpose. A solid box would read as a building and
 * invite the operator to interpret it as the real geometry; this
 * reads as an outline of where the room is.
 */

export const PLACEHOLDER_EXTENT = {
  min: [-4, 0, -4] as [number, number, number],
  max: [4, 4, 4] as [number, number, number],
};

export function ModelPlaceholder() {
  const size: [number, number, number] = [
    PLACEHOLDER_EXTENT.max[0] - PLACEHOLDER_EXTENT.min[0],
    PLACEHOLDER_EXTENT.max[1] - PLACEHOLDER_EXTENT.min[1],
    PLACEHOLDER_EXTENT.max[2] - PLACEHOLDER_EXTENT.min[2],
  ];

  const centre: [number, number, number] = [
    (PLACEHOLDER_EXTENT.max[0] + PLACEHOLDER_EXTENT.min[0]) / 2,
    (PLACEHOLDER_EXTENT.max[1] + PLACEHOLDER_EXTENT.min[1]) / 2,
    (PLACEHOLDER_EXTENT.max[2] + PLACEHOLDER_EXTENT.min[2]) / 2,
  ];

  return (
    <group position={centre}>
      <mesh>
        <boxGeometry args={size} />

        <meshBasicMaterial
          color="#334155"
          wireframe
          transparent
          opacity={0.5}
        />
      </mesh>

      {/*
        A solid floor, so the markers read as standing on
        something rather than floating in a wireframe.
      */}
      <mesh
        position={[0, -size[1] / 2, 0]}
        rotation={[-Math.PI / 2, 0, 0]}
      >
        <planeGeometry args={[size[0], size[2]]} />

        <meshStandardMaterial
          color="#0f172a"
          roughness={0.9}
          transparent
          opacity={0.6}
          side={DoubleSide}
        />
      </mesh>
    </group>
  );
}
