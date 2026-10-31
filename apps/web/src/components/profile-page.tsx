"use client";
import { useEffect, useState } from "react";
import {
  Check,
  LogIn,
  LogOut,
  ShieldCheck,
  MonitorSmartphone,
  Save,
} from "lucide-react";
import { api, command, Row, when } from "@/lib/api";
import { Header, Panel, StudioContext } from "./ui";

export default function ProfilePage({ ctx }: { ctx: StudioContext }) {
  const [profile, setProfile] = useState<Row>(ctx.user),
    [sessions, setSessions] = useState<Row[]>([]),
    [busy, setBusy] = useState(false),
    [google, setGoogle] = useState(false),
    [error, setError] = useState("");
  const load = () =>
    api("/v1/auth/sessions")
      .then((r) => setSessions(r.items))
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api("/v1/auth/providers")
      .then((r) => setGoogle(r.google))
      .catch(() => {});
  }, []);
  return (
    <>
      <Header
        eyebrow="YOUR ACCOUNT"
        title="Make yourself at home."
        description="Your profile, preferences and the devices you trust."
      />
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="profile-grid">
        <Panel title="Personal details">
          <form
            className="panel-body"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                const r = await command(
                  "/v1/auth/profile",
                  {
                    name: profile.name,
                    timezone: profile.timezone || "Asia/Kolkata",
                    avatar_color: profile.avatar_color || "sage",
                    notifications_enabled:
                      profile.notifications_enabled !== false,
                  },
                  "PATCH",
                );
                setProfile(r.user);
                window.dispatchEvent(new CustomEvent("studio:profile-updated"));
                ctx.notify("Profile saved");
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <div
              className={"profile-avatar " + (profile.avatar_color || "sage")}
            >
              {(profile.name || "You")
                .split(" ")
                .map((x: string) => x[0])
                .slice(0, 2)
                .join("")}
            </div>
            <label>
              Your name
              <input
                value={profile.name || ""}
                onChange={(e) =>
                  setProfile({ ...profile, name: e.target.value })
                }
                maxLength={120}
                required
                autoComplete="name"
              />
            </label>
            <label>
              Email
              <input value={profile.email || ""} readOnly type="email" />
            </label>
            <span className="field-note">
              <ShieldCheck size={14} />{" "}
              {profile.email_verified
                ? "Verified email"
                : "Email verification pending"}
            </span>
            <label>
              Timezone
              <input
                value={profile.timezone || "Asia/Kolkata"}
                onChange={(e) =>
                  setProfile({ ...profile, timezone: e.target.value })
                }
                list="profile-timezones"
                required
              />
            </label>
            <datalist id="profile-timezones">
              {[
                "Asia/Kolkata",
                "Europe/London",
                "America/New_York",
                "America/Los_Angeles",
                "Asia/Dubai",
                "Asia/Singapore",
                "Australia/Sydney",
                "UTC",
              ].map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
            <fieldset className="avatar-choices">
              <legend>Profile color</legend>
              {["sage", "forest", "clay", "sand", "lavender"].map((color) => (
                <label key={color} className={"avatar-choice " + color}>
                  <input
                    type="radio"
                    name="avatar_color"
                    value={color}
                    checked={(profile.avatar_color || "sage") === color}
                    onChange={() =>
                      setProfile({ ...profile, avatar_color: color })
                    }
                  />
                  <span>{color}</span>
                </label>
              ))}
            </fieldset>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={profile.notifications_enabled !== false}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    notifications_enabled: e.target.checked,
                  })
                }
              />
              Show unread notification badges
            </label>
            <button className="btn primary" disabled={busy}>
              <Save size={15} />
              {busy ? "Saving…" : "Save profile"}
            </button>
          </form>
        </Panel>
        <div className="stack">
          <Panel title="Sign-in & security">
            <div className="panel-body stack">
              <div className="security-item">
                <LogIn />
                <div>
                  <strong>Google</strong>
                  <p className="muted small-text">
                    {profile.providers?.includes("google")
                      ? "Your Google account is connected."
                      : "Connect the Google account that matches your email."}
                  </p>
                </div>
                {profile.providers?.includes("google") ? (
                  <Check size={18} />
                ) : (
                  <a
                    className={"btn small " + (!google ? "is-disabled" : "")}
                    aria-disabled={!google}
                    href={
                      google
                        ? "/backend/v1/auth/google/start?return_to=/app/profile"
                        : undefined
                    }
                  >
                    Connect
                  </a>
                )}
              </div>
              <div className="security-item">
                <ShieldCheck />
                <div>
                  <strong>Password</strong>
                  <p className="muted small-text">
                    {profile.has_password
                      ? "Update your password and sign out old sessions."
                      : "Set a password using a secure email link."}
                  </p>
                </div>
                <button
                  className="btn small"
                  onClick={() =>
                    ctx.form({
                      title: "Update your password",
                      description:
                        "Every device will be signed out after this change.",
                      fields: profile.has_password
                        ? [
                            {
                              key: "current_password",
                              label: "Current password",
                              type: "password",
                              required: true,
                            },
                            {
                              key: "new_password",
                              label: "New password · at least 12 characters",
                              type: "password",
                              required: true,
                            },
                          ]
                        : [],
                      action: async (values) => {
                        if (profile.has_password) {
                          await command("/v1/auth/password", values);
                          window.location.assign("/signin");
                        } else {
                          await command("/v1/auth/forgot-password", {
                            email: profile.email,
                          });
                          ctx.notify(
                            "Check your email for a secure password link",
                          );
                        }
                      },
                    })
                  }
                >
                  {profile.has_password ? "Change" : "Set password"}
                </button>
              </div>
            </div>
          </Panel>
          <Panel title="Your devices">
            <div className="panel-body stack">
              <p className="muted small-text">
                Sessions expire automatically. You can end access at any time.
              </p>
              {sessions.map((s) => (
                <div className="session-item" key={s.id}>
                  <MonitorSmartphone size={19} />
                  <div>
                    <strong>
                      {s.current ? "This device" : "Another device"}
                    </strong>
                    <p className="small-text muted">
                      {s.user_agent.includes("Mobile")
                        ? "Mobile browser"
                        : s.user_agent.includes("Firefox")
                          ? "Firefox"
                          : s.user_agent.includes("Chrome")
                            ? "Chrome"
                            : "Browser session"}{" "}
                      · Last active {when(s.last_seen_at)}
                    </p>
                  </div>
                  {!s.current && (
                    <button
                      className="btn subtle"
                      aria-label="Sign out device"
                      onClick={async () => {
                        try {
                          await api("/v1/auth/sessions/" + s.id, {
                            method: "DELETE",
                          });
                          load();
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }}
                    >
                      <LogOut size={16} />
                    </button>
                  )}
                </div>
              ))}
              <button
                className="btn"
                disabled={sessions.length < 2}
                onClick={async () => {
                  try {
                    await command("/v1/auth/sessions/revoke-others");
                    await load();
                    ctx.notify("Other devices signed out");
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                <LogOut size={15} />
                Sign out other devices
              </button>
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
