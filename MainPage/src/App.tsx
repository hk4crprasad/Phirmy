import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { motion } from "motion/react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  CalendarDays,
  Check,
  CheckCheck,
  ChevronDown,
  Code2,
  FileText,
  Globe2,
  Headphones,
  Layers3,
  Menu,
  MessageCircle,
  Mic,
  Pause,
  Play,
  ShieldCheck,
  Sparkles,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useMotionPreference } from "./components/useMotionPreference";
import BlurText from "./components/react-bits/BlurText";
import { openCookieSettings } from "./components/CookieControls";
import SpotlightCard from "./components/react-bits/SpotlightCard";

import ShinyText from "./components/react-bits/new/ShinyText";
import Magnet from "./components/react-bits/new/Magnet/Magnet";
import {HeroThreads, ConversationWords} from "./components/MotionAccents";

const ProductDemo = lazy(() => import("./components/ProductDemo"));
const appOrigin = (
  import.meta.env.VITE_APP_URL ||
  (import.meta.env.DEV
    ? `${window.location.protocol}//${window.location.hostname}:3100`
    : window.location.origin)
).replace(/\/$/, "");
const appLink = (path: string) => `${appOrigin}${path}`;

function Reveal({
  children,
  className = "",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  const reduced = useMotionPreference();
  return (
    <motion.div
      className={className}
      initial={reduced ? false : { opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.12 }}
      transition={{ duration: 0.65, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

function Brand({ dark = false }: { dark?: boolean }) {
  return (
    <a
      href="#"
      className={`brand ${dark ? "brand-dark" : ""}`}
      aria-label="Phirmy home"
    >
      <img
        src={`/brand/phirmy-${dark ? "dark" : "light"}.jpg`}
        alt="Phirmy — Build. Scale. Together."
        width="1280"
        height="441"
      />
    </a>
  );
}

function Wave({ className = "" }: { className?: string }) {
  return (
    <div className={`wave ${className}`} aria-hidden="true">
      {Array.from({ length: 27 }, (_, i) => (
        <i
          key={i}
          style={
            {
              "--height": `${10 + ((i * 19 + 7) % 37)}px`,
              "--delay": `${i * -0.13}s`,
            } as CSSProperties
          }
        />
      ))}
    </div>
  );
}

function HeroVisual({paused}: {paused: boolean}) {
  return <div className="hero-visual" aria-hidden="true">
    <HeroThreads paused={paused} />
    <div className="silver-core"><img src="/brand/phirmy-symbol.jpg" alt="" width="1280" height="1280"/><span className="core-sheen"/></div>
    <span className="emblem-line"/><span className="emblem-line right"/>
  </div>;
}

const faqs = [
  [
    "What exactly is Phirmy?",
    "Phirmy helps you build AI agents for customer conversations. Add your website and documents, choose how your agent should respond, then connect it to website chat, browser voice, or configured phone channels. Conversations, leads, bookings, and follow-up requests come together in your workspace.",
  ],
  [
    "How does my agent learn about my business?",
    "You choose the source material: website pages, uploaded documents, and the guidance you write. Your agent uses that knowledge to answer questions. Preview its answers and check its sources before publishing. Keep the source material current as your business changes.",
  ],
  [
    "Can it actually book appointments or take action?",
    "Yes, with the relevant integration connected and permissions configured. Agents can check availability and request a booking through supported scheduling providers. Actions that change something require confirmation; a booking is only presented as confirmed after the provider confirms it.",
  ],
  [
    "Do I need to know how to code?",
    "You can configure your agent and customize its website widget in the dashboard. Install the widget by adding an embed snippet to your site. Developers can also connect custom HTTP tools for more specific workflows.",
  ],
  [
    "Can I use it for phone calls?",
    "Phone channels use supported telephony providers and require a configured number, provider access, and applicable verification. Website chat and browser voice are separate channels. Live transfers need additional setup and approval. Availability depends on your workspace configuration.",
  ],
  [
    "What happens when a customer needs a person?",
    "Your agent can collect a follow-up request and send it to your team’s inbox. Configured phone agents can also support approved human transfers where enabled. You decide the handoff rules and review the conversation context.",
  ],
  [
    "How does pricing work?",
    "Plans and paid activation are being finalized. We will show the available plan, included usage, and any applicable charges before you activate a paid service. This page does not collect payment or make a pricing commitment.",
  ],
];

export default function App() {
  const [productsOpen, setProductsOpen] = useState(false);
  const productNav = useRef<HTMLDivElement>(null);
  const [menu, setMenu] = useState(false);
  const [paused, setPaused] = useState(false);
  const [demoMounted, setDemoMounted] = useState(false);
  const [demoRequested, setDemoRequested] = useState(0);
  const demoRef = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const reduced = useMotionPreference();
  const still = paused || Boolean(reduced);
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setDemoMounted(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    if (demoRef.current) observer.observe(demoRef.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!productNav.current?.contains(event.target as Node)) setProductsOpen(false);
    };
    window.addEventListener("pointerdown", outside);
    return () => window.removeEventListener("pointerdown", outside);
  }, []);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape" && productsOpen) {
        setProductsOpen(false);
        productNav.current?.querySelector("button")?.focus();
      }
      if (event.key === "Escape" && menu) {
        setMenu(false);
        menuButton.current?.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [menu, productsOpen]);
  useEffect(() => {
    const visibility = () =>
      document.documentElement.classList.toggle("page-hidden", document.hidden);
    document.addEventListener("visibilitychange", visibility);
    return () => document.removeEventListener("visibilitychange", visibility);
  }, []);
  function watchDemo() {
    setDemoMounted(true);
    setDemoRequested((n) => n + 1);
    demoRef.current?.scrollIntoView({
      behavior: reduced ? "instant" : "smooth",
      block: "start",
    });
  }

  return (
    <div className={still ? "site phirmy-home motion-paused" : "site phirmy-home"}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="header">
        <div className="container nav-shell">
          <Brand />
          <nav className="desktop-nav" aria-label="Main navigation">
            <div className="product-nav" ref={productNav} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setProductsOpen(false); }}>
              <button aria-expanded={productsOpen} aria-controls="product-navigation" onClick={() => setProductsOpen(!productsOpen)}>Product <ChevronDown size={13}/></button>
              {productsOpen && <div className="product-mega" id="product-navigation">
                <div className="mega-heading"><span className="eyebrow">MADE FOR THE CONVERSATION</span><p>One place to listen.<br/>And take the next step.</p></div>
                <div className="mega-links">
                  {[["Website chat", "Answers from your own knowledge", "#website-chat", MessageCircle], ["Voice conversations", "Browser voice and configured phone channels", "#voice-conversations", AudioLines], ["Connected actions", "Tools, bookings and team follow-ups", "#connected-actions", CalendarDays]].map(([title, detail, href, Icon]) => { const ItemIcon = Icon as typeof MessageCircle; return <a key={String(title)} href={String(href)} onClick={() => setProductsOpen(false)}><ItemIcon size={21}/><span><strong>{String(title)}</strong><small>{String(detail)}</small></span><ArrowUpRight size={15}/></a>; })}
                </div>
                <a href="/contact" className="mega-contact"><span>Let’s make it yours.</span><strong>Talk to Phirmy <ArrowUpRight size={19}/></strong><small>Explore what fits your business.</small></a>
              </div>}
            </div>
            <a href="#use-cases">Use cases</a>
            <a href="#how-it-works">How it works</a>
            <a href="#faq">FAQs</a>
            <a href="/contact">Contact</a>
          </nav>
          <div className="nav-actions">
            {import.meta.env.VITE_APP_URL && <a className="login" href={appLink("/signin")}>Log in <ArrowUpRight size={14}/></a>}
            <a className="button small dark-button" href="/contact">
              Get started <ArrowUpRight size={15} />
            </a>
            <button
              ref={menuButton}
              className="icon-button mobile-toggle"
              aria-label={menu ? "Close navigation" : "Open navigation"}
              aria-expanded={menu}
              aria-controls="mobile-nav"
              onClick={() => setMenu(!menu)}
            >
              {menu ? <X /> : <Menu />}
            </button>
          </div>
        </div>
        {menu && (
          <nav
            id="mobile-nav"
            className="mobile-nav"
            aria-label="Mobile navigation"
          >
            {[
              ["Product", "#product"],
              ["Use cases", "#use-cases"],
              ["How it works", "#how-it-works"],
              ["FAQs", "#faq"],
              ["Contact us", "/contact"],
              ["Request workspace access", "/contact"],
            ].map(([label, link]) => (
              <a key={label} href={link} onClick={() => setMenu(false)}>
                {label}
                <ArrowUpRight size={16} />
              </a>
            ))}
          </nav>
        )}
      </header>
      <main id="main">
        <section className="hero container">
          <div className="hero-copy">
            <Reveal>
              <div className="eyebrow">
                <span className="status-dot" /> A LITTLE MORE HUMAN. A LOT MORE POSSIBLE.
              </div>
            </Reveal>
            <h1>
              <span className="sr-only">Your business. Always there.</span>
              <span aria-hidden="true">
                {reduced ? (
                  <>
                    <span>Your business.</span>
                    <span className="silver-text">Always there.</span>
                  </>
                ) : (
                  <>
                    <BlurText
                      text="Your business."
                      delay={90}
                      direction="bottom"
                      trigger="load"
                      distance={18}
                      stepDuration={0.28}
                    />
                    <ShinyText text="Always there." className="silver-text hero-shine" color="#4e665c" shineColor="#273d34" speed={1.8} trigger="view" disabled={still} />
                  </>
                )}
              </span>
            </h1>
            <Reveal delay={0.18}>
              <p className="hero-description">
                AI voice and chat, shaped around your business.
                <br className="desktop-break" /> Helpful answers. Thoughtful conversations. A clear next step.
              </p>
              <div className="hero-buttons">
                <Magnet disabled={still} maxOffset={7} padding={28} magnetStrength={5} wrapperClassName="cta-magnet">
                  <a className="button dark-button" href="/contact">
                    Build your agent <ArrowUpRight size={18} />
                  </a>
                </Magnet>
                <button className="button demo-button" onClick={watchDemo}>
                  <span className="play-disc">
                    <Play size={12} fill="currentColor" />
                  </span>
                  See it in action
                </button>
              </div>
              <ConversationWords paused={still}/>
              <div className="hero-notes">
                <span>
                  <Check size={13} /> Your knowledge, your voice
                </span>
                <span>
                  <Check size={13} /> No code to get started
                </span>
              </div>
            </Reveal>
          </div>
          <Reveal className="hero-art" delay={0.2}>
            <HeroVisual paused={still} />
          </Reveal>
          <div className="hero-bottom">
            <span>BUILT TO LISTEN. DESIGNED TO MOVE YOU FORWARD.</span>
            <a href="#product" aria-label="Explore the product">
              <ArrowDown size={17} />
            </a>
            <button
              className="motion-toggle"
              onClick={() => setPaused(!paused)}
              aria-pressed={paused}
              disabled={Boolean(reduced)}
            >
              {still ? <Play size={12} /> : <Pause size={12} />}
              {reduced
                ? "Reduced motion"
                : paused
                  ? "Resume ambient motion"
                  : "Pause ambient motion"}
            </button>
          </div>
        </section>
        <section
          className="channel-strip"
          aria-label="Connected product channels"
        >
          <div className="container channel-inner">
            <span>FROM FIRST HELLO TO WHAT’S NEXT</span>
            <div>
              <MessageCircle /> Website chat
            </div>
            <div>
              <AudioLines /> Natural voice
            </div>
            <div>
              <CalendarDays /> Connected actions
            </div>
            <div>
              <Users /> Human connection
            </div>
          </div>
        </section>
        <section id="product" className="section container">
          <Reveal className="section-heading">
            <div>
              <span className="eyebrow">01 / MEET YOUR NEW TEAMMATE</span>
              <h2>
                More than an answer.
                <br />
                <span className="muted">A way forward.</span>
              </h2>
            </div>
            <p>
              Give your customers a conversation that goes somewhere. Phirmy
              connects what your business knows with what your customers need.
            </p>
          </Reveal>
          <div className="feature-grid">
            <Reveal>
              <SpotlightCard
                theme="light"
                className="feature-card"
                spotlightColor="#9b9b8e"
                intensity={0.22}
              >
                <span className="feature-number">01</span>
                <div className="feature-art chat-art">
                  <div className="tiny-chat">
                    Does this work with my website?<span>Just now</span>
                  </div>
                  <div className="tiny-answer">
                    <Sparkles size={14} />
                    <span>Let’s find the right fit for you.</span>
                  </div>
                  <span className="source-chip">
                    <FileText size={11} /> Grounded in your knowledge
                  </span>
                </div>
                <MessageCircle className="feature-icon" size={22} />
                <h3 id="website-chat">A chat that gets you.</h3>
                <p>
                  A helpful presence on your website, with answers from your
                  content and a look that feels like your brand.
                </p>
                <a href="#use-cases">
                  Explore website chat <ArrowUpRight size={15} />
                </a>
              </SpotlightCard>
            </Reveal>
            <Reveal delay={0.08}>
              <SpotlightCard
                theme="light"
                className="feature-card"
                spotlightColor="#9b9b8e"
                intensity={0.22}
              >
                <span className="feature-number">02</span>
                <div className="feature-art voice-art">
                  <div className="voice-orb">
                    <AudioLines size={29} />
                  </div>
                  <Wave />
                  <span className="voice-art-caption">
                    A conversation, not a phone menu.
                  </span>
                </div>
                <AudioLines className="feature-icon" size={22} />
                <h3 id="voice-conversations">A voice worth talking to.</h3>
                <p>
                  Let customers speak naturally in the browser or on configured
                  phone channels. Keep the context as the conversation unfolds.
                </p>
                <a href="#use-cases">
                  Discover voice agents <ArrowUpRight size={15} />
                </a>
              </SpotlightCard>
            </Reveal>
            <Reveal delay={0.16}>
              <SpotlightCard
                theme="light"
                className="feature-card"
                spotlightColor="#9b9b8e"
                intensity={0.22}
              >
                <span className="feature-number">03</span>
                <div className="feature-art action-art">
                  <div className="flow-icon">
                    <MessageCircle size={20} />
                  </div>
                  <span className="flow-line" />
                  <div className="flow-icon middle">
                    <Sparkles size={22} />
                  </div>
                  <span className="flow-line" />
                  <div className="flow-icon">
                    <CalendarDays size={20} />
                  </div>
                  <span className="action-chip">
                    <CheckCheck size={14} /> From intent to action
                  </span>
                </div>
                <Zap className="feature-icon" size={22} />
                <h3 id="connected-actions">Keep the momentum.</h3>
                <p>
                  Capture a lead, check a calendar, or create a follow-up.
                  Connect your tools and put the next step within reach.
                </p>
                <a href="#how-it-works">
                  See how it connects <ArrowUpRight size={15} />
                </a>
              </SpotlightCard>
            </Reveal>
          </div>
        </section>
        <section id="use-cases" className="showcase section" ref={demoRef}>
          <div className="container">
            <Reveal className="showcase-heading">
              <span className="eyebrow">
                <span className="light-dot" /> THE POSSIBILITIES, IN MOTION
              </span>
              <h2>
                Small conversations.
                <br />
                <span>Real possibilities.</span>
              </h2>
              <p>
                From the first “hello” to the next step.
                <br />
                See where a conversation with Phirmy can go.
              </p>
            </Reveal>
            <Suspense
              fallback={
                <div className="demo-placeholder">
                  Preparing the product walkthrough…
                </div>
              }
            >
              {demoMounted ? (
                <ProductDemo requested={demoRequested} ambientPaused={still} />
              ) : (
                <div className="demo-placeholder">
                  <button
                    className="button light-button"
                    onClick={() => setDemoMounted(true)}
                  >
                    Explore the walkthrough <Play size={16} />
                  </button>
                </div>
              )}
            </Suspense>
            <div className="showcase-foot">
              <span>
                <ShieldCheck size={15} /> Your knowledge at the heart of every
                answer.
              </span>
              <span>ILLUSTRATED PRODUCT TOUR · NO LIVE CALL</span>
            </div>
          </div>
        </section>
        <section id="how-it-works" className="section container setup-section">
          <Reveal className="section-heading">
            <div>
              <span className="eyebrow">02 / MADE SIMPLE, ON PURPOSE</span>
              <h2>
                From your knowledge.
                <br />
                <span className="muted">To their “thank you.”</span>
              </h2>
            </div>
            <p>
              Your expertise does the heavy lifting.
              <br />
              Phirmy helps you put it to work.
            </p>
          </Reveal>
          <div className="steps-grid">
            {[
              {
                n: "01",
                icon: Globe2,
                title: "Bring what you know.",
                description:
                  "Add your website, documents, and FAQs. Give your agent the information your customers are looking for.",
                tags: ["Website pages", "Documents", "Your instructions"],
              },
              {
                n: "02",
                icon: Layers3,
                title: "Make it feel like you.",
                description:
                  "Choose its voice, tone, and appearance. Connect your tools, test its answers, and decide when a person should step in.",
                tags: ["Your brand", "Your voice", "Your boundaries"],
              },
              {
                n: "03",
                icon: Code2,
                title: "Meet your customers.",
                description:
                  "Publish your website widget or connect a supported voice channel. Review conversations and keep making it better.",
                tags: ["Embed & publish", "Review", "Improve"],
              },
            ].map((step, i) => (
              <Reveal key={step.n} delay={i * 0.08} className="step">
                <div className="step-top">
                  <span>{step.n}</span>
                  <step.icon size={23} />
                </div>
                <h3>{step.title}</h3>
                <p>{step.description}</p>
                <div className="step-tags">
                  {step.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
              </Reveal>
            ))}
          </div>
        </section>
        <section className="workspace-section">
          <div className="container workspace-grid">
            <Reveal className="workspace-copy">
              <span className="eyebrow">03 / BUILT FOR THE WHOLE PICTURE</span>
              <h2>
                More connection.
                <br />
                <span className="muted">Less switching tabs.</span>
              </h2>
              <p>
                Every conversation is a chance to understand your customers
                better. Bring the details together, so your team knows what to
                do next.
              </p>
              <ul>
                <li>
                  <Check /> Conversations and leads in one place
                </li>
                <li>
                  <Check /> Sources you can review and update
                </li>
                <li>
                  <Check /> Follow-ups with the context attached
                </li>
                <li>
                  <Check /> Usage visibility and workspace controls
                </li>
              </ul>
              <a className="text-link" href="/contact">
                Explore the workspace with us <ArrowUpRight size={17} />
              </a>
            </Reveal>
            <Reveal className="workspace-preview" delay={0.12}>
              <div className="preview-top">
                <span>
                  <span className="tiny-mark">p</span> Your workspace
                </span>
                <span className="preview-pill">ILLUSTRATIVE VIEW</span>
              </div>
              <div className="preview-body">
                <aside>
                  <Layers3 />
                  <MessageCircle className="selected" />
                  <Users />
                  <CalendarDays />
                  <ShieldCheck />
                </aside>
                <div className="inbox-preview">
                  <div className="inbox-heading">
                    <h3>
                      A little context.
                      <br />A better connection.
                    </h3>
                    <span className="inbox-icon">
                      <MessageCircle size={21} />
                    </span>
                  </div>
                  <div className="inbox-row">
                    <span className="avatar">JK</span>
                    <div>
                      <strong>Jordan Kim</strong>
                      <p>Interested in the studio consultation</p>
                    </div>
                    <span className="inbox-time">2m ago</span>
                  </div>
                  <div className="inbox-message">
                    <span>CONVERSATION SUMMARY</span>
                    <p>
                      Looking for a workspace for a team of six. Asked about
                      availability and would like a follow-up.
                    </p>
                    <div>
                      <span>
                        <FileText size={12} /> Source attached
                      </span>
                      <span>
                        <Check size={12} /> Follow-up requested
                      </span>
                    </div>
                  </div>
                  <div className="inbox-bottom">
                    <span>
                      <span className="live-dot" /> Ready for your team
                    </span>
                    <ArrowRight size={16} />
                  </div>
                </div>
              </div>
            </Reveal>
          </div>
        </section>
        <section className="section container connection-section">
          <Reveal>
            <span className="eyebrow">FITS THE WAY YOU WORK</span>
            <h2>
              Your tools. <span className="muted">Working together.</span>
            </h2>
            <p>
              Keep the systems you trust. Give your conversations somewhere to
              go.
            </p>
          </Reveal>
          <Reveal className="integration-row">
            <span>
              <CalendarDays /> Cal.com
            </span>
            <span>
              <CalendarDays /> Calendly
            </span>
            <span>
              <CalendarDays /> Google Calendar
            </span>
            <span>
              <AudioLines /> Twilio
            </span>
            <span>
              <AudioLines /> Plivo
            </span>
            <span>
              <Code2 /> Custom APIs
            </span>
          </Reveal>
          <p className="integration-note">
            Connect the services you use. Features depend on your provider setup
            and workspace permissions.
          </p>
        </section>
        <section id="faq" className="section faq-section container">
          <Reveal className="faq-intro">
            <span className="eyebrow">A LITTLE MORE CLARITY</span>
            <h2>
              Good questions.
              <br />
              <span className="muted">Honest answers.</span>
            </h2>
            <p>Getting to know your next teammate.</p>
            <span className="faq-symbol">
              <MessageCircle size={40} strokeWidth={1} />
            </span>
          </Reveal>
          <div className="faq-list">
            {faqs.map(([question, answer], i) => (
              <details key={question}>
                <summary>
                  <span className="faq-number">0{i + 1}</span>
                  <span>{question}</span>
                  <ChevronDown size={17} />
                </summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </section>
        <section className="rollout-note container" aria-labelledby="rollout-title"><span className="eyebrow">WHERE WE ARE TODAY</span><div><h2 id="rollout-title">Built with care. Opening thoughtfully.</h2><p>Website chat, browser voice, knowledge sources, and connected tools are implemented. Phone channels need provider setup. We’re preparing the public rollout and paid activation, and can walk you through what is ready for your use case.</p><a href="/contact">Talk about your use case <ArrowUpRight size={16}/></a></div></section>
        <section className="final-cta container">
          <Reveal>
            <div className="cta-monogram">
              <img
                src="/brand/phirmy-symbol.jpg"
                alt=""
                width="1280"
                height="1280"
                loading="lazy"
              />
            </div>
            <span className="eyebrow">BUILD. SCALE. TOGETHER.</span>
            <h2>
              Your next chapter
              <br />
              starts with a conversation.
            </h2>
            <p>
              Give your business a voice. And your customers a reason to stay.
            </p>
            <Magnet disabled={still} maxOffset={8} padding={36} magnetStrength={5} wrapperClassName="cta-magnet">
              <a className="button dark-button" href="/contact">
                Let’s build something <ArrowUpRight size={18} />
              </a>
            </Magnet>
          </Reveal>
          <div className="cta-ring ring-a" />
          <div className="cta-ring ring-b" />
        </section>
      </main>
      <footer className="footer">
        <div className="container footer-top">
          <div>
            <Brand dark />
            <p>
              A little more human.
              <br />A lot more possible.
            </p>
          </div>
          <div className="footer-links">
            <div>
              <span>EXPLORE</span>
              <a href="#product">Product</a>
              <a href="#use-cases">Use cases</a>
              <a href="#how-it-works">How it works</a>
            </div>
            <div>
              <span>GET STARTED</span>
              <a href="/contact">Request workspace access <ArrowUpRight size={12}/></a>
              <a href="#how-it-works">Setup guide <ArrowUpRight size={12}/></a>
              <a href="#faq">Questions & answers</a>
              <a href="/contact">Contact us</a>
            </div>
            <div>
              <span>THE IMPORTANT THINGS</span>
              <a href="/legal/privacy">Privacy</a>
              <a href="/legal/terms">Terms</a>
              <a href="/legal/cookies">Cookie policy</a>
              <button className="footer-cookie" onClick={openCookieSettings}>Cookie settings</button>
            </div>
          </div>
        </div>
        <div className="footer-wordmark" aria-hidden="true">phirmy</div>
        <div className="container footer-bottom">
          <span>
            © {new Date().getFullYear()} Phirmy. Built for what’s next.
          </span>
          <span>
            BUILD <i /> SCALE <i /> TOGETHER
          </span>
          <a href="#">
            Back to top <ArrowUpRight size={13} />
          </a>
        </div>
      </footer>
    </div>
  );
}
