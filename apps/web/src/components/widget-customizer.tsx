"use client";
import { useEffect, useState, CSSProperties } from "react";
import {
  MessageCircle,
  Sparkles,
  X,
  RotateCcw,
  Save,
  Monitor,
  Smartphone,
} from "lucide-react";
import { api, command, Row } from "@/lib/api";
import { Dialog, StudioContext } from "./ui";
import "./widget-customizer.css";
import "../../public/widget-designs.css";
import { widgetDesigns, legacyWidgetLayouts } from "@/lib/widget-designs";
import OriginVerification from "./origin-verification";
import WidgetProtection from "./widget-protection";

const styles: Row = {
  color_mode: "light",
  preset: "minimal",
  accent_color: "#393632",
  background_color: "#ffffff",
  text_color: "#242321",
  button_text_color: "#ffffff",
  user_message_color: "#393632",
  user_text_color: "#ffffff",
  border_color: "#e7e3de",
  launcher_shape: "pill",
  launcher_icon: "chat",
  font_family: "system",
  corner_radius: 16,
  widget_width: 350,
  widget_height: 510,
  offset_x: 22,
  offset_y: 22,
  position: "right",
};
const fonts: Row = {
  system: "system-ui, sans-serif",
  serif: "Georgia, serif",
  rounded: "ui-rounded, system-ui, sans-serif",
};
export default function WidgetCustomizer({
  ctx,
  installation,
  close,
  saved,
}: {
  ctx: StudioContext;
  installation: Row;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const [theme, setTheme] = useState<Row>({
    ...styles,
    assistant_name: installation.name,
    welcome_message: "Hello! How can I help?",
    launcher_label: "Ask us",
    input_placeholder: "Ask a question…",
    send_button_label: "Send",
    status_text: "AI assistant",
    tone: "agent",
    ...installation.theme,
  });
  const [deviceDark, setDeviceDark] = useState(false);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const change = () => setDeviceDark(media.matches);
    change();
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  const [origins, setOrigins] = useState<string>(
    installation.allowed_origins.join(", "),
  );
  const [enabled, setEnabled] = useState(installation.enabled);
  const [tab, setTab] = useState("brand"),
    [mobile, setMobile] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null),
    [fileUrl, setFileUrl] = useState(""),
    [removeLogo, setRemoveLogo] = useState(false);
  const set = (key: string, value: any) =>
    setTheme((old) => ({
      ...old,
      [key]: value,
      ...(key === "preset" &&
        widgetDesigns.find((design) => design.id === value)?.theme),
      ...(key === "preset" &&
      !widgetDesigns.some((design) => design.id === value)
        ? {
            widget_width:
              value === "compact" ? 300 : value === "panel" ? 390 : 350,
            widget_height: value === "compact" ? 390 : 510,
            corner_radius: value === "bubble" ? 25 : 16,
          }
        : {}),
    }));
  useEffect(() => {
    if (!file) {
      setFileUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setFileUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const logo = removeLogo
    ? ""
    : fileUrl ||
      (theme.logo_path && !theme.logo_url
        ? "/backend" + theme.logo_path
        : theme.logo_url);
  function text(key: string, label: string, max: number, multiline = false) {
    return (
      <label key={key}>
        {label}
        {multiline ? (
          <textarea
            aria-label={label}
            value={theme[key] || ""}
            maxLength={max}
            onChange={(e) => set(key, e.target.value)}
            rows={3}
          />
        ) : (
          <input
            aria-label={label}
            value={theme[key] || ""}
            maxLength={max}
            onChange={(e) => set(key, e.target.value)}
          />
        )}
      </label>
    );
  }
  function select(key: string, label: string, options: string[][]) {
    return (
      <label key={key}>
        {label}
        <select
          aria-label={label}
          value={theme[key]}
          onChange={(e) => set(key, e.target.value)}
        >
          {options.map(([value, title]) => (
            <option key={value} value={value}>
              {title}
            </option>
          ))}
        </select>
      </label>
    );
  }
  function number(key: string, label: string, min: number, max: number) {
    return (
      <label key={key}>
        {label}
        <input
          type="number"
          aria-label={label}
          value={theme[key]}
          min={min}
          max={max}
          required
          onChange={(e) => set(key, Number(e.target.value))}
        />
      </label>
    );
  }
  function color(key: string, label: string) {
    return (
      <label key={key}>
        {label}
        <span className="widget-color-input">
          <input
            type="color"
            aria-label={label + " picker"}
            value={/^#[0-9a-f]{6}$/i.test(theme[key]) ? theme[key] : "#000000"}
            onChange={(e) => set(key, e.target.value)}
          />
          <input
            aria-label={label + " hex"}
            value={theme[key]}
            maxLength={7}
            pattern="#[0-9a-fA-F]{6}"
            required
            onChange={(e) => set(key, e.target.value)}
          />
        </span>
      </label>
    );
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = {
        agent_id: installation.agent_id,
        name: installation.name,
        enabled,
        allowed_origins: origins
          .split(",")
          .map((x: string) => x.trim())
          .filter(Boolean),
        theme: {
          ...theme,
          ...(removeLogo || file ? { logo_url: "" } : {}),
          logo_remove: removeLogo,
        },
      };
      if (file) {
        const data = new FormData();
        data.append("file", file);
        data.append("settings_json", JSON.stringify(payload));
        await api(ctx.base + "/installations/" + installation.id + "/logo", {
          method: "POST",
          body: data,
        });
      } else {
        await command(
          ctx.base + "/installations/" + installation.id,
          payload,
          "PUT",
        );
      }
      await saved();
      await ctx.refresh();
      ctx.notify("Widget settings saved");
      close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const previewStyle = {
    "--preview-surface":
      theme.color_mode === "auto" && deviceDark
        ? "#272624"
        : theme.background_color,
    "--preview-ink":
      theme.color_mode === "auto" && deviceDark ? "#f4f1ec" : theme.text_color,
    "--preview-primary": theme.accent_color,
    "--preview-on-primary": theme.button_text_color,
    "--preview-user": theme.user_message_color,
    "--preview-on-user": theme.user_text_color,
    "--preview-line":
      theme.color_mode === "auto" && deviceDark
        ? "#48443f"
        : theme.border_color,
    fontFamily: fonts[theme.font_family],
    borderRadius: theme.corner_radius,
  } as CSSProperties;
  return (
    <Dialog
      title="Your assistant’s appearance"
      className="widget-customizer-modal"
      close={() => !busy && close()}
    >
      <form className="widget-customizer" onSubmit={submit}>
        <div className="widget-customizer-intro">
          <p>
            Match your website, shape your greeting, and choose how your
            assistant speaks. Saved changes reach your installed widget when the
            page reloads.
          </p>
        </div>
        <div className="widget-customizer-grid">
          <div className="widget-controls">
            <div
              className="tabs"
              role="tablist"
              aria-label="Widget settings sections"
            >
              {[
                ["brand", "Brand"],
                ["style", "Style"],
                ["messages", "Messages & tone"],
                ["website", "Website"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={tab === value}
                  className={"tab " + (tab === value ? "active" : "")}
                  onClick={() => setTab(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div
              className="widget-fields"
              role="tabpanel"
              aria-label={tab + " settings"}
            >
              {tab === "brand" && (
                <>
                  <h3>Make it yours</h3>
                  {text("assistant_name", "Assistant name", 160)}
                  {text("launcher_label", "Launcher label", 80)}
                  <label>
                    Upload logo
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      onChange={(e) => {
                        const next = e.target.files?.[0] || null;
                        if (next && next.size > 2_000_000) {
                          setError("Choose a logo smaller than 2 MB");
                          return;
                        }
                        setFile(next);
                        setRemoveLogo(false);
                        setError("");
                      }}
                    />
                    <span className="field-note">
                      PNG, JPEG or WebP, up to 2 MB. Your logo appears in the
                      chat header.
                    </span>
                  </label>
                  {text("logo_url", "Logo URL · HTTPS", 2048)}
                  {(logo || file) && (
                    <button
                      type="button"
                      className="btn small"
                      onClick={() => {
                        setRemoveLogo(true);
                        setFile(null);
                        setTheme((old) => ({
                          ...old,
                          logo_url: "",
                          logo_path: "",
                        }));
                      }}
                    >
                      <X size={14} /> Remove logo
                    </button>
                  )}
                  {select("font_family", "Font family", [
                    ["system", "Website-friendly system"],
                    ["serif", "Classic serif"],
                    ["rounded", "Soft rounded"],
                  ])}
                </>
              )}
              {tab === "style" && (
                <>
                  <h3>Colours & shape</h3>
                  <label>
                    Colour mode
                    <select
                      aria-label="Colour mode"
                      value={theme.color_mode}
                      onChange={(e) =>
                        setTheme((old) => ({
                          ...old,
                          color_mode: e.target.value,
                          background_color:
                            e.target.value === "dark" ? "#272624" : "#ffffff",
                          text_color:
                            e.target.value === "dark" ? "#f4f1ec" : "#242321",
                          border_color:
                            e.target.value === "dark" ? "#48443f" : "#e7e3de",
                        }))
                      }
                    >
                      <option value="light">Light</option>
                      <option value="dark">Dark</option>
                      <option value="auto">Follow visitor device</option>
                    </select>
                  </label>
                  <div className="widget-field-pair">
                    {color("accent_color", "Button colour")}
                    {color("button_text_color", "Button text colour")}
                    {color("background_color", "Panel colour")}
                    {color("text_color", "Text colour")}
                    {color("user_message_color", "Visitor bubble colour")}
                    {color("user_text_color", "Visitor text colour")}
                    {color("border_color", "Border colour")}
                  </div>
                  {select("preset", "Widget style", [
                    ...widgetDesigns.map((design) => [design.id, design.label]),
                    ...legacyWidgetLayouts,
                  ])}
                  <p className="field-note">
                    {
                      widgetDesigns.find((design) => design.id === theme.preset)
                        ?.description
                    }{" "}
                    Choose a starting style, then fine-tune the colours and
                    layout.
                  </p>
                  <div className="widget-field-pair">
                    {select("launcher_shape", "Button shape", [
                      ["pill", "Pill"],
                      ["rounded", "Rounded rectangle"],
                      ["circle", "Icon circle"],
                    ])}
                    {select("launcher_icon", "Button icon", [
                      ["chat", "Chat"],
                      ["sparkle", "Sparkle"],
                      ["logo", "Brand logo"],
                      ["none", "Text only"],
                    ])}
                    {number("corner_radius", "Corner radius · px", 0, 28)}
                    {select("position", "Position", [
                      ["right", "Bottom right"],
                      ["left", "Bottom left"],
                    ])}
                    {number("widget_width", "Panel width · px", 280, 480)}
                    {number("widget_height", "Panel height · px", 360, 720)}
                    {number("offset_x", "Side spacing · px", 8, 64)}
                    {number("offset_y", "Bottom spacing · px", 8, 64)}
                  </div>
                  <button
                    className="btn subtle small"
                    type="button"
                    onClick={() => setTheme((old) => ({ ...old, ...styles }))}
                  >
                    <RotateCcw size={14} /> Reset styling
                  </button>
                </>
              )}
              {tab === "messages" && (
                <>
                  <h3>Your conversation</h3>
                  {text("welcome_message", "Welcome message", 500, true)}
                  {text("input_placeholder", "Input placeholder", 120)}
                  {text("send_button_label", "Send button label", 40)}
                  {text("status_text", "Footer text", 100)}
                  {select("tone", "Response tone", [
                    ["agent", "Use the agent’s tone"],
                    ["professional", "Professional"],
                    ["friendly", "Friendly"],
                    ["warm", "Warm & reassuring"],
                    ["concise", "Concise & direct"],
                  ])}
                  <p className="field-note">
                    Tone changes how this widget replies. Its connected
                    knowledge, tools and factual rules stay in place.
                  </p>
                </>
              )}
              {tab === "website" && (
                <>
                  <h3>Website controls</h3>
                  <p className="field-note">
                    Only the listed, verified websites can start conversations.
                    Your platform preview remains available on this application.
                  </p>
                  <label>
                    Website origins · comma separated
                    <textarea
                      value={origins}
                      required
                      rows={3}
                      onChange={(e) => setOrigins(e.target.value)}
                    />
                  </label>
                  <p className="field-note">
                    Use complete origins such as https://yourwebsite.com. These
                    define permitted site navigation and widget placement. Each
                    external origin requires ownership verification.
                  </p>
                  <OriginVerification
                    base={ctx.base}
                    origins={origins.split(",").map((value) => value.trim())}
                  />
                  <WidgetProtection
                    base={ctx.base}
                    installationId={installation.id}
                  />
                  <label className="widget-checkbox">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                    />{" "}
                    Show this widget on its websites
                  </label>
                  <label className="widget-checkbox">
                    <input
                      type="checkbox"
                      checked={theme.collect_email === true}
                      onChange={(e) => set("collect_email", e.target.checked)}
                    />{" "}
                    Ask for email before starting chat
                  </label>
                  <p className="field-note">
                    Email collection starts off. Shared addresses remain marked
                    unverified until email proof. Promotional consent is saved
                    only after verification and approved consent wording is
                    enabled.
                  </p>
                  <label className="widget-checkbox">
                    <input
                      type="checkbox"
                      checked={theme.voice_input_enabled !== false}
                      onChange={(e) =>
                        set("voice_input_enabled", e.target.checked)
                      }
                    />{" "}
                    Offer microphone voice input
                  </label>
                  <p className="field-note">
                    Voice input transcribes up to 30 seconds into editable text.
                    Requires HTTPS and visitor microphone permission.
                  </p>
                  <label className="widget-checkbox">
                    <input
                      type="checkbox"
                      checked={!!theme.voice_enabled}
                      onChange={(e) => set("voice_enabled", e.target.checked)}
                    />{" "}
                    Offer voice conversations
                  </label>
                  <p className="field-note">
                    Requires connected speech and model providers. Visitors
                    choose microphone access.
                  </p>
                  <label className="widget-checkbox">
                    <input
                      type="checkbox"
                      checked={theme.website_actions ?? true}
                      onChange={(e) => set("website_actions", e.target.checked)}
                    />{" "}
                    Allow indexed page navigation and scrolling
                  </label>
                </>
              )}
            </div>
          </div>
          <aside className="widget-preview-area">
            <div className="row between">
              <strong>Live preview</strong>
              <div className="row">
                <button
                  type="button"
                  aria-label="Desktop preview"
                  aria-pressed={!mobile}
                  className="btn subtle small"
                  onClick={() => setMobile(false)}
                >
                  <Monitor size={16} />
                </button>
                <button
                  type="button"
                  aria-label="Mobile preview"
                  aria-pressed={mobile}
                  className="btn subtle small"
                  onClick={() => setMobile(true)}
                >
                  <Smartphone size={16} />
                </button>
              </div>
            </div>
            <p className="field-note">Preview your look before saving.</p>
            <div
              className={"widget-preview-canvas " + (mobile ? "mobile" : "")}
            >
              <div
                className={
                  "widget-preview-stack wd-root " +
                  (theme.position === "left" ? "left" : "")
                }
                data-widget-design={theme.preset}
                style={previewStyle}
              >
                <div
                  className={"widget-preview-panel wd-panel " + theme.preset}
                  style={{
                    borderRadius: theme.corner_radius,
                    width: theme.widget_width,
                    maxWidth: "100%",
                  }}
                >
                  <div className="widget-preview-header wd-header">
                    {logo && (
                      <img
                        src={logo}
                        alt="Widget logo preview"
                        onLoad={(e) => (e.currentTarget.style.visibility = "")}
                        onError={(e) =>
                          (e.currentTarget.style.visibility = "hidden")
                        }
                      />
                    )}
                    <strong>{theme.assistant_name || "Your assistant"}</strong>
                    <X size={16} />
                  </div>
                  <div className="widget-preview-messages wd-log">
                    <div className="wd-message">
                      {theme.welcome_message || "Hello! How can I help?"}
                    </div>
                    <div className="visitor wd-message wd-user">
                      I have a question about a product.
                    </div>
                    <div className="wd-message">
                      I’d be happy to help. What would you like to know?
                    </div>
                  </div>
                  <div className="widget-preview-composer wd-composer">
                    <span>{theme.input_placeholder || "Ask a question…"}</span>
                    <b>{theme.send_button_label || "Send"}</b>
                  </div>
                  <small className="wd-footer">
                    {theme.status_text || "AI assistant"}
                  </small>
                </div>
                <div
                  className={
                    "widget-preview-launcher wd-launcher " +
                    theme.launcher_shape
                  }
                  aria-label="Launcher preview"
                >
                  {theme.launcher_icon === "logo" && logo ? (
                    <img
                      src={logo}
                      alt=""
                      style={{ width: 20, height: 20, objectFit: "contain" }}
                      onError={(e) =>
                        (e.currentTarget.style.visibility = "hidden")
                      }
                    />
                  ) : theme.launcher_icon === "sparkle" ? (
                    <Sparkles size={18} />
                  ) : theme.launcher_icon === "chat" ||
                    theme.launcher_shape === "circle" ||
                    theme.launcher_icon === "logo" ? (
                    <MessageCircle size={18} />
                  ) : null}
                  {theme.launcher_shape !== "circle" &&
                    (theme.launcher_label || "Ask us")}
                </div>
              </div>
            </div>
          </aside>
        </div>
        <div className="widget-customizer-footer">
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <span className="field-note">{installation.name}</span>
          <div className="row">
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={close}
            >
              Cancel
            </button>
            <button className="btn primary" disabled={busy}>
              <Save size={15} /> {busy ? "Saving…" : "Save widget"}
            </button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}
