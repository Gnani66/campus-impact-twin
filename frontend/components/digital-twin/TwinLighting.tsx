"use client";

/**
 * Lighting for the twin scene.
 *
 * Three lights rather than one: ambient so shadowed geometry stays
 * readable, a key light that casts the shadows, and a hemisphere
 * to give the scene a sky and ground tint.
 *
 * The intensities are deliberately low. A digital twin is an
 * instrument, and blown-out lighting washes out the status
 * colours that carry the actual information.
 */
export function TwinLighting() {
  return (
    <>
      <ambientLight intensity={0.9} />

      <directionalLight
        position={[10, 12, 8]}
        intensity={1.6}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={1}
        shadow-camera-far={50}
        shadow-camera-left={-15}
        shadow-camera-right={15}
        shadow-camera-top={15}
        shadow-camera-bottom={-15}
      />

      <hemisphereLight intensity={0.5} groundColor="#1e293b" />
    </>
  );
}
