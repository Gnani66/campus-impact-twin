import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-10 bg-slate-950 px-6 text-white">
      <div className="max-w-2xl text-center">
        <p className="text-xs font-medium uppercase tracking-[0.3em] text-cyan-400">
          Smart Campus Digital Twin
        </p>

        <h1 className="mt-5 text-4xl font-semibold leading-tight sm:text-5xl">
          Campus → Building → Floor →
          Zone → Sensors
        </h1>

        <p className="mt-5 text-slate-400">
          A real digital-twin entity graph served by
          FastAPI and backed by Supabase. The 3D model
          resolves to a real zone, and every zone resolves
          to its equipment and sensors.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-4">
        <Link
          href="/twin"
          className="rounded-xl bg-cyan-400 px-6 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300"
        >
          Open the 3D twin
        </Link>

        <Link
          href="/dashboard"
          className="rounded-xl border border-white/15 px-6 py-3 text-sm font-semibold transition hover:bg-white/5"
        >
          Campus command centre
        </Link>
      </div>
    </main>
  );
}
