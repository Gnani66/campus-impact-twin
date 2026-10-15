"use client";

import TwinCanvas from "@/components/TwinCanvas";

export default function TwinPage() {
  return (
    <main className="h-screen bg-slate-950 text-white">
      <header className="absolute left-0 right-0 top-0 z-10 flex items-center justify-between border-b border-white/10 bg-slate-950/80 px-6 py-4 backdrop-blur-md">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.25em] text-cyan-400">
            Routezen
          </p>

          <h1 className="text-xl font-semibold">
            Campus Digital Twin
          </h1>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className="h-2 w-2 rounded-full bg-emerald-400" />
          Simulation Mode
        </div>
      </header>

      <div className="h-full pt-[73px]">
        <TwinCanvas />
      </div>
    </main>
  );
}