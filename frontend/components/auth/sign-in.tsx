"use client";

import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Eye,
  EyeOff,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Mark } from "@/components/marketing/mark";

export function SignIn() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !email.includes("@")) {
      setError("Enter a valid work email.");
      return;
    }
    if (!password) {
      setError("Enter your password.");
      return;
    }

    sessionStorage.setItem("forecast_hub_identity", email.trim());
    router.push("/dashboard");
  }

  return (
    <main className="forecast-landing min-h-screen bg-[#f1f3ef] text-[#111512]">
      <div className="grid min-h-screen lg:grid-cols-[minmax(0,0.88fr)_minmax(560px,1.12fr)]">
        <section className="relative hidden overflow-hidden bg-[#111512] px-10 py-9 text-white lg:flex lg:flex-col xl:px-16 xl:py-12">
          <div className="pointer-events-none absolute inset-0 opacity-70" aria-hidden>
            <div className="absolute -left-24 top-20 size-80 rounded-full bg-[#287b59]/25 blur-3xl" />
            <div className="absolute -right-24 bottom-0 size-96 rounded-full bg-[#9c8760]/20 blur-3xl" />
          </div>

          <Link href="/" className="relative flex w-fit items-center gap-3" aria-label="Forecast Hub home">
            <Mark size={30} />
            <span className="text-site-h3 font-bold">Forecast Hub</span>
          </Link>

          <div className="relative my-auto max-w-[34rem] py-16">
            <p className="font-mono text-site-caption uppercase tracking-[0.2em] text-[#7fbea1]">Your planning workspace</p>
            <h1 className="mt-5 max-w-[11ch] text-balance font-display text-[clamp(3.25rem,5vw,5.6rem)] font-normal leading-[0.98] tracking-[-0.035em]">
              Turn uncertainty into a decision.
            </h1>
            <p className="mt-6 max-w-[44ch] text-site-lead text-[#b9bdb9]">
              Every forecast, scenario, and insight stays connected to the evidence that produced it.
            </p>

            <div className="mt-10 border border-white/15 bg-white/[0.035]">
              <div className="flex items-center justify-between border-b border-white/15 px-5 py-4">
                <div className="flex items-center gap-2.5">
                  <Sparkles className="size-4 text-[#7fbea1]" aria-hidden />
                  <span className="text-site-body font-medium">Latest decision brief</span>
                </div>
                <span className="font-mono text-[0.68rem] uppercase tracking-[0.13em] text-[#858b86]">Updated now</span>
              </div>
              <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 p-5">
                <span className="flex size-9 items-center justify-center bg-[#1d3027] text-[#7fbea1]"><BarChart3 className="size-4" aria-hidden /></span>
                <div>
                  <p className="text-site-body font-semibold">Demand holds above plan</p>
                  <p className="mt-1 text-site-body text-[#aeb4af]">Base demand is 6.8% higher over the next eight weeks.</p>
                </div>
              </div>
            </div>
          </div>

          <div className="relative flex flex-wrap gap-x-6 gap-y-2 font-mono text-[0.7rem] text-[#858b86]">
            <span className="inline-flex items-center gap-1.5"><CheckCircle2 className="size-3.5 text-[#7fbea1]" aria-hidden /> Backtested forecasts</span>
            <span className="inline-flex items-center gap-1.5"><ShieldCheck className="size-3.5 text-[#7fbea1]" aria-hidden /> Traceable insights</span>
          </div>
        </section>

        <section className="relative flex min-h-screen flex-col px-5 py-6 sm:px-10 sm:py-8 lg:px-14 xl:px-24">
          <div className="flex items-center justify-between gap-4">
            <Link href="/" className="inline-flex min-h-11 items-center gap-2 text-site-body font-medium text-[#59605a] transition-colors hover:text-[#111512]">
              <ArrowLeft className="size-4" aria-hidden /> Back home
            </Link>
            <div className="flex items-center gap-2 lg:hidden">
              <Mark size={24} />
              <span className="text-site-body font-bold">Forecast Hub</span>
            </div>
          </div>

          <div className="my-auto w-full max-w-[29rem] self-center py-12">
            <p className="font-mono text-site-caption uppercase tracking-[0.18em] text-[#287b59]">Workspace access</p>
            <h2 className="mt-4 font-display text-[clamp(2.5rem,6vw,4rem)] font-normal leading-[1.02] tracking-[-0.03em]">Welcome back.</h2>
            <p className="mt-4 text-site-lead text-[#59605a]">Sign in to review forecasts, scenarios, and the decisions waiting for you.</p>

            <form onSubmit={submit} className="mt-9 space-y-5" noValidate>
              <label className="block">
                <span className="font-mono text-site-caption font-medium uppercase tracking-[0.1em] text-[#4f5650]">Work email</span>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => {
                    setEmail(event.target.value);
                    setError("");
                  }}
                  autoComplete="email"
                  placeholder="you@company.com"
                  className="mt-2 h-14 w-full border border-[#bfc7bf] bg-[#fafbf9] px-4 text-[1rem] outline-none transition-[border-color,box-shadow] placeholder:text-[#929992] focus:border-[#287b59] focus:shadow-[0_0_0_3px_rgba(40,123,89,.12)]"
                />
              </label>

              <label className="block">
                <span className="font-mono text-site-caption font-medium uppercase tracking-[0.1em] text-[#4f5650]">Password</span>
                <span className="relative mt-2 block">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      setError("");
                    }}
                    autoComplete="current-password"
                    placeholder="Enter your password"
                    className="h-14 w-full border border-[#bfc7bf] bg-[#fafbf9] px-4 pr-12 text-[1rem] outline-none transition-[border-color,box-shadow] placeholder:text-[#929992] focus:border-[#287b59] focus:shadow-[0_0_0_3px_rgba(40,123,89,.12)]"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((visible) => !visible)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-[#6f766f] hover:text-[#111512]"
                  >
                    {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                  </button>
                </span>
              </label>

              {error ? <p role="alert" className="border-l-2 border-[#aa453f] bg-[#f3e5e2] px-3 py-2 text-site-body text-[#8f3833]">{error}</p> : null}

              <button type="submit" className="group flex h-14 w-full items-center justify-center gap-3 bg-[#111512] px-6 text-site-body font-semibold text-white transition-colors hover:bg-[#242a25]">
                Sign in <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
              </button>
            </form>

            <div className="mt-6 flex items-center gap-3 text-site-body text-[#737a73]">
              <span className="h-px flex-1 bg-[#cfd5cf]" />
              <span>or preview without an account</span>
              <span className="h-px flex-1 bg-[#cfd5cf]" />
            </div>

            <Link href="/dashboard" className="mt-5 flex h-14 w-full items-center justify-center border border-[#bfc7bf] bg-[#fafbf9] px-6 text-site-body font-semibold text-[#343a35] transition-colors hover:border-[#8f9a90] hover:bg-white">
              Explore the live workspace
            </Link>

            <p className="mt-6 text-center text-site-caption text-[#7a817b]">
              This preview keeps sign-in details in this browser session only.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}
