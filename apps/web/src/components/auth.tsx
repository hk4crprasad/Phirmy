"use client";
import { useState, useEffect } from "react";
import {
  ArrowUpRight,
  AudioLines,
  ArrowRight,
  ShieldCheck,
  LogIn,
} from "lucide-react";
import { command, api } from "@/lib/api";
import Link from "next/link";
import AuthParticles from "@/components/auth-particles";
import ThemeSwitcher from "./theme-switcher";
import { legalPolicy, legalDocuments } from "@/lib/legal";
import { LoadingMark } from "./loading-state";

export default function Auth() {
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [keep, setKeep] = useState(false),
    [previewName, setPreviewName] = useState("");
  const [legalAccepted, setLegalAccepted] = useState(false);
  const [google, setGoogle] = useState(false);
  useEffect(() => {
    api("/v1/auth/providers")
      .then((result) => setGoogle(result.google))
      .catch(() => {});
    const authError = new URLSearchParams(window.location.search).get(
      "auth_error",
    );
    const errors: Record<string, string> = {
      legal_acceptance_required:
        "Create an account and accept the current Terms and Privacy notice before signing up with Google.",
      google_link_required:
        "An account already uses this email. Sign in with your password, then connect Google in your profile.",
      google_account_mismatch:
        "Choose the Google account that matches your profile email.",
      google_state: "That sign-in attempt expired. Please try again.",
      google_expired: "That sign-in attempt expired. Please try again.",
      google_unavailable: "Google sign-in could not finish. Please try again.",
    };
    if (authError === "legal_acceptance_required") setRegister(true);
    if (authError)
      setError(
        errors[authError] || "Sign-in could not finish. Please try again.",
      );
    const keeping = new URLSearchParams(window.location.search).has("keep");
    setKeep(keeping);
    if (keeping) {
      setRegister(true);
      try {
        setPreviewName(
          JSON.parse(sessionStorage.getItem("studio.preview") || "{}").name ||
            "",
        );
      } catch {}
    }
  }, []);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      let account = await command(
        "/v1/auth/" + (register ? "signup" : "signin"),
        register
          ? {
              ...Object.fromEntries(form.entries()),
              legal_accepted: legalAccepted,
              legal_version: legalPolicy.version,
            }
          : Object.fromEntries(form.entries()),
      );
      if (register && account.verification_required) {
        window.location.assign("/verify-email" + (keep ? "?keep=1" : ""));
        return;
      }
      if (register) {
        account = await command("/v1/auth/signin", {
          email: form.get("email"),
          password: form.get("password"),
        });
      }
      if (account.user?.verification_required) {
        window.location.assign("/verify-email" + (keep ? "?keep=1" : ""));
        return;
      }
      if (keep) {
        try {
          const me = account.workspace ? account : await api("/v1/auth/me");
          const ws = me.workspace?.id || me.workspaces?.[0]?.id;
          const saved = await command(
            "/v1/workspaces/" + ws + "/preview/claim",
          );
          sessionStorage.removeItem("studio.preview");
          localStorage.setItem("studio.workspace", ws);
          window.location.assign("/app/agents/" + saved.agent_id);
          return;
        } catch {
          window.location.assign("/app?savePreview=1");
          return;
        }
      }
      window.location.assign("/app");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <main className="auth-shell">
      <section className="auth-story">
        <AuthParticles />
        <div className="brand">
          <span className="brand-icon">
            <AudioLines size={22} />
          </span>{" "}
          Phirmy
        </div>
        <div className="auth-manifesto">
          <div className="eyebrow">A LITTLE MORE HUMAN.</div>
          <h1>
            Good conversations.
            <br />
            Real possibilities.
          </h1>
          <p>
            Give your business a voice that listens.
            <br />
            Grounded in your knowledge. Ready to help.
          </p>
        </div>
        <div className="auth-footer">
          <span>YOUR KNOWLEDGE. YOUR VOICE.</span>
          <ArrowUpRight size={18} />
        </div>
      </section>
      <section className="auth-form-wrap">
        <div className="auth-theme">
          <ThemeSwitcher />
        </div>
        <div className="auth-form">
          <div className="eyebrow muted">
            {keep ? "KEEP THE MOMENTUM" : "WELCOME TO YOUR WORKSPACE"}
          </div>
          <h2>
            {keep
              ? "Your assistant is ready to keep."
              : register
                ? "Make yourself heard."
                : "Pick up where you left off."}
          </h2>
          <p className="muted">
            {keep
              ? "Save " +
                (previewName || "your website assistant") +
                " with its knowledge already connected."
              : register
                ? "Create your account and build your first agent."
                : "Sign in to manage your agents and conversations."}
          </p>
          <button
            className="btn wide google-signin"
            disabled={!google || busy || (register && !legalAccepted)}
            onClick={async () => {
              setError("");
              setBusy(true);
              try {
                if (register)
                  await command("/v1/auth/signup-intent", {
                    legal_accepted: legalAccepted,
                    legal_version: legalPolicy.version,
                  });
                window.location.assign(
                  "/backend/v1/auth/google/start?return_to=" +
                    encodeURIComponent(keep ? "/app?savePreview=1" : "/app"),
                );
              } catch (e) {
                setError((e as Error).message);
                setBusy(false);
              }
            }}
          >
            <LogIn size={17} /> Continue with Google
          </button>
          {!google && (
            <p className="field-note" style={{ textAlign: "center" }}>
              Google sign-in is being connected.
            </p>
          )}
          <div className="auth-divider">
            <span>or continue with email</span>
          </div>
          <form onSubmit={submit}>
            {register && (
              <label>
                Your name
                <input
                  name="name"
                  autoComplete="name"
                  placeholder="Alex Morgan"
                  required
                  maxLength={120}
                />
              </label>
            )}
            <label>
              Work email
              <input
                name="email"
                type="email"
                autoComplete="email"
                placeholder="you@company.com"
                required
              />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                placeholder={
                  register ? "At least 12 characters" : "Your password"
                }
                required
                minLength={register ? 12 : 1}
                maxLength={256}
              />
            </label>
            {register && (
              <label>
                Workspace name
                <input
                  name="workspace_name"
                  placeholder="Your company"
                  defaultValue={previewName}
                  required
                  maxLength={120}
                />
              </label>
            )}
            {register && (
              <div className="signup-legal">
                <p className="muted">
                  {legalPolicy.status === "DRAFT"
                    ? "DRAFT: legal documents await lawyer review."
                    : "Review the Terms and Privacy notice."}
                </p>
                <label>
                  <input
                    type="checkbox"
                    name="legal_accepted"
                    value="true"
                    checked={legalAccepted}
                    onChange={(e) => setLegalAccepted(e.target.checked)}
                    required
                  />
                  <span>
                    I accept the{" "}
                    <Link href="/legal/terms" target="_blank">
                      {legalPolicy.status} Terms
                    </Link>{" "}
                    and acknowledge the{" "}
                    <Link href="/legal/privacy" target="_blank">
                      {legalPolicy.status} Privacy notice
                    </Link>{" "}
                    (version {legalPolicy.version}).
                  </span>
                </label>
              </div>
            )}
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            <button className="btn primary wide" disabled={busy}>
              {busy && <LoadingMark />}
              {busy ? "Connecting…" : register ? "Create workspace" : "Sign in"}
              <ArrowRight size={17} />
            </button>
          </form>
          <p className="auth-switch">
            {register ? "Already have an account?" : "New here?"}{" "}
            <button
              onClick={() => {
                setRegister(!register);
                setError("");
              }}
            >
              {register ? "Sign in" : "Create a workspace"}
            </button>
          </p>
          {!register && (
            <p style={{ textAlign: "center", marginTop: 16, fontSize: 12 }}>
              <Link href="/forgot-password">Forgot your password?</Link>
            </p>
          )}
          <nav className="auth-legal-links" aria-label="Legal documents">
            {Object.entries(legalDocuments).map(([id, doc]) => (
              <Link key={id} href={`/legal/${id}`}>
                {doc.title}
              </Link>
            ))}
          </nav>
          <div className="auth-trust">
            <ShieldCheck size={15} /> Private workspace · Your data stays yours
          </div>
        </div>
      </section>
    </main>
  );
}
