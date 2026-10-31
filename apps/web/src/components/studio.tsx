"use client";
import { useState, useEffect, useCallback, useRef, ReactNode } from "react";
import dynamic from "next/dynamic";
import { useWorkspaceData } from "@/lib/workspace-data";
import { isWorkspaceRoute } from "@/lib/workspace-routes";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import {
  AudioLines,
  LayoutDashboard,
  BookOpen,
  Bot,
  Phone,
  Radio,
  ShoppingBag,
  MessageSquare,
  Inbox,
  Contact,
  CalendarDays,
  Plug,
  Wallet,
  Code2,
  Settings,
  ChevronRight,
  LogOut,
  Users,
  ArrowUpRight,
  FlaskConical,
  ShieldCheck,
  PanelLeftClose,
  PanelLeftOpen,
  X,
  UserRound,
} from "lucide-react";
import { api, command, Row, money } from "@/lib/api";
import { FormDialog, FormSpec, StudioContext } from "./ui";
import { WorkspacePageLoading } from "./workspace-page-loading";
const loading = () => <WorkspacePageLoading />;
const Dashboard = dynamic(() => import("./overview"), { loading });
const Knowledge = dynamic(
  () => import("./workspace-pages").then((m) => m.Knowledge),
  { loading },
);
const Agents = dynamic(
  () => import("./workspace-pages").then((m) => m.Agents),
  { loading },
);
const Calls = dynamic(() => import("./workspace-pages").then((m) => m.Calls), {
  loading,
});
const Commerce = dynamic(
  () => import("./workspace-pages").then((m) => m.Commerce),
  { loading },
);
const InboxPage = dynamic(
  () => import("./workspace-pages").then((m) => m.InboxPage),
  { loading },
);
const Leads = dynamic(() => import("./workspace-pages").then((m) => m.Leads), {
  loading,
});
const Developer = dynamic(
  () => import("./workspace-pages").then((m) => m.Developer),
  { loading },
);
const WorkspaceSettings = dynamic(
  () => import("./workspace-pages").then((m) => m.WorkspaceSettings),
  { loading },
);
const Appointments = dynamic(
  () => import("./workspace-pages").then((m) => m.Appointments),
  { loading },
);
const Numbers = dynamic(
  () => import("./workspace-pages").then((m) => m.Numbers),
  { loading },
);
const Templates = dynamic(
  () => import("./workspace-pages").then((m) => m.Templates),
  { loading },
);
const TeamPage = dynamic(
  () => import("./business-tools").then((m) => m.TeamPage),
  { loading },
);
const IntegrationPage = dynamic(
  () => import("./business-tools").then((m) => m.IntegrationPage),
  { loading },
);
const BillingPage = dynamic(
  () => import("./business-tools").then((m) => m.BillingPage),
  { loading },
);
const OperationsPage = dynamic(
  () => import("./business-tools").then((m) => m.OperationsPage),
  { loading },
);
const VoiceLab = dynamic(() => import("./voice-lab"), { loading });
const CampaignManager = dynamic(() => import("./campaign-manager"), {
  loading,
});
const ToolStudio = dynamic(() => import("./tool-studio"), { loading });
const ModelStudio = dynamic(() => import("./model-studio"), { loading });
const ProfilePage = dynamic(() => import("./profile-page"), { loading });
const ContactsPage = dynamic(() => import("./contacts-page"), { loading });
import NotificationCenter from "./notification-center";
import LoadingState from "./loading-state";
import ThemeSwitcher from "./theme-switcher";
import "./dashboard.css";

const NAV = [
  {
    label: "WORKSPACE",
    items: [
      { path: "", title: "Overview", icon: LayoutDashboard },
      { path: "agents", title: "Agents", icon: Bot },
      { path: "knowledge", title: "Knowledge", icon: BookOpen },
      { path: "templates", title: "Templates", icon: AudioLines },
      { path: "tools", title: "Tools", icon: Code2 },
      { path: "models", title: "Models", icon: FlaskConical },
    ],
  },
  {
    label: "CONVERSATIONS",
    items: [
      { path: "voice", title: "Voice lab", icon: Radio },
      { path: "calls", title: "Call history", icon: Phone },
      { path: "campaigns", title: "Campaigns", icon: AudioLines },
      { path: "inbox", title: "Inbox", icon: Inbox },
      { path: "contacts", title: "Contacts", icon: Contact },
      { path: "leads", title: "Leads", icon: Users },
      { path: "appointments", title: "Appointments", icon: CalendarDays },
    ],
  },
  {
    label: "BUSINESS",
    items: [
      { path: "products", title: "Product catalog", icon: ShoppingBag },
      { path: "widget", title: "Chat widget", icon: MessageSquare },
      { path: "numbers", title: "Phone numbers", icon: Phone },
      { path: "integrations", title: "Integrations", icon: Plug },
      { path: "team", title: "Team", icon: Users },
      { path: "operations", title: "Operations", icon: ShieldCheck },
    ],
  },
];

