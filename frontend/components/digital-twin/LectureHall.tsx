"use client";

import { useGLTF } from "@react-three/drei";

import { TWIN_CONFIG } from "@/lib/twin/config";

/**
 * Single source of truth for the model path.
 *
 * Read from the existing twin configuration rather than
 * restated, so the two 3D surfaces in this project cannot
 * disagree about which file they load.
 */
const MODEL_PATH = TWIN_CONFIG.model.path;

/**
 * The lecture hall model.
 *
 * The GLB is an asset, not a data source. It contributes geometry
 * and nothing else: every number on screen comes from the
 * backend through the twin snapshot, which is what makes this a
 * digital twin rather than a 3D viewer with a data panel.
 *
 * The scale and position are tuned to centre the model on the
 * origin, because the export's origin is not at the centre of the
 * room and an off-origin model sits awkwardly under the marker.
 */
export function LectureHall({
  scale = 1,
  position = [0, 0, 0],
  onSelect,
}: {
  scale?: number;
  position?: [number, number, number];
  onSelect?: () => void;
}) {
  // Suspended internally while the model loads; the nearest
  // Suspense boundary renders null until it arrives.
  const { scene } = useGLTF(MODEL_PATH);

  return (
    <group position={position} scale={scale} onClick={onSelect}>
      <primitive object={scene} />
    </group>
  );
}

// Deliberately NOT preloaded at module scope.
//
// `useGLTF.preload` starts the fetch the moment this module is
// imported, which for a model this size means the download
// begins during hydration and the scene never reaches its first
// paint. Suspense already requests it as soon as the component
// renders, which is the point at which the load actually
// matters.
export default LectureHall;
