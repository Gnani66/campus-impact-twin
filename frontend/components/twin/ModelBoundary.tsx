"use client";

import {
  Component,
  type ReactNode,
} from "react";

/**
 * Survives a model that does not load.
 *
 * useGLTF throws when the file cannot be fetched. In React that
 * is an error, not a loading state, so it propagates out of the
 * Suspense boundary and takes the whole Canvas with it — the
 * operator gets a black rectangle and the browser console gets an
 * uncaught error, for a model that is an asset rather than the
 * thing being demonstrated.
 *
 * The twin is still worth showing without it. Every number in the
 * scene comes from the backend, and the markers are placed from
 * the snapshot, so the operational picture does not depend on the
 * GLB having arrived. This catches the failure and renders
 * `fallback` in its place, which is a plain footprint standing in
 * for the room.
 *
 * An error boundary is class-based because React has no hook form
 * of try/catch for this: the throw happens during render, below
 * any component that could otherwise observe it.
 */
export interface ModelBoundaryProps {
  /**
   * What to render when the model cannot be loaded.
   *
   * Kept as a node rather than built here, because the two scenes
   * that use this need different stand-ins: the dashboard scene
   * has markers placed from the snapshot and only needs a
   * footprint, while the full twin measures the model to place
   * markers and needs the same measurement given a default.
   */
  fallback: ReactNode;

  /** Named in the console so a failure here is identifiable. */
  children: ReactNode;
}

interface ModelBoundaryState {
  failed: boolean;
}

export class ModelBoundary extends Component<
  ModelBoundaryProps,
  ModelBoundaryState
> {
  state: ModelBoundaryState = { failed: false };

  static getDerivedStateFromError(): ModelBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    // Logged rather than swallowed. The fallback keeps the page
    // usable, but a model that stopped loading is a real fault and
    // should be visible in the console rather than hidden behind a
    // tidy placeholder.
    console.error(
      "[twin] model failed to load; rendering a placeholder instead.",
      error,
    );
  }

  render(): ReactNode {
    if (this.state.failed) {
      return this.props.fallback;
    }

    return this.props.children;
  }
}
