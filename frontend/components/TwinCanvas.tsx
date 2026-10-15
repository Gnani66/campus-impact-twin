"use client";

import { Canvas } from "@react-three/fiber";
import {
  OrbitControls,
  Environment,
} from "@react-three/drei";
import { Suspense } from "react";

import LectureHall from "./LectureHall";

export default function TwinCanvas() {
  return (
    <div className="h-full w-full">
      <Canvas
        shadows
        camera={{
          position: [8, 6, 10],
          fov: 45,
        }}
      >
        <color
          attach="background"
          args={["#020617"]}
        />

        <ambientLight intensity={1.5} />

        <directionalLight
          position={[10, 15, 10]}
          intensity={3}
          castShadow
        />

        <Suspense fallback={null}>
          <Environment preset="city" />

          <LectureHall />
        </Suspense>

        <OrbitControls
          enableDamping
          dampingFactor={0.08}
          minDistance={3}
          maxDistance={30}
        />
      </Canvas>
    </div>
  );
}