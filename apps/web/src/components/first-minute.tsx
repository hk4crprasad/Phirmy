"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  Check,
  Globe,
  MessageCircle,
  Plus,
  Send,
} from "lucide-react";
import { command, Row } from "@/lib/api";
import "./first-minute.css";
import ThemeSwitcher from "./theme-switcher";
import ProductTour from "./product-tour";

export default function FirstMinute() {
  const [url, setUrl] = useState(""),
    [preview, setPreview] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [seconds, setSeconds] = useState(0),
    [input, setInput] = useState(""),
    [messages, setMessages] = useState<Row[]>([]),
    [asking, setAsking] = useState(false);
  const started = useRef(0),
    answer = useRef<HTMLDivElement>(null),
    conversation = useRef<HTMLDivElement>(null),
    art = useRef<HTMLElement>(null),
    controller = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(
      () =>
        setSeconds(Math.round((performance.now() - started.current) / 1000)),
      250,
    );
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    const list = conversation.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages, asking]);
  useEffect(() => {
    const element = art.current;
    if (!element) return;
    let visible = false;
    function updateMotion() {
      element!.dataset.motionPaused = String(!visible || document.hidden);
    }
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      updateMotion();
    });
    observer.observe(element);
    document.addEventListener("visibilitychange", updateMotion);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", updateMotion);
    };
  }, [preview]);
  async function tryWebsite(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSeconds(0);
    started.current = performance.now();
    controller.current = new AbortController();
    const timeout = setTimeout(() => controller.current?.abort(), 24000);
    try {
      const response = await fetch("/backend/v1/public/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
        signal: controller.current.signal,
      });
      const result = await response.json();
      if (!response.ok)
        throw Error(result.detail || "This page could not be read.");
      setPreview(result);
      setMessages([
        { role: "user", text: result.question },
        { role: "assistant", ...result.answer },
      ]);
      sessionStorage.setItem(
        "studio.preview",
        JSON.stringify({ name: result.name, url: result.website_url }),
      );
      setTimeout(() => answer.current?.focus(), 50);
    } catch (e) {
      setError(
        (e as Error).message ||
          "That page took too long. Try a public product or about page.",
      );
    } finally {
      clearTimeout(timeout);
      setBusy(false);
    }
  }
  async function ask(event: React.FormEvent) {
    event.preventDefault();
    const question = input.trim();
    if (!question || asking) return;
    setInput("");
    setAsking(true);
    setError("");
    setMessages((old) => [...old, { role: "user", text: question }]);
    try {
      const result = await command("/v1/public/preview/question", {
        question,
        history: messages.slice(-8).map((message) => ({
          role: message.role,
          content: String(message.text).slice(0, 2000),
        })),
      });
      setMessages((old) => [...old, { role: "assistant", ...result }]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAsking(false);
    }
  }
  return (
    <main className="first-minute">
      <header className="fm-nav">
        <Link href="/" className="fm-brand" aria-label="Phirmy home">
          <AudioLines size={25} strokeWidth={1.8} />
          Phirmy
          <span className="fm-brand-dot" />
        </Link>
        <div className="fm-nav-actions">
          <ThemeSwitcher />
          <Link className="fm-signin" href="/signin">
            Your workspace <ArrowUpRight size={15} />
          </Link>
        </div>
      </header>
      <div className={"fm-stage " + (preview ? "has-preview" : "")}>
        {!preview ? (
          <>
            <section className="fm-copy">
              <div className="fm-kicker">
                <span />
                GO ON. TAKE YOUR TIME BACK.
              </div>
              <h1>
                Your website.
                <br />
                <span>Answering customers.</span>
              </h1>
              <p>
                Turn your website into an assistant you can try right now. No
                signup. No setup.
              </p>
              <form className="fm-url" onSubmit={tryWebsite}>
                <label htmlFor="business-url">Your website</label>
                <div className="fm-input-row">
                  <Globe size={19} />
                  <input
                    id="business-url"
                    name="website"
                    autoComplete="url"
                    inputMode="url"
                    placeholder="yourbusiness.com"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    required
                    disabled={busy}
                  />
                </div>
                <button className="fm-primary" disabled={busy}>
                  {busy ? "Reading your website…" : "Try my website"}
                  <ArrowRight size={20} />
                </button>
              </form>
              {error && (
                <div className="fm-error" role="alert">
                  {error}
                </div>
              )}
              {busy && (
                <div className="fm-progress" role="status">
                  <div>
                    <span>
                      {seconds < 4
                        ? "Opening your page"
                        : seconds < 10
                          ? "Finding what your business offers"
                          : "Preparing your first answer"}
                    </span>
                    <strong>{seconds}s</strong>
                  </div>
                  <div className="fm-progress-track">
                    <i />
                  </div>
                </div>
              )}
              <div className="fm-tour">
                <ProductTour />
              </div>
            </section>
            <aside
              ref={art}
              className="fm-art"
              aria-label="A little less on your plate"
            >
              <div className="fm-art-line" />
              <div className="fm-orbit orbit-one" />
              <div className="fm-orbit orbit-two" />
              <div className="fm-orbit orbit-three" />
              <div className="fm-center">
                <AudioLines size={66} strokeWidth={1.2} />
              </div>
              <div className="fm-note note-one">
                <MessageCircle size={18} />
                <span>One less “just checking…”</span>
                <Check size={16} />
              </div>
              <div className="fm-note note-two">
                <span className="fm-mini-wave">
                  {[12, 22, 32, 17, 26, 39, 21, 30, 14].map((height, i) => (
                    <i
                      key={i}
                      style={{
                        height,
                        animationDelay: `${i * -0.16}s`,
                        animationDuration: `${1.2 + (i % 3) * 0.23}s`,
                      }}
                    />
                  ))}
                </span>
                <span>A little more breathing room.</span>
              </div>
              <div className="fm-art-caption">
                <span>YOUR BUSINESS KNOWS THE ANSWER.</span>
                <strong>Give it a voice.</strong>
              </div>
              <Plus className="fm-cross" size={16} />
            </aside>
          </>
        ) : (
          <section
            className="fm-result"
            ref={answer}
            tabIndex={-1}
            aria-label="Your website assistant"
          >
            <div className="fm-result-intro">
              <div className="fm-read">
                <Check size={14} />
                Your website, understood.
              </div>
              <h1>
                That’s your business.
                <br />
                <span>Already helping.</span>
              </h1>
              <p>
                Ask a real customer question. See exactly where the answer comes
                from.
              </p>
              <div className="fm-source">
                <Globe size={16} />
                <a href={preview.website_url} target="_blank" rel="noreferrer">
                  {(() => {
                    try {
                      return new URL(preview.website_url).hostname;
                    } catch {
                      return preview.website_url;
                    }
                  })()}
                  <ArrowUpRight size={13} />
                </a>
              </div>
              <Link className="fm-primary" href="/signin?keep=1">
                Keep my assistant
                <ArrowRight size={18} />
              </Link>
              <p className="fm-result-foot">
                Your first answer was ready in{" "}
                {(preview.elapsed_ms / 1000).toFixed(1)} seconds. This preview
                read one page.
              </p>
              <button
                className="fm-text-button"
                onClick={() => {
                  setPreview(null);
                  setError("");
                }}
              >
                Try a different website
              </button>
            </div>
            <div className="fm-conversation">
              <div className="fm-chat-header">
                <span className="fm-agent-mark">
                  <AudioLines size={22} />
                </span>
                <div>
                  <strong>{preview.name}</strong>
                  <span>Answers from your website</span>
                </div>
                <i />
              </div>
              <div
                className="fm-messages"
                ref={conversation}
                aria-live="polite"
              >
                {messages.map((m, i) => (
                  <div className={"fm-message " + m.role} key={i}>
                    {m.role === "assistant" && (
                      <span className="fm-message-label">
                        {m.mode === "source-excerpt"
                          ? "From your page"
                          : m.mode === "not-found"
                            ? "Not found on this page"
                            : "Assistant"}
                      </span>
                    )}
                    <p>{m.text}</p>
                    {m.links?.map((link: Row) => (
                      <a
                        className="fm-answer-link"
                        href={link.url}
                        target="_blank"
                        rel="noreferrer"
                        key={link.url}
                      >
                        {link.title}
                        <ArrowUpRight size={14} />
                      </a>
                    ))}
                    {m.notice && (
                      <span className="fm-answer-notice">{m.notice}</span>
                    )}
                    {m.citations?.[0]?.url && (
                      <a
                        href={m.citations[0].url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Read the source
                        <ArrowUpRight size={12} />
                      </a>
                    )}
                  </div>
                ))}
                {asking && (
                  <div className="fm-thinking" role="status">
                    Answering from your page…
                  </div>
                )}
              </div>
              <form className="fm-compose" onSubmit={ask}>
                <label htmlFor="first-question" className="fm-sr">
                  Ask your assistant
                </label>
                <input
                  id="first-question"
                  placeholder="Ask a customer question…"
                  autoComplete="off"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  required
                  maxLength={1000}
                />
                <button disabled={asking} aria-label="Send question">
                  <ArrowRight size={19} />
                </button>
              </form>
              <div className="fm-chat-foot">
                A sourced text preview. Save it to connect chat and your voice.
              </div>
              {error && (
                <div className="fm-error" role="alert">
                  {error}
                </div>
              )}
            </div>
          </section>
        )}
      </div>
      <footer className="fm-footer">
        <span>More room for the work you love.</span>
        <span>
          Built around your business.
          <AudioLines size={17} />
        </span>
      </footer>
    </main>
  );
}
