"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

// Reveal hook — matches Nexdash data-motion stagger
function Reveal({ children, delay = 0, className = "" }: { children: React.ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [v, setV] = useState(false);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setV(true); io.disconnect(); } }, { threshold: 0.15 });
    io.observe(el); return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={className} style={{ opacity: v ? 1 : 0, transform: v ? "translateY(0)" : "translateY(26px)", transition: `opacity 0.6s ease ${delay}ms, transform 0.6s cubic-bezier(.22,1,.36,1) ${delay}ms` }}>
      {children}
    </div>
  );
}

export default function NexdashSmartCampus() {
  const [menu, setMenu] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    // globals.css sets html,body overflow:hidden for dashboard #app-scroll — unlock for landing window scroll
    const html = document.documentElement; const body = document.body;
    const prevHtmlOverflow = html.style.overflow; const prevBodyOverflow = body.style.overflow;
    const prevHtmlHeight = html.style.height; const prevBodyHeight = body.style.height;
    html.style.overflow = "auto"; body.style.overflow = "auto"; html.style.height = "auto"; body.style.height = "auto";
    const prevTitle = document.title;
    document.title = "SCEMS · Smart Campus Environmental Monitoring System";
    return () => { html.style.overflow = prevHtmlOverflow; body.style.overflow = prevBodyOverflow; html.style.height = prevHtmlHeight; body.style.height = prevBodyHeight; document.title = prevTitle; };
  }, []);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", on, { passive: true }); return () => window.removeEventListener("scroll", on);
  }, []);

  return (
    <div className="nd-site relative min-h-dvh overflow-x-clip bg-[#F3F5F4] text-[#07110B] antialiased">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
        :root{--nd-panel:#ECEFEE;--nd-panel-alt:#E8EDEB;--nd-band:#041C15;--nd-band-nexos:#08281E;--nd-bg:#F3F5F4;--nd-card:#FFFFFF;--nd-card-dark:#041C15;--nd-band-text:#FFFFFF;--nd-band-dim:rgba(255,255,255,0.72);--nd-text:#07110B;--nd-text-mid:#565C59;--nd-text-dim:#858B8C;--nd-hairline:#DFE3E1;--nd-chip-bg:#E6F0EC;--nd-chip-text:#0E5A56}
        .nd-display{font-family:'Instrument Sans',system-ui,sans-serif; font-weight:800; letter-spacing:-0.035em; line-height:0.98}
        .nd-h2{font-size:clamp(32px,4vw,44px); line-height:1.05}
        .nd-h3{font-size:22px; line-height:1.15; letter-spacing:-0.02em}
        .nd-body{font-family:'Instrument Sans',system-ui,sans-serif; font-size:16px; line-height:1.6}
        .nd-sub{font-size:20px; line-height:1.5}
        .nd-eyebrow{font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:0.16em; text-transform:uppercase}
        .nd-label{font-family:'Instrument Sans',system-ui,sans-serif; font-size:13px; font-weight:600; letter-spacing:0.04em}
        .nd-small{font-size:14px; line-height:1.5}
        .nd-mono{font-family:'JetBrains Mono',monospace}
        .nd-rail{scrollbar-width:none} .nd-rail::-webkit-scrollbar{display:none}
        html{scroll-behavior:smooth}
        /* reset globals overflow for landing */
        #zero-scroll{display:none}
      `}</style>

      {/* HEADER — exactly Nexdash sticky */}
      <header className={`sticky top-0 z-50 transition-[background-color,backdrop-filter,transform] duration-300 will-change-transform ${scrolled ? "bg-[#F3F5F4]/80 backdrop-blur-xl border-b border-[#DFE3E1]" : "bg-transparent"}`}>
        <div className="w-full pt-[21px] max-md:pt-[12px]">
          <div className="px-6 md:px-10 lg:px-[max(54px,3.75vw)]">
            <nav className="flex h-[84px] items-center justify-between gap-6 max-md:h-[52px]">
              <Link href="/" className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#041C15] text-white text-[11px] font-bold">SC</span>
                <span className="leading-none">
                  <span className="block text-[13px] font-extrabold tracking-[0.06em]">SMART CAMPUS</span>
                  <span className="hidden sm:block text-[10px] font-semibold tracking-[0.12em] text-[#565C59]">REAL-TIME INTELLIGENCE</span>
                </span>
              </Link>
              <div className="hidden items-center gap-10 lg:flex">
                <a href="#overview" className="nd-label hover:opacity-60 transition">Overview</a>
                <a href="#platform" className="nd-label hover:opacity-60 transition">Platform</a>
                <a href="#solutions" className="nd-label hover:opacity-60 transition">Solutions</a>
              </div>
              <div className="hidden items-center gap-6 lg:flex">
                <Link href="/dashboard" className="inline-flex items-center rounded-full bg-[#041C15] px-6 py-2.5 nd-label text-white hover:bg-[#0A2A20] active:scale-[0.97] transition">Live Dashboard</Link>
              </div>
              <button onClick={() => setMenu(!menu)} className="-mr-2 flex h-11 w-11 items-center justify-center lg:hidden" aria-label="Menu">
                <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M3 6h14M3 10h14M3 14h14" /></svg>
              </button>
            </nav>
          </div>
        </div>
        {menu && (
          <div className="border-t border-[#DFE3E1] bg-white px-6 py-6 lg:hidden">
            <a onClick={() => setMenu(false)} href="#overview" className="block py-2 nd-label">Overview</a>
            <a onClick={() => setMenu(false)} href="#platform" className="block py-2 nd-label">Platform</a>
            <a onClick={() => setMenu(false)} href="#solutions" className="block py-2 nd-label">Solutions</a>
            <Link onClick={() => setMenu(false)} href="/dashboard" className="mt-4 inline-flex rounded-full bg-[#041C15] px-6 py-3 nd-label text-white w-full justify-center">VIEW LIVE DASHBOARD ↗</Link>
          </div>
        )}
      </header>

      <main>
        {/* HERO — huge SMART CAMPUS like NEXDASH, iso hero depot */}
        <div className="w-full">
          <div className="relative overflow-hidden bg-[var(--nd-panel)] -mt-[105px] pt-[105px] lg:min-h-[max(720px,100svh)]">
            <div className="px-5 md:px-7 lg:px-[max(34px,2.361vw)] pb-20 pt-10 max-md:flex max-md:min-h-[calc(100svh-64px)] max-md:flex-col max-md:pb-6 max-md:pt-2 lg:pb-[clamp(80px,calc(100svh_-_733px),147px)] lg:pt-[71px]">
              <h1 className="nd-display z-10 text-center whitespace-nowrap text-[9.5vw] font-bold leading-[0.94] tracking-[-0.022em] text-[#041C15] sm:text-[9vw] lg:text-[min(10.5vw,20svh)] overflow-hidden">SMART CAMPUS</h1>

              <div className="mt-6 max-md:mt-0 max-md:flex max-md:grow max-md:flex-col lg:mt-[clamp(44px,calc(100svh_-_781px),99px)]">
                {/* hero image — user uploaded heroimage.png — enlarged */}
                <Reveal className="select-none lg:absolute lg:-bottom-[1vw] lg:right-[0%] lg:w-[70%] lg:max-w-[980px] flex items-center justify-center">
                  <img src="/heroimage.png" alt="Smart Campus hero" className="w-full h-auto max-h-[640px] lg:max-h-[600px] object-contain object-center drop-shadow-xl" style={{ objectFit: "contain" }} />
                </Reveal>
                <div className="relative z-10 max-w-[400px] max-md:mt-auto max-md:px-1">
                  <Reveal><p className="nd-display max-w-[340px] text-[30px] font-bold leading-[1.12] tracking-[-0.035em] max-md:text-[clamp(42px,12vw,52px)] md:text-[33px]">The campus is alive.</p></Reveal>
                  <Reveal delay={100}><p className="mt-4 max-w-[420px] nd-body text-[#07110B] max-md:mt-5 max-md:text-[18px] max-md:leading-[1.45] max-md:text-[#565C59]">Real-time intelligence for a smarter, safer and more sustainable campus — environmental, energy and infrastructure connected through live IoT.</p></Reveal>
                  <Reveal delay={200}>
                    <div className="mt-8 flex flex-wrap items-center gap-6 max-md:mt-6">
                      <Link href="/dashboard" className="inline-flex items-center justify-center rounded-full font-bold tracking-[0.02em] px-6 py-3 nd-label md:px-7 bg-[#041C15] text-white hover:bg-[#0A2A20]">View live dashboard</Link>
                      <a href="#platform" className="group inline-flex items-center gap-1.5 px-1 nd-label hover:opacity-70">See how it works →</a>
                    </div>
                  </Reveal>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* THE BIGGEST INDUSTRY — becomes THE BIGGEST CAMPUS CHALLENGE */}
        <div id="overview" className="w-full">
          <div className="px-6 md:px-10 lg:px-[max(54px,3.75vw)] pb-14 pt-12 max-md:pt-14 md:pb-24 md:pt-24 lg:pb-[91px] lg:pt-[91px]">
            <Reveal><h2 className="nd-display nd-h2 max-w-[710px]">The biggest campus nobody is monitoring.</h2></Reveal>
            <div className="mt-8 grid gap-12 md:mt-12 lg:mt-[92px] lg:grid-cols-[536px_544px] lg:justify-between">
              <Reveal className="nd-body space-y-6 text-[#07110B]">
                <p>Every corridor, lab, and courtyard emits data — yet most campuses run blind. Fragmented sensors, disconnected systems, and delayed response keep energy, air quality and safety invisible until it’s too late.</p>
                <p>The opportunity isn&apos;t one more dashboard. It&apos;s rebuilding the operating model: unifying IoT, streaming live telemetry, and running the campus on real intelligence.</p>
              </Reveal>
              <Reveal delay={120}>
                <div className="space-y-9">
                  <div>
                    <p className="nd-eyebrow">Powered by</p>
                    <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-5">
                      {["ESP32","BME280","ENS160","BH1750","MQTT","FastAPI","PostgreSQL"].map(t=> <span key={t} className="rounded-full border border-[#DFE3E1] bg-white px-3 py-1.5 nd-eyebrow text-[#07110B]">{t}</span>)}
                    </div>
                  </div>
                  <div>
                    <p className="nd-eyebrow">Live metrics</p>
                    <div className="mt-5 flex flex-wrap gap-3 nd-small">
                      <span className="rounded-full bg-[#041C15] px-3 py-1.5 text-white font-semibold">24.3°C Temperature</span>
                      <span className="rounded-full border border-[#DFE3E1] bg-white px-3 py-1.5">61% Humidity</span>
                      <span className="rounded-full border border-[#DFE3E1] bg-white px-3 py-1.5">AQI 38 Good</span>
                      <span className="rounded-full border border-[#DFE3E1] bg-white px-3 py-1.5">12.8kW Energy</span>
                      <span className="rounded-full bg-[#E6F0EC] px-3 py-1.5 font-semibold text-[#0E5A56]">18/18 Online</span>
                    </div>
                  </div>
                </div>
              </Reveal>
            </div>
          </div>
        </div>

        {/* Full width image — user uploaded secondimage.jpg — full bleed */}
        <div className="w-full">
          <div className="relative overflow-hidden bg-transparent">
            <div className="relative w-full h-[56vw] min-h-[320px] max-h-[720px]">
              <img src="/secondimage.jpg" alt="Smart Campus" className="absolute inset-0 h-full w-full object-cover" />

            </div>
          </div>
        </div>

        {/* WHAT SETS SMART CAMPUS APART — 4 features */}
        <div id="platform" className="w-full">
          <div className="px-6 md:px-10 lg:px-[max(54px,3.75vw)] pb-10 pt-12 md:pb-20 md:pt-20 lg:pb-[70px] lg:pt-[100px]">
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,560px)] lg:gap-14">
              <div>
                <Reveal><h2 className="nd-display nd-h2">What sets Smart Campus apart.</h2></Reveal>
                <Reveal delay={100}><img src="/image3.png" alt="Smart Campus" className="mt-10 w-full max-w-[720px] rounded-[18px] h-[520px] object-contain bg-[#F3F5F4] lg:mt-[60px]" /></Reveal>
              </div>
              <div className="space-y-8 lg:pt-[72px]">
                {[
                  ["Vertically integrated","Sensors, MQTT, processing and dashboard in one stack. Not a marketplace — we own the signal end-to-end."],
                  ["AI-native insight","Live telemetry gets smarter with every reading, turning raw sensor data into lower cost and higher awareness."],
                  ["Zero-waste intelligence","We track energy and environment route by route, cutting waste every hour with live kW / AQI trends."],
                  ["Built for action","We unify fragmented campus data into one view designed to respond today and automate tomorrow."],
                ].map(([t,d],i)=> <Reveal key={t} delay={i*80}><h3 className="nd-display nd-h3">{t}</h3><p className="nd-body mt-2">{d}</p></Reveal>)}
              </div>
            </div>
          </div>
        </div>

        {/* 3 cards — Sense / Connect / Understand like Acquire/Electrify/Run */}
        <div id="solutions" className="w-full">
          <div className="px-6 md:px-10 lg:px-[max(54px,3.75vw)] pb-10 md:pb-24 lg:pb-[25px]">
            <div className="grid gap-6 md:grid-cols-3">
              <Reveal><article className="relative flex h-full flex-col overflow-hidden rounded-[22px] px-8 pt-9 lg:px-12 lg:pt-12 bg-[var(--nd-card)] text-[#07110B] border border-[#DFE3E1]">
                <h3 className="nd-display nd-h3">Sense.</h3><p className="nd-body mt-3.5">We collect live campus data through sensors for air quality, temperature, light, rain, sound and more.</p>
                <img src="/sense.png" alt="Sense" className="mt-auto mx-auto w-full max-w-[420px] h-[440px] lg:h-[500px] object-contain object-center scale-[1.06]" />
              </article></Reveal>
              <Reveal delay={100}><article className="relative flex h-full flex-col overflow-hidden rounded-[22px] px-8 pt-9 lg:px-12 lg:pt-12 bg-[var(--nd-card-dark)] text-white">
                <h3 className="nd-display nd-h3">Connect.</h3><p className="nd-body mt-3.5 text-white/70">Sensor data flows into one system, turning every reading into a live view of the campus.</p>
                <img src="/understand.png" alt="Understand" className="mt-auto mx-auto w-full max-w-[420px] h-[440px] lg:h-[500px] object-contain object-center scale-[1.06]" />
              </article></Reveal>
              <Reveal delay={200}><article className="relative flex h-full flex-col overflow-hidden rounded-[22px] px-8 pt-9 lg:px-12 lg:pt-12 bg-[var(--nd-card)] border border-[#DFE3E1]">
                <h3 className="nd-display nd-h3">Run on SCEMS.</h3><p className="nd-body mt-3.5">Our platform brings data collection, alerts and visualization together — giving you real-time visibility across campus.</p>
                <img src="/runonscems.png" alt="Run on SCEMS" className="mt-auto mx-auto w-full max-w-[420px] h-[440px] lg:h-[500px] object-contain object-center scale-[1.06]" />
              </article></Reveal>
            </div>
          </div>
        </div>

        {/* Logistics Future is Now — Campus Future is Now */}
        <div className="w-full">
          <div className="relative overflow-hidden bg-[var(--nd-panel-alt)] lg:min-h-[520px]">
            <div className="px-5 md:px-7 lg:px-[max(34px,2.361vw)] pb-5 pt-10 text-center md:pt-20 lg:pt-[72px]">
              <Reveal><h2 className="nd-display nd-h2 mx-auto">Campus Future is Now.</h2></Reveal>
              <Reveal delay={100}><p className="nd-sub mx-auto mt-7 max-w-[900px]">Building the campus for the intelligent age: connected, electric, and data-operated.</p></Reveal>
            </div>
            <Reveal><img src="/finalimage.png" alt="Campus Future" className="w-full h-auto object-contain" /></Reveal>
          </div>
        </div>

        {/* Better economics → Better intelligence at every layer */}
        <div className="w-full bg-[#F3F5F4] pt-5 md:pt-6 lg:pt-[63px]">
          <div className="relative overflow-hidden bg-[#041C15] text-white pb-14 lg:pb-16">
            <div className="px-5 md:px-7 lg:px-[max(34px,2.361vw)] pt-8 md:pt-20 lg:pt-16">
              <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,600px)] lg:gap-x-16">
                <Reveal><h2 className="nd-display nd-h2 max-w-[596px]">Better intelligence at every layer.</h2></Reveal>
                <Reveal delay={100}><p className="nd-body max-w-[520px] text-white/70">More sensors compound. Mesh builds coverage, calibration and the live network. SCEMS increases utilization and lowers waste. Live AQI and energy already beat blind operation on every floor, with lower cost and faster response.</p></Reveal>
                <Reveal delay={200} className="lg:col-start-2 lg:max-w-[430px] lg:justify-self-end">
                  <p className="nd-display nd-h3 leading-[1.3] lg:text-right">Each layer reinforces the next, creating a more aware campus as it scales.</p>
                  <div className="mt-8 lg:flex lg:justify-end"><Link href="/dashboard" className="inline-flex items-center justify-center rounded-full font-bold px-7 py-3 nd-label bg-white text-[#07110B] hover:bg-[#EEF1F0]">View live dashboard</Link></div>
                </Reveal>
              </div>
            </div>
            <Reveal className="mt-14 w-full px-5 md:px-7 lg:mt-16 lg:flex lg:justify-center"><img src="https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1750&auto=format&fit=crop&q=80" alt="Tablet with dashboard" className="w-full lg:h-[46svh] lg:w-auto rounded-xl object-cover" /></Reveal>
          </div>
        </div>




        {/* SCEMS intelligence behind network */}
        <section id="nexos" className="w-full">
          <div className="px-6 md:px-10 lg:px-[max(54px,3.75vw)] pb-12 pt-10 md:pt-20 lg:pb-16 lg:pt-[104px]">
            <div className="grid gap-6 lg:grid-cols-[minmax(0,700px)_minmax(0,1fr)] lg:gap-16">
              <Reveal><h2 className="nd-display nd-h2 max-w-[824px]">SCEMS: the intelligence behind the campus.</h2></Reveal>
              <div>
                <Reveal delay={100}><p className="nd-body max-w-[520px]">SCEMS is the platform at the heart of every campus operation, orchestrating environment, energy and safety in real time. Once a sensor joins the mesh, SCEMS runs its insight:</p></Reveal>
                <Reveal delay={200}><div className="mt-8 flex flex-wrap items-center gap-6"><Link href="/dashboard" className="inline-flex rounded-full px-7 py-3 nd-label bg-[#041C15] text-white">View live dashboard</Link></div></Reveal>
              </div>
            </div>
          </div>
        </section>

      </main>

      {/* FOOTER — huge SMART CAMPUS like NEXDASH */}
      <div className="w-full pb-5 lg:pb-[29px]">
        <div className="relative overflow-hidden bg-[#041C15] text-white lg:h-[340px]">
          <div className="px-5 md:px-7 lg:px-[max(34px,2.361vw)] flex flex-col gap-10 pb-10 pt-12 md:pb-14 md:pt-16 lg:grid lg:h-full lg:grid-cols-[auto_auto] lg:items-start lg:justify-between lg:pb-[46px] lg:pt-[56px]">
            <span className="nd-display block text-[17vw] font-bold leading-[0.8] tracking-[-0.045em] lg:text-[clamp(72px,9.2vw,132px)]">SMART CAMPUS</span>
            <div className="grid grid-cols-2 gap-x-10 gap-y-10 sm:grid-cols-2 lg:gap-x-[74px]">
              <div className="flex flex-col gap-4"><span className="nd-small text-white/60">Company</span><Link href="/dashboard" className="nd-label text-white hover:opacity-70">Live Dashboard</Link><a href="#overview" className="nd-label text-white hover:opacity-70">Overview</a></div>
              <div className="flex flex-col gap-4"><span className="nd-small text-white/60">Platform</span><Link href="/dashboard" className="nd-label text-white hover:opacity-70">SCEMS</Link><a href="#platform" className="nd-label text-white hover:opacity-70">How it works</a></div>
            </div>
            <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between lg:col-span-2 nd-small text-white/60 border-t border-white/10 pt-6 mt-2">
              <span>© 2026 SCEMS. All rights reserved.</span>
              <span className="flex items-center gap-1">Crafted with <span className="text-[#FF4D4D]">♥</span> by Gnanesh</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
