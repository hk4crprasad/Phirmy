"use client";
import { useState, useEffect, useRef } from "react";
import { Send, RefreshCw } from "lucide-react";
import { Row, money, authenticatedFetch } from "@/lib/api";
import { botToken } from "@/lib/bot-challenge";
import { checkMicrophone, microphoneError } from "@/lib/microphone";
import WidgetEmailVerification from "./widget-email-verification";

export default function WidgetChat({
  publicId,
  publicKey = "",
  dashboardPreview = false,
}: {
  publicId: string;
  publicKey?: string;
  dashboardPreview?: boolean;
}) {
  const [session, setSession] = useState<Row | null>(null),
    [messages, setMessages] = useState<Row[]>([]),
    [input, setInput] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [definitions, setDefinitions] = useState<Row[]>([]),
    [variables, setVariables] = useState<Row>({});
  const [email, setEmail] = useState(""),
    [emailRequired, setEmailRequired] = useState(false);
  const [state, setState] = useState("open"),
    [voiceStatus, setVoiceStatus] = useState("");
  const recording = useRef<MediaRecorder | null>(null),
    stream = useRef<MediaStream | null>(null),
    recordingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const end = useRef<HTMLDivElement | null>(null);
  const chatController = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const challengeRoot = useRef<HTMLDivElement | null>(null);
  busyRef.current = busy;
  const voiceEpoch = useRef(0), voiceBusy = useRef(false);
  const [voicePending, setVoicePending] = useState(false);
  function releaseRecording() {
    if (recordingTimer.current) clearTimeout(recordingTimer.current);
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }
  async function voiceInput() {
    if (recording.current?.state === "recording") {
      recording.current.stop();
      return;
    }
    if (voiceBusy.current || !session) return;
    const epoch = ++voiceEpoch.current;
    voiceBusy.current = true;
    setVoicePending(true);
    setError("");
    setVoiceStatus("Allow microphone access in your browser to begin.");
    try {
      checkMicrophone();
      if (!window.MediaRecorder) throw Error("Voice recording is unavailable in this browser. Please type your message.");
      const captured = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (epoch !== voiceEpoch.current) {
        captured.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = captured;
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      if (!mime) throw Error("Voice input is unavailable in this browser");
      const recorder = new MediaRecorder(captured, { mimeType: mime }), chunks: Blob[] = [];
      recording.current = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        if (epoch !== voiceEpoch.current) return;
        releaseRecording();
        setVoicePending(true);
        setVoiceStatus("Transcribing…");
        try {
          const response = await fetch("/backend/v1/public/voice/transcribe", {
            method: "POST", credentials: "omit",
            headers: { "Content-Type": mime, Authorization: "Bearer " + session.session_token },
            body: new Blob(chunks, { type: mime }), signal: AbortSignal.timeout(45000),
          });
          const result = await response.json();
          if (epoch !== voiceEpoch.current) return;
          if (!response.ok) throw Error(typeof result.detail === "string" ? result.detail : "Transcription failed");
          if (!result.text) throw Error("No speech detected. Try again or type your message.");
          setInput((old) => (old + " " + result.text).trim().slice(0, 8000));
          setVoiceStatus("Review your message, then send.");
        } catch (e) {
          if (epoch === voiceEpoch.current) { setError((e as Error).message); setVoiceStatus(""); }
        } finally {
          if (epoch === voiceEpoch.current) { voiceBusy.current = false; setVoicePending(false); }
        }
      };
      recorder.onerror = () => {
        if (epoch !== voiceEpoch.current) return;
        voiceEpoch.current++;
        recorder.onstop = null;
        if (recorder.state === "recording") recorder.stop();
        releaseRecording();
        voiceBusy.current = false;
        setVoicePending(false);
        setVoiceStatus("");
        setError("Recording stopped unexpectedly. Check your microphone and try again.");
      };
      recorder.start();
      setVoicePending(false);
      setVoiceStatus("Listening… tap stop when finished.");
      recordingTimer.current = setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, 30000);
    } catch (e) {
      if (epoch !== voiceEpoch.current) return;
      releaseRecording();
      voiceBusy.current = false;
      setVoicePending(false);
      setVoiceStatus("");
      setError(microphoneError(e));
    }
  }
  useEffect(() => {
    const stop = () => {
      voiceEpoch.current++;
      voiceBusy.current = false;
      if (recording.current) {
        recording.current.onstop = null;
        if (recording.current.state === "recording") recording.current.stop();
      }
      releaseRecording();
    };
    const leave = () => { stop(); setVoicePending(false); setVoiceStatus(""); };
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); stop(); };
  }, []);
  useEffect(() => {
    if (!session) return;
    let stopped = false,
      timer: ReturnType<typeof setTimeout>;
    async function sync() {
      try {
        const response = await fetch("/backend/v1/public/conversation", {
          method: "POST",
          credentials: "omit",
          headers: { Authorization: "Bearer " + session?.session_token },
          signal: AbortSignal.timeout(10000),
        });
        if (!response.ok) {
          if ([401, 403, 404].includes(response.status) && !stopped) {
            stopped = true;
            chatController.current?.abort();
            setSession(null);
            setError("Chat session is unavailable. Reconnect to continue.");
          }
          return;
        }
        const result = await response.json();
        if (stopped) return;
        setState(result.state);
        if (result.state !== "open" && busyRef.current)
          chatController.current?.abort();
        if (!busyRef.current && result.items.length)
          setMessages(
            result.items.map((item: Row) => ({
              role: item.role,
              text:
                item.role === "operator"
                  ? "Support team · " + item.text_content
                  : item.text_content,
              ...item.metadata_data,
            })),
          );
      } catch {
      } finally {
        if (!stopped) timer = setTimeout(sync, 2000);
      }
    }
    sync();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [session?.id]);
  function setupRequest(path: string, options: RequestInit) {
    if (dashboardPreview) {
      const headers = new Headers(options.headers);
      headers.set("X-Studio-Preview", "1");
      return authenticatedFetch(path, {
        ...options,
        headers,
      });
    }
    return fetch("/backend" + path, { ...options, credentials: "omit" });
  }
  async function connect(signal?: AbortSignal) {
    setError("");
    try {
      const configResponse = await setupRequest(
          "/v1/public/installations/" +
            encodeURIComponent(publicId) +
            "?public_key=" +
            encodeURIComponent(publicKey),
          { method: "POST", credentials: "omit", signal },
        ),
        config = await configResponse.json();
      if (!configResponse.ok)
        throw Error(
          typeof config.detail === "string"
            ? config.detail
            : "This assistant is unavailable",
        );
      const required = (config.variables || []).filter(
        (v: Row) =>
          v.required && !String(variables[v.name] ?? v.default ?? "").trim(),
      );
      if (required.length) {
        setDefinitions(config.variables);
        return;
      }
      setDefinitions([]);
      if (config.theme?.collect_email === true && !email) {
        setEmailRequired(true);
        return;
      }
      setEmailRequired(false);
      const token=await botToken(challengeRoot.current!,config.challenge,signal);
      const response = await setupRequest("/v1/public/sessions", {
        method: "POST",
        signal,
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          installation_public_id: publicId,
          public_key: publicKey,
          variables,
          visitor_email: email || undefined,
          bot_token:token||undefined,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.detail || "Session unavailable");
      setSession(result);
      setMessages([{ role: "assistant", text: result.greeting }]);
    } catch (e) {
      if (!signal?.aborted) setError((e as Error).message);
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    // Strict Mode replays effect setup. Defer until its cleanup can cancel the
    // discarded setup, avoiding duplicate durable public sessions in development.
    queueMicrotask(() => {
      if (!controller.signal.aborted) connect(controller.signal);
    });
    return () => controller.abort();
  }, [publicId, publicKey, dashboardPreview]);
  useEffect(() => {
    end.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "nearest",
    });
  }, [messages]);
  async function send(event: React.FormEvent, confirmation?: Row) {
    event.preventDefault();
    if (
      !session ||
      busy ||
      state === "resolved" ||
      (!input.trim() && !confirmation)
    )
      return;
    const text = confirmation ? "Confirm request" : input.trim();
    setInput("");
    setBusy(true);
    setError("");
    setMessages((old) => [
      ...old,
      { role: "user", text },
      { role: "assistant", text: "", pending: true },
    ]);
    try {
      chatController.current = new AbortController();
      const response = await fetch("/backend/v1/public/chat", {
        signal: chatController.current.signal,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + session.session_token,
        },
        body: JSON.stringify({
          session_id: session.id,
          message: text,
          client_message_id: crypto.randomUUID(),
          ...(confirmation ? { confirmation_id: confirmation.id } : {}),
        }),
      });
      if (!response.ok) {
        const data = await response.json();
        throw Error(data.detail || "Chat failed");
      }
      const reader = response.body!.getReader(),
        decoder = new TextDecoder();
      let buffer = "",
        answer = "",
        metadata: Row = {};
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf("\n\n")) >= 0) {
          const event = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          const kind = event
            .split("\n")
            .find((x) => x.startsWith("event: "))
            ?.slice(7);
          const payload = event
            .split("\n")
            .find((x) => x.startsWith("data: "))
            ?.slice(6);
          if (!payload) continue;
          const data = JSON.parse(payload);
          if (kind === "chat.text.delta") answer += data.text;
          if (kind === "chat.products") metadata.products = data.products;
          if (kind === "chat.ticket.created")
            metadata.ticket_id = data.ticket_id;
          if (kind === "chat.completed") {
            answer = data.text;
            metadata = { ...metadata, ...data };
          }
          if (kind === "chat.human_queued" || kind === "chat.interrupted") {
            setState("human");
            setMessages((old) => old.slice(0, -1));
            continue;
          }
          if (kind === "chat.failed") throw Error(data.message);
          setMessages((old) => [
            ...old.slice(0, -1),
            { role: "assistant", text: answer, pending: false, ...metadata },
          ]);
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
      setMessages((old) =>
        old[old.length - 1]?.pending ? old.slice(0, -1) : old,
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div ref={challengeRoot} aria-label="Bot verification" />
      {session&&<WidgetEmailVerification key={session.id} session={session} initialEmail={email}/>}
      {emailRequired && (
        <form
          className="panel-body"
          onSubmit={(e) => {
            e.preventDefault();
            connect();
          }}
        >
          <h3>Let’s get started</h3>
          <p>
            Enter your email to start the conversation and let our team follow
            up.
          </p>
          <label>
            Email address
            <input
              aria-label="Email address"
              type="email"
              required
              maxLength={254}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <button className="btn primary">Continue</button>
        </form>
      )}
      {definitions.length > 0 && (
        <form
          className="panel-body"
          onSubmit={(e) => {
            e.preventDefault();
            connect();
          }}
        >
          <strong>A little context first.</strong>
          {definitions.map((v) => (
            <label key={v.name}>
              {v.description || v.name.replaceAll("_", " ")}
              <input
                required={v.required}
                value={variables[v.name] ?? v.default ?? ""}
                maxLength={2000}
                onChange={(e) =>
                  setVariables({ ...variables, [v.name]: e.target.value })
                }
              />
            </label>
          ))}
          <button className="btn primary">Start conversation</button>
        </form>
      )}
      <div className="chat-log" aria-live="polite">
        {messages.map((message, i) => (
          <div
            key={i}
            className={"chat-bubble " + (message.role === "user" ? "user" : "")}
          >
            {message.pending ? "Thinking…" : message.text}
            {message.products?.map((product: Row) => (
              <a
                key={product.id}
                className="product-mini"
                href={product.canonical_url}
                target="_blank"
                rel="noreferrer"
              >
                <strong>{product.title}</strong>
                {money(product.price_minor, product.currency)} ↗
              </a>
            ))}
            {message.actions?.map((action: Row) => (
              <a
                className="product-mini"
                key={action.id}
                href={
                  action.type === "scroll"
                    ? action.url + "#" + encodeURIComponent(action.section_id)
                    : action.url
                }
                target="_blank"
                rel="noopener noreferrer"
              >
                {action.type === "scroll"
                  ? "View section"
                  : "Open website page"}{" "}
                ↗
              </a>
            ))}
            {message.citations?.length > 0 && (
              <span className="muted small-text">
                Sources:{" "}
                {Array.from(
                  new Map(
                    message.citations.map((c: Row) => [c.url, c]),
                  ).values(),
                ).map((c: any) => (
                  <a
                    key={c.url}
                    href={c.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {c.title || "Website source"}{" "}
                  </a>
                ))}
              </span>
            )}
            {message.ticket_id && (
              <span style={{ display: "block", fontSize: 9, marginTop: 8 }}>
                Ticket {message.ticket_id.slice(0, 8)} · recorded
              </span>
            )}
            {message.confirmation &&
              message === messages[messages.length - 1] && (
                <button
                  type="button"
                  className="btn"
                  disabled={
                    busy ||
                    state !== "open" ||
                    Date.parse(message.confirmation.expires_at) <= Date.now()
                  }
                  onClick={(event) => send(event, message.confirmation)}
                >
                  Confirm request
                </button>
              )}
          </div>
        ))}
        {!session && !error && !definitions.length && !emailRequired && (
          <div className="muted small-text">Opening conversation…</div>
        )}
        <div ref={end} />
      </div>
      {error && (
        <div className="error" style={{ margin: 15 }} role="alert">
          {error}
          <button className="btn small" onClick={() => connect()}>
            <RefreshCw size={11} />
            New session
          </button>
        </div>
      )}
      <form className="chat-compose" onSubmit={send}>
        <input
          aria-label="Chat message"
          placeholder="Ask a question…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={!session || busy || state === "resolved"}
          required
        />
        {session?.voice_input_available && (
          <button
            type="button"
            className="btn"
            onClick={voiceInput}
            aria-label={
              voiceStatus.startsWith("Listening")
                ? "Stop voice input"
                : "Start voice input"
            }
            disabled={busy || voicePending || state === "resolved"}
          >
            {voiceStatus.startsWith("Listening") ? "Stop" : "Mic"}
          </button>
        )}
        <button
          className="btn primary"
          aria-label="Send chat message"
          disabled={!session || busy || state === "resolved"}
        >
          <Send size={14} />
        </button>
      </form>
      <div className="status-strip">
        <i className="connection-dot" />
        {voiceStatus ||
          (state === "human"
            ? "Support team connected · AI paused"
            : state === "resolved"
              ? "Conversation closed"
              : "AI assistant")}{" "}
        ·{" "}
        {session?.mode === "live-llm"
          ? "Connected"
          : "Development response mode"}
      </div>
    </>
  );
}
