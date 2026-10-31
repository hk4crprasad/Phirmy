"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AudioLines, ArrowRight, MailCheck, RefreshCw } from "lucide-react";
import { api, command } from "@/lib/api";

export default function VerifyEmail() {
  const [email, setEmail] = useState(""),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  const [verified, setVerified] = useState(false),
    [busy, setBusy] = useState(false),
    [keep, setKeep] = useState(false);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const params = new URLSearchParams(window.location.search),
      token = params.get("token");
    setKeep(params.has("keep") || !!sessionStorage.getItem("studio.preview"));
    api("/v1/auth/me")
      .then((r) => {
        setEmail(r.user.email);
        if (r.user.email_verified) setVerified(true);
      })
      .catch(() => {});
    if (token) {
      setBusy(true);
      command("/v1/auth/verify-email", { token })
        .then((r) => {
          setMessage(r.message);
          setVerified(true);
          history.replaceState(null, "", "/verify-email");
        })
        .catch((e) => setError(e.message))
        .finally(() => setBusy(false));
    }
  }, []);
  return (
    <main className="auth-form-wrap" style={{ minHeight: "100dvh" }}>
      <section className="auth-form verification-card">
        <Link href="/" className="brand">
          <AudioLines /> Phirmy
        </Link>
        <div className="verification-mark">
          <MailCheck size={30} />
        </div>
        <div className="eyebrow">ONE QUICK STEP</div>
        <h1>{verified ? "You’re ready to build." : "Check your inbox."}</h1>
        <p className="muted">
          {verified
            ? "Your email is verified. Your first agent is waiting."
            : "Open the verification link" +
              (email ? " we sent to " + email : " in your email") +
              ". It keeps your workspace yours."}
        </p>
        {busy && <p role="status">Verifying your email…</p>}
        {message && (
          <div className="notice" role="status">
            {message}
          </div>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {verified ? (
          <Link
            className="btn primary wide"
            href={keep ? "/app?savePreview=1" : "/app"}
          >
            Open my workspace <ArrowRight size={16} />
          </Link>
        ) : (
          <button
            className="btn wide"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                const r = await command("/v1/auth/verification-email");
                setMessage(r.message);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <RefreshCw size={16} />
            Send another link
          </button>
        )}
        <p className="small-text muted">
          Check your spam folder, or return to{" "}
          <Link href="/signin" className="table-action">
            sign in
          </Link>
          .
        </p>
      </section>
    </main>
  );
}
