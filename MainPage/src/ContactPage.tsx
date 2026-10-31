import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  Check,
  CheckCheck,
  ChevronDown,
  CircleHelp,
  LoaderCircle,
  Mail,
  MessageCircle,
  Send,
  ShieldCheck,
} from "lucide-react";
import { motion } from "motion/react";
import { useMotionPreference } from "./components/useMotionPreference";
import "./contact.css";

const SUPPORT = "support@phirmy.com";
const appOrigin = (
  import.meta.env.VITE_APP_URL ||
  (import.meta.env.DEV
    ? `${location.protocol}//${location.hostname}:3100`
    : location.origin)
).replace(/\/$/, "");
const interests = [
  { value: "voice", label: "AI voice agents", icon: AudioLines },
  { value: "chat", label: "Website chat", icon: MessageCircle },
  { value: "both", label: "Voice + chat", icon: CheckCheck },
  { value: "exploring", label: "Still exploring", icon: CircleHelp },
];

export default function ContactPage() {
  const reduced = useMotionPreference();
  const [interest, setInterest] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState<{
    name: string;
    email: string;
    reference: string;
  } | null>(null);
  const [messageLength, setMessageLength] = useState(0);
  const attempt = useRef<{ key: string; payload: string } | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const successRef = useRef<HTMLDivElement>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    document.title = "Contact Phirmy — Let’s build your next conversation";
    return () => request.current?.abort();
  }, []);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);
  useEffect(() => {
    if (success) successRef.current?.focus();
  }, [success]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || request.current) return;
    const form = new FormData(event.currentTarget);
    const payload = {
      name: String(form.get("name") || "").trim(),
      email: String(form.get("email") || "").trim(),
      company: String(form.get("company") || "").trim(),
      interest,
      message: String(form.get("message") || "").trim(),
      contact_permission: form.get("contact_permission") === "on",
      fax_number: String(form.get("fax_number") || ""),
    };
    if (
      payload.name.length < 2 ||
      payload.message.length < 20 ||
      !interest ||
      !payload.contact_permission
    ) {
      setError(
        "Please tell us your name, choose an interest, and add a message of at least 20 characters. Then confirm we may contact you.",
      );
      return;
    }
    const json = JSON.stringify(payload);
    if (!attempt.current || attempt.current.payload !== json)
      attempt.current = { key: crypto.randomUUID(), payload: json };
    const controller = new AbortController();
    request.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setBusy(true);
    setError("");
    try {
      const result = await fetch("/api/contact", {
        method: "POST",
        credentials: "omit",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": attempt.current.key,
        },
        body: json,
        signal: controller.signal,
      });
      if (!result.ok) {
        if (result.status === 429)
          throw new Error(
            "You’ve sent a few messages recently. Please try again later, or email us directly below.",
          );
        if (result.status === 422)
          throw new Error(
            "Please check your email address and the details in your message, then try again.",
          );
        if (result.status === 409) {
          attempt.current = null;
          throw new Error(
            "Please try submitting again. We’ve refreshed your enquiry reference.",
          );
        }
        throw new Error(
          "Your message could not be received right now. Please try again or email us directly below.",
        );
      }
      const receipt = await result.json();
      if (
        receipt.status !== "received" ||
        typeof receipt.reference !== "string"
      )
        throw new Error(
          "We couldn’t confirm receipt. Please try again; the same enquiry won’t be queued twice.",
        );
      setSuccess({
        name: payload.name.split(/\s+/)[0],
        email: payload.email,
        reference: receipt.reference,
      });
    } catch (e) {
      setError(
        e instanceof DOMException && e.name === "AbortError"
          ? "We couldn’t confirm receipt in time. Please try again; the same enquiry won’t be queued twice."
          : e instanceof TypeError
            ? "We couldn’t reach the server. Please try again or email us directly below."
            : e instanceof Error
              ? e.message
              : "Something interrupted your message. Please try again.",
      );
    } finally {
      clearTimeout(timeout);
      setBusy(false);
      request.current = null;
    }
  }

  return (
    <div className="site contact-site">
      <a className="skip-link" href="#contact-main">
        Skip to contact form
      </a>
      <header className="header">
        <div className="container nav-shell">
          <a href="/" className="brand" aria-label="Phirmy home">
            <img
              src="/brand/phirmy-light.jpg"
              alt="Phirmy — Build. Scale. Together."
              width="1280"
              height="441"
            />
          </a>
          <nav className="contact-nav" aria-label="Contact navigation">
            <a href="/#product">Meet Phirmy</a>
            <a href="/#use-cases">See it in action</a>
          </nav>
          <a className="contact-back" href="/">
            <ArrowLeft size={14} />
            <span>Back to home</span>
          </a>
        </div>
      </header>
      <main id="contact-main" className="container contact-layout">
        <motion.div
          className="contact-intro"
          initial={reduced ? false : { opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <div className="eyebrow">
            <span className="status-dot" /> GOOD THINGS START WITH A HELLO
          </div>
          <h1>
            Big ideas.
            <br />
            <span>Let’s talk.</span>
          </h1>
          <p className="contact-lead">
            Your business has a voice.
            <br />
            Let’s help more people hear it.
          </p>
          <p className="contact-description">
            Whether you’re ready to build your first AI agent or just curious
            about what’s possible, we’d love to hear what you have in mind.
          </p>
          <div className="contact-sculpture" aria-hidden="true">
            <div className="contact-orbit" />
            <div className="contact-orbit inner" />
            <img
              src="/brand/phirmy-symbol.jpg"
              alt=""
              width="1280"
              height="1280"
            />
            <span className="contact-note">
              <MessageCircle size={14} /> A conversation. A possibility.
            </span>
            <span className="contact-sculpture-dot" />
          </div>
          <div className="direct-contact">
            <span className="contact-mail-icon">
              <Mail size={20} strokeWidth={1.5} />
            </span>
            <div>
              <p>Prefer a good old-fashioned email?</p>
              <a href={`mailto:${SUPPORT}`}>
                {SUPPORT}
                <ArrowUpRight size={15} />
              </a>
            </div>
          </div>
        </motion.div>
        <motion.div
          className="contact-form-column"
          initial={reduced ? false : { opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65, delay: 0.12 }}
        >
          {success ? (
            <div
              className="contact-card success-card"
              ref={successRef}
              tabIndex={-1}
              role="status"
            >
              <span className="success-seal">
                <Check size={30} strokeWidth={1.4} />
              </span>
              <span className="eyebrow">
                THE FIRST HELLO IS THE HARDEST PART
              </span>
              <h2>
                Thanks, {success.name}.<br />
                <span>A good start.</span>
              </h2>
              <p>
                We’ve received your enquiry. Our team will review what you have
                in mind and get back to you at <strong>{success.email}</strong>.
              </p>
              <div className="success-next">
                <Mail size={18} />
                <div>
                  <strong>Keep the conversation going.</strong>
                  <p>
                    Have anything to add? Email{" "}
                    <a href={`mailto:${SUPPORT}`}>{SUPPORT}</a>.
                  </p>
                </div>
              </div>
              <a className="button dark-button" href="/#use-cases">
                Explore what’s possible <ArrowUpRight size={17} />
              </a>
              <p className="contact-reference">
                Your reference
                <br />
                <span>{success.reference}</span>
              </p>
            </div>
          ) : (
            <div className="contact-card">
              <div className="contact-card-heading">
                <span className="eyebrow">LET’S BUILD SOMETHING TOGETHER</span>
                <h2>What do you have in mind?</h2>
                <p>A few details now. A more useful conversation next.</p>
              </div>
              <form onSubmit={submit} aria-label="Contact Phirmy">
                {error && (
                  <div
                    className="contact-error"
                    role="alert"
                    tabIndex={-1}
                    ref={errorRef}
                  >
                    {error}
                    <a href={`mailto:${SUPPORT}`}>
                      Email {SUPPORT} <ArrowUpRight size={12} />
                    </a>
                  </div>
                )}
                <fieldset disabled={busy} className="contact-fields">
                  <legend className="sr-only">Your enquiry</legend>
                  <div className="contact-field-row">
                    <label htmlFor="contact-name">
                      Your name <span aria-hidden="true">*</span>
                      <input
                        id="contact-name"
                        name="name"
                        autoComplete="name"
                        placeholder="Alex Morgan"
                        required
                        minLength={2}
                        maxLength={100}
                      />
                    </label>
                    <label htmlFor="contact-email">
                      Email address <span aria-hidden="true">*</span>
                      <input
                        id="contact-email"
                        name="email"
                        type="email"
                        autoComplete="email"
                        placeholder="alex@yourcompany.com"
                        required
                        maxLength={254}
                      />
                    </label>
                  </div>
                  <label htmlFor="contact-company">
                    Company <span className="optional">optional</span>
                    <input
                      id="contact-company"
                      name="company"
                      autoComplete="organization"
                      placeholder="Where you’re making things happen"
                      maxLength={150}
                    />
                  </label>
                  <fieldset className="interest-group">
                    <legend>
                      I’m interested in <span aria-hidden="true">*</span>
                    </legend>
                    <div className="interest-options">
                      {interests.map(({ value, label, icon: Icon }) => (
                        <label
                          key={value}
                          className={
                            interest === value
                              ? "interest-option selected"
                              : "interest-option"
                          }
                        >
                          <input
                            type="radio"
                            name="interest"
                            value={value}
                            required
                            checked={interest === value}
                            onChange={() => setInterest(value)}
                          />
                          <Icon size={16} />
                          <span>{label}</span>
                          <span className="interest-check">
                            {interest === value && <Check size={11} />}
                          </span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                  <label htmlFor="contact-message">
                    Tell us a little about your idea{" "}
                    <span aria-hidden="true">*</span>
                    <textarea
                      id="contact-message"
                      name="message"
                      placeholder="What does your business do? What would you love your agent to help with?"
                      required
                      minLength={20}
                      maxLength={4000}
                      rows={5}
                      onChange={(event) =>
                        setMessageLength(event.target.value.length)
                      }
                      aria-describedby="message-hint"
                    />
                  </label>
                  <div id="message-hint" className="message-hint">
                    <span>
                      A little context goes a long way. At least 20 characters.
                    </span>
                    <span>{messageLength.toLocaleString()} / 4,000</span>
                  </div>
                  <div className="contact-trap" aria-hidden="true">
                    <label>
                      Leave this blank
                      <input
                        name="fax_number"
                        tabIndex={-1}
                        autoComplete="off"
                      />
                    </label>
                  </div>
                  <label className="contact-consent">
                    <input type="checkbox" name="contact_permission" required />
                    <span>
                      You may contact me about this enquiry. I’ve read the{" "}
                      <a href={"/legal/privacy"}>Privacy notice</a>.
                    </span>
                  </label>
                  <button
                    className="button dark-button contact-submit"
                    type="submit"
                    disabled={busy}
                  >
                    {busy ? (
                      <>
                        <LoaderCircle size={17} className="sending-spinner" />
                        Sending your message…
                      </>
                    ) : (
                      <>
                        Let’s start a conversation <ArrowUpRight size={18} />
                      </>
                    )}
                  </button>
                  <div className="contact-form-note">
                    <ShieldCheck size={13} />
                    <span>
                      Your details are for this conversation. No mailing list.
                    </span>
                  </div>
                </fieldset>
              </form>
            </div>
          )}
          <p className="contact-required">
            {!success && "* Required details. We’ll take it from there."}
          </p>
        </motion.div>
      </main>
      <section
        className="container contact-next"
        aria-labelledby="next-heading"
      >
        <div>
          <span className="eyebrow">A SIMPLE NEXT STEP</span>
          <h2 id="next-heading">
            A hello. <span>A plan. A possibility.</span>
          </h2>
        </div>
        <div className="contact-next-grid">
          <article>
            <span>01</span>
            <h3>You share the idea.</h3>
            <p>
              Tell us about your business and the conversations you want to make
              better.
            </p>
          </article>
          <article>
            <span>02</span>
            <h3>We find the right fit.</h3>
            <p>
              We’ll get in touch to understand your needs and explore where
              Phirmy can help.
            </p>
          </article>
          <article>
            <span>03</span>
            <h3>We build from there.</h3>
            <p>
              From voice to website chat, we’ll help you work out a sensible
              next step.
            </p>
          </article>
        </div>
      </section>
      <footer className="contact-footer">
        <div className="container">
          <span>© {new Date().getFullYear()} Phirmy</span>
          <span className="contact-tagline">
            BUILD <i /> SCALE <i /> TOGETHER
          </span>
          <div>
            <a href={"/legal/privacy"}>Privacy</a>
            <a href={"/legal/terms"}>Terms</a>
            <a href={`mailto:${SUPPORT}`}>
              Contact us <ArrowUpRight size={12} />
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
