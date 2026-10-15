"use client";

import { useGLTF } from "@react-three/drei";

export default function LectureHall() {
  const { scene } = useGLTF(
    "/models/lecture-hall.glb",
  );

  return (
    <primitive
      object={scene}
      scale={1}
      position={[0, 0, 0]}
    />
  );
}

useGLTF.preload(
  "/models/lecture-hall.glb",
);