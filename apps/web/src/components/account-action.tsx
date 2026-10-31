"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, AudioLines } from "lucide-react";
import { api, command } from "@/lib/api";
export default function AccountAction({
  mode,
}: {
  mode: "forgot" | "reset" | "invite";
}) {
  const [token, setToken] = useState(""),
    [error, setError] = useState(""),
    [done, setDone] = useState(""),
    [busy, setBusy] = useState(false),
    [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token") || "");
    if (mode === "invite")
      api("/v1/auth/me")
        .then(() => setSignedIn(true))
        .catch(() => {});
  }, [mode]);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget).entries());
    try {
      if (mode === "forgot") {
        const r = await command("/v1/auth/forgot-password", data);
        setDone(
          r.message +
            (r.delivery === "development-outbox"
              ? " This development server saves email privately in its mail outbox."
              : ""),
        );
      }
      if (mode === "reset") {
        const r = await command("/v1/auth/reset-password", { ...data, token });
        setDone(r.message);
      }
      if (mode === "invite") {
        const r = await command("/v1/auth/accept-invitation", { token });
        localStorage.setItem("studio.workspace", r.workspace_id);
        window.location.assign("/app");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-form-wrap" style={{ minHeight: "100dvh" }}>
      <section className="auth-form">
        <Link href="/" className="brand">
          <AudioLines />
          Phirmy
        </Link>
        <h2>
          {mode === "forgot"
            ? "Let’s get you back in."
            : mode === "reset"
              ? "A fresh start."
              : "You’re invited."}
        </h2>
        <p className="muted">
          {mode === "invite"
            ? "Join a workspace with the email address your invitation was sent to."
            : mode === "forgot"
              ? "Enter your email for a private reset link."
              : "Choose a new password. Your previous sessions will be signed out."}
        </p>
        {done ? (
          <div className="notice" role="status" style={{ marginTop: 25 }}>
            {done}
          </div>
        ) : (
          <form onSubmit={submit}>
            {mode === "forgot" && (
              <label>
                Email
                <input
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                />
              </label>
            )}
            {mode === "reset" && (
              <label>
                New password
                <input
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={12}
                  maxLength={256}
                />
              </label>
            )}
            {mode === "invite" && !signedIn ? (
              <p className="notice">
                Sign in or create an account with the invited email, then return
                to this link to accept.
              </p>
            ) : (
              <button
                className="btn primary"
                disabled={
                  busy || ((mode === "reset" || mode === "invite") && !token)
                }
              >
                {busy
                  ? "Working…"
                  : mode === "forgot"
                    ? "Send reset link"
                    : mode === "reset"
                      ? "Update password"
                      : "Join workspace"}
                <ArrowRight size={16} />
              </button>
            )}
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
          </form>
        )}
        <p style={{ marginTop: 24 }}>
          <Link href="/signin" className="table-action">
            Go to sign in
            <ArrowRight size={14} />
          </Link>
        </p>
      </section>
    </main>
  );
}
