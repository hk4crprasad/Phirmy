"use client";
import { useEffect, useRef, useState } from "react";
import { Mic, Square, ArrowLeft, AudioLines, ShieldCheck } from "lucide-react";
import { VoiceConnection } from "@/lib/voice-connection";

export default function PublicVoice({ publicId }: { publicId: string }) {
  const [token, setToken] = useState(""),
    [state, setState] = useState("idle"),
    [error, setError] = useState(""),
    [turns, setTurns] = useState<{ role: string; text: string }[]>([]),
    [partial, setPartial] = useState("");
  const pageUrl = useRef<string | undefined>(undefined);
  const connection = useRef<VoiceConnection | null>(null),
    parentOrigin = useRef(""),
    end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const authorize = (event: MessageEvent) => {
      if (
        event.source !== window.parent ||
        event.data?.type !== "voice-studio:authorize" ||
        typeof event.data.token !== "string"
      )
        return;
      try {
        const raw = event.data.token
            .split(".")[0]
            .replace(/-/g, "+")
            .replace(/_/g, "/"),
          claims = JSON.parse(atob(raw));
        if (
          claims.aud !== "widget" ||
          claims.origin !== event.origin ||
          claims.exp * 1000 <= Date.now()
        )
          return;
        parentOrigin.current = event.origin;
        pageUrl.current =
          typeof event.data.page_url === "string"
            ? event.data.page_url
            : undefined;
        setToken(event.data.token);
      } catch {}
    };
    window.addEventListener("message", authorize);
    const stop = () => { void connection.current?.stop(); };
    window.addEventListener("pagehide", stop);
    window.parent.postMessage({ type: "voice-studio:ready" }, "*");
    return () => {
      window.removeEventListener("message", authorize);
      window.removeEventListener("pagehide", stop);
      connection.current?.stop();
    };
  }, []);
  useEffect(() => {
    const transcript = end.current?.parentElement;
    transcript?.scrollTo({
      top: transcript.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [turns, partial]);
  const running = !["idle", "ended"].includes(state);
  return (
    <section className="public-voice">
      <div className="public-voice-heading">
        <AudioLines size={18} />
        <strong>Speak with this agent</strong>
        <button
          className="icon-button"
          aria-label="Back to chat"
          onClick={() => {
            connection.current?.stop();
            if (parentOrigin.current)
              window.parent.postMessage(
                { type: "voice-studio:close" },
                parentOrigin.current,
              );
          }}
        >
          <ArrowLeft size={17} />
        </button>
      </div>
      <div className={"public-voice-orb " + (running ? "active" : "")}>
        <AudioLines size={35} />
      </div>
      <h2>
        {state === "idle" || state === "ended"
          ? "A conversation starts here."
          : state === "permission"
            ? "Allow microphone access…"
          : state === "connecting"
            ? "Connecting…"
            : state === "speaking"
              ? "Speaking…"
              : state === "thinking"
                ? "One moment…"
                : "Listening…"}
      </h2>
      <p className="muted small-text">
        {state === "permission"
          ? "Choose Allow in your browser’s microphone prompt to begin."
          : running
          ? "You can speak naturally and interrupt."
          : "You’re speaking with an AI assistant. Your microphone is used only during the conversation."}
      </p>
      <div className="public-voice-transcript" aria-live="polite">
        {turns.slice(-30).map((turn, index) => (
          <p key={index} className={turn.role === "user" ? "user" : ""}>
            <strong>{turn.role === "user" ? "You" : "Agent"}</strong>
            {turn.text}
          </p>
        ))}
        {partial && <p className="muted">{partial}</p>}
        <div ref={end} />
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {running ? (
        <button
          className="btn primary wide"
          onClick={() => connection.current?.stop()}
        >
          <Square size={15} />
          End conversation
        </button>
      ) : (
        <button
          className="btn primary wide"
          disabled={!token}
          onClick={() => {
            setError("");
            setTurns([]);
            setPartial("");
            connection.current = new VoiceConnection(
              publicId,
              token,
              {
                website: (data) =>
                  window.parent.postMessage(
                    {
                      type: "voice-studio:website",
                      actions: data.actions,
                      products: data.products,
                    },
                    parentOrigin.current,
                  ),
                state: setState,
                error: setError,
                transcript: (role, text, final) => {
                  if (final) {
                    setTurns((old) => [...old, { role, text }]);
                    setPartial("");
                  } else setPartial(text);
                },
              },
              pageUrl.current,
            );
            connection.current.start();
          }}
        >
          <Mic size={16} />
          Start voice conversation
        </button>
      )}
      {!token && (
        <p className="field-note">
          Open this agent from its website to start a conversation.
        </p>
      )}
      <p className="public-voice-privacy">
        <ShieldCheck size={12} />
        Microphone stops when you end or close this conversation.
      </p>
    </section>
  );
}