export default function Studio({ children }: { children: ReactNode }) {
  const path = usePathname(),
    router = useRouter(),
    section = path.split("/")[2] || "",
    validRoute = isWorkspaceRoute(path.split("/").slice(2).filter(Boolean));
  const [user, setUser] = useState<Row | null>(null),
    [workspaces, setWorkspaces] = useState<Row[]>([]),
    [workspace, setWorkspace] = useState<Row | null>(null);
  const [error, setError] = useState(""),
    [initial, setInitial] = useState(true),
    [toast, setToast] = useState(""),
    [formSpec, setFormSpec] = useState<FormSpec | null>(null),
    [mobile, setMobile] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [smallScreen, setSmallScreen] = useState(false);
  const sidebar = useRef<HTMLElement>(null),
    menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    setCollapsed(localStorage.getItem("studio.sidebar-collapsed") === "true");
    const media = window.matchMedia("(max-width:700px)"),
      update = () => setSmallScreen(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!mobile) return;
    const before = document.activeElement as HTMLElement | null,
      overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebar.current?.querySelector<HTMLElement>("button,a,select")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobile(false);
        return;
      }
      if (e.key !== "Tab") return;
      const nodes = Array.from(
        sidebar.current?.querySelectorAll<HTMLElement>(
          "a[href],button:not([disabled]),select",
        ) || [],
      ).filter((n) => n.getClientRects().length);
      const first = nodes[0],
        last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      }
      if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    const resize = () => {
      if (window.innerWidth > 700) setMobile(false);
    };
    document.addEventListener("keydown", key);
    window.addEventListener("resize", resize);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", resize);
      before?.focus();
    };
  }, [mobile]);
  const [savePreview, setSavePreview] = useState(false),
    [savingPreview, setSavingPreview] = useState(false);
  useEffect(() => {
    setSavePreview(
      new URLSearchParams(window.location.search).has("savePreview"),
    );
  }, []);
  const base = workspace ? "/v1/workspaces/" + workspace.id : "";
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );
  const notify = useCallback((message: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(message);
    toastTimer.current = setTimeout(() => setToast(""), 5000);
  }, []);
  const view = section || "overview";
  const { data, summary, loaded, pending, errors, refresh, retry } =
    useWorkspaceData(validRoute ? base : "", view, () =>
      router.replace("/signin"),
    );
  useEffect(() => {
    const updated = () =>
      api("/v1/auth/me")
        .then((result) => setUser(result.user))
        .catch(() => {});
    window.addEventListener("studio:profile-updated", updated);
    return () => window.removeEventListener("studio:profile-updated", updated);
  }, []);
  useEffect(() => {
    if (!validRoute) return;
    api("/v1/auth/me", { signal: AbortSignal.timeout(15000) })
      .then((result) => {
        if (result.user.verification_required) {
          router.replace("/verify-email");
          return;
        }
        setUser(result.user);
        setWorkspaces(result.workspaces);
        const selected = localStorage.getItem("studio.workspace");
        setWorkspace(
          result.workspaces.find((x: Row) => x.id === selected) ||
            result.workspaces[0],
        );
      })
      .catch((e) => {
        if (e.status === 401) router.replace("/signin");
        else
          setError(
            e.name === "TimeoutError"
              ? "Sign-in took too long. Check your connection and try again."
              : e.message,
          );
      })
      .finally(() => setInitial(false));
  }, [router, validRoute]);
  useEffect(() => {
    setMobile(false);
  }, [path]);
  if (!validRoute) return children;
  if (initial || !user || !workspace)
    return (
      <>
        {children}
        {error ? (
          <div className="loading-state loading-page">
            <h1>We couldn’t open your workspace.</h1>
            <p role="alert">{error}</p>
            <button
              className="btn primary"
              onClick={() => window.location.reload()}
            >
              Try again
            </button>
            <Link href="/signin" className="btn">
              Back to sign in
            </Link>
          </div>
        ) : (
          <LoadingState workspace label="Opening your workspace…" />
        )}
      </>
    );
  const ctx: StudioContext = {
    workspace,
    user,
    data,
    summary,
    capabilities: summary.capabilities || {},
    base,
    refresh,
    go: (p) => router.push("/app" + (p ? "/" + p : "")),
    notify,
    form: setFormSpec,
  };
  const title =
    [
      ...NAV.flatMap((x) => x.items),
      { path: "settings", title: "Settings" },
      { path: "billing", title: "Billing" },
      { path: "developers", title: "Developers" },
      { path: "team", title: "Team" },
      { path: "profile", title: "Your profile" },
    ].find((x) => x.path === section)?.title || "Overview";
  let content;
  if (section === "agents")
    content = <Agents ctx={ctx} id={path.split("/")[3]} />;
  else if (section === "knowledge")
    content = <Knowledge ctx={ctx} id={path.split("/")[3]} />;
  else if (section === "calls") content = <Calls ctx={ctx} />;
  else if (section === "voice") content = <VoiceLab ctx={ctx} />;
  else if (section === "products" || section === "widget")
    content = <Commerce ctx={ctx} widget={section === "widget"} />;
  else if (section === "campaigns") content = <CampaignManager ctx={ctx} />;
  else if (section === "inbox") content = <InboxPage ctx={ctx} />;
  else if (section === "leads") content = <Leads ctx={ctx} />;
  else if (section === "contacts") content = <ContactsPage ctx={ctx} />;
  else if (section === "billing") content = <BillingPage ctx={ctx} />;
  else if (section === "developers") content = <Developer ctx={ctx} />;
  else if (section === "integrations") content = <IntegrationPage ctx={ctx} />;
  else if (section === "operations") content = <OperationsPage ctx={ctx} />;
  else if (section === "tools") content = <ToolStudio ctx={ctx} />;
  else if (section === "models") content = <ModelStudio ctx={ctx} />;
  else if (section === "appointments") content = <Appointments ctx={ctx} />;
  else if (section === "numbers") content = <Numbers ctx={ctx} />;
  else if (section === "team") content = <TeamPage ctx={ctx} />;
  else if (section === "profile") content = <ProfilePage ctx={ctx} />;
  else if (section === "settings")
    content = <WorkspaceSettings ctx={ctx} team={false} />;
  else if (section === "templates") content = <Templates ctx={ctx} />;
  else content = <Dashboard ctx={ctx} />;
  const summaryReady = loaded.includes("summary");
  const viewReady = loaded.includes(view);
  const independent = [
    "profile",
    "settings",
    "templates",
    "operations",
  ].includes(view);
  const pageReady = viewReady && (summaryReady || independent);
  const pageError = errors[view] || (!independent ? errors.summary : "");
  return (
    <div className={"studio " + (collapsed ? "sidebar-collapsed" : "")}>
      <a href="#workspace-content" className="skip-link">
        Skip to content
      </a>
      {mobile && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <aside
        ref={sidebar}
        id="workspace-navigation"
        className={"sidebar " + (mobile ? "open" : "")}
        aria-label="Main navigation"
        aria-hidden={smallScreen && !mobile ? true : undefined}
        inert={smallScreen && !mobile ? true : undefined}
        role={mobile ? "dialog" : undefined}
        aria-modal={mobile ? true : undefined}
      >
        <button
          className="mobile-nav-close icon-button"
          onClick={() => setMobile(false)}
          aria-label="Close navigation"
        >
          <X size={20} />
        </button>
        <Link href="/app" className="brand" aria-label="Phirmy home">
          <span className="brand-icon">
            <AudioLines size={23} />
          </span>
          <span className="nav-label">
            Phirmy
          </span>
        </Link>
        <div className="workspace-switch">
          <span className="workspace-monogram">
            {workspace.name.slice(0, 1).toUpperCase()}
          </span>
          <select
            aria-label="Workspace"
            value={workspace.id}
            onChange={(e) => {
              const selected = workspaces.find((x) => x.id === e.target.value)!;
              localStorage.setItem("studio.workspace", selected.id);
              setWorkspace(selected);
            }}
            style={{
              padding: 0,
              background: "transparent",
              border: 0,
              color: "var(--ink)",
            }}
          >
            {workspaces.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </div>
        <nav className="sidebar-scroll">
          {NAV.map((group) => (
            <div key={group.label}>
              <div className="nav-heading">{group.label}</div>
              {group.items.map((item) => (
                <Link
                  href={"/app" + (item.path ? "/" + item.path : "")}
                  key={item.path}
                  title={item.title}
                  aria-label={item.title}
                  aria-current={section === item.path ? "page" : undefined}
                  className={
                    "nav-link " + (section === item.path ? "active" : "")
                  }
                >
                  <item.icon />
                  <span className="nav-label">{item.title}</span>
                  {item.path === "inbox" && summary.open_tickets > 0 && (
                    <span className="count">{summary.open_tickets}</span>
                  )}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <Link
            href="/app/billing"
            aria-label="Billing"
            className={"nav-link " + (section === "billing" ? "active" : "")}
          >
            <Wallet />
            <span className="nav-label">Billing</span>
            <span className="nav-label sidebar-balance">
              {money(summary.wallet?.balance_minor || 0)}
            </span>
          </Link>
          <Link
            href="/app/developers"
            aria-label="Developers"
            className={"nav-link " + (section === "developers" ? "active" : "")}
          >
            <Code2 />
            <span className="nav-label">Developers</span>
          </Link>
          <Link href="/docs" className="nav-link" aria-label="Documentation">
            <BookOpen />
            <span className="nav-label">Documentation</span>
          </Link>
          <Link
            href="/app/settings"
            aria-label="Settings"
            className={"nav-link " + (section === "settings" ? "active" : "")}
          >
            <Settings />
            <span className="nav-label">Settings</span>
          </Link>
          <div className="user-row">
            <Link
              href="/app/profile"
              className={"avatar " + (user.avatar_color || "sage")}
              aria-label="Your profile"
              title="Your profile"
            >
              {(user?.name || "You")
                .trim()
                .split(/\s+/)
                .filter(Boolean)
                .map((x: string) => x[0])
                .slice(0, 2)
                .join("") || "Y"}
            </Link>
            <Link href="/app/profile" className="nav-label">
              <strong>{user.name}</strong>
              <small>{workspace.role} workspace</small>
            </Link>
            <button
              title="Sign out"
              aria-label="Sign out"
              onClick={async () => {
                try {
                  await command("/v1/auth/signout");
                  router.replace("/signin");
                } catch (e) {
                  notify((e as Error).message);
                }
              }}
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell" inert={mobile ? true : undefined}>
        <header className="topbar">
          <div className="breadcrumb">
            <button
              ref={menuButton}
              className="icon-button navigation-toggle"
              onClick={() => {
                if (window.innerWidth <= 700) setMobile(!mobile);
                else {
                  setCollapsed(!collapsed);
                  localStorage.setItem(
                    "studio.sidebar-collapsed",
                    String(!collapsed),
                  );
                }
              }}
              aria-label={
                smallScreen && !mobile
                  ? "Open navigation"
                  : mobile
                    ? "Close navigation"
                    : collapsed
                      ? "Expand navigation"
                      : "Toggle navigation"
              }
              aria-expanded={smallScreen ? mobile : !collapsed}
              aria-controls="workspace-navigation"
            >
              {collapsed ? (
                <PanelLeftOpen size={19} />
              ) : (
                <PanelLeftClose size={19} />
              )}
            </button>
            <span>Workspace</span>
            <ChevronRight size={11} />
            <strong>{title}</strong>
          </div>
          <div className="top-actions">
            <ThemeSwitcher />
            <NotificationCenter key={base} base={base} />
            <Link
              href="/app/profile"
              className="icon-button profile-trigger"
              aria-label="Your profile"
              title="Your profile"
            >
              <UserRound size={18} />
            </Link>
            <Link
              href="/app/voice"
              className="btn small"
              aria-label="Test an agent"
              title="Test an agent"
            >
              <span className="test-agent-label">Test an agent</span>
              <ArrowUpRight size={12} />
            </Link>
          </div>
        </header>
        <main
          id="workspace-content"
          className="content"
          tabIndex={-1}
          aria-busy={!pageReady}
        >
          {savePreview && (
            <div className="notice">
              <div>
                <strong>
                  Your account is ready. Save your website assistant.
                </strong>
                <p>
                  The first save did not finish. Retry while the website preview
                  is still available.
                </p>
              </div>
              <button
                className="btn primary"
                disabled={savingPreview}
                onClick={async () => {
                  setSavingPreview(true);
                  try {
                    const saved = await command(base + "/preview/claim");
                    sessionStorage.removeItem("studio.preview");
                    setSavePreview(false);
                    await refresh();
                    router.replace("/app/agents/" + saved.agent_id);
                  } catch (e) {
                    notify((e as Error).message);
                  } finally {
                    setSavingPreview(false);
                  }
                }}
              >
                {savingPreview ? "Saving…" : "Save my assistant"}
              </button>
              <button
                className="btn subtle"
                onClick={() => {
                  setSavePreview(false);
                  router.replace("/app");
                }}
              >
                Dismiss
              </button>
            </div>
          )}
          {error && (
            <div className="error inline-error" role="alert">
              {error}
              <button className="btn subtle" onClick={() => setError("")}>
                Dismiss
              </button>
            </div>
          )}
          {children}
          {pageError && (
            <div className="error inline-error" role="alert">
              {pageError}{" "}
              <button className="btn" onClick={retry}>
                Retry loading
              </button>
            </div>
          )}
          {pageReady ? (
            <>
              {pending.includes(view) && (
                <p className="workspace-refresh-note" role="status">
                  Updating this page…
                </p>
              )}
              {content}
            </>
          ) : view === "overview" && summaryReady ? (
            <Dashboard ctx={ctx} pending />
          ) : (
            <WorkspacePageLoading
              label={"Loading " + title.toLowerCase() + "…"}
            />
          )}
        </main>
      </div>
      {formSpec && (
        <FormDialog
          key={formSpec.title}
          spec={formSpec}
          close={() => setFormSpec(null)}
        />
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
