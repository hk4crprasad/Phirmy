"use client";
import { useEffect, useRef, useState } from "react";
import { Sun, Moon, Monitor, Check } from "lucide-react";
import { useTheme } from "./theme-provider";

export default function ThemeSwitcher() {
  const { preference, resolved, setPreference } = useTheme();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null),
    trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    root.current
      ?.querySelector<HTMLButtonElement>(
        '[role="menuitemradio"][aria-checked="true"]',
      )
      ?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
      if (event.key === "Tab") setOpen(false);
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const items = Array.from(
        root.current?.querySelectorAll<HTMLButtonElement>(
          '[role="menuitemradio"]',
        ) || [],
      );
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? items.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) %
              items.length;
      items[next]?.focus();
    };
    document.addEventListener("pointerdown", outside);
    root.current?.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", outside);
      root.current?.removeEventListener("keydown", key);
    };
  }, [open]);
  return (
    <div className="theme-switcher" ref={root}>
      <button
        ref={trigger}
        className="icon-button theme-trigger"
        aria-label="Color theme"
        title="Color theme"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {resolved === "dark" ? <Moon size={18} /> : <Sun size={18} />}
      </button>
      {open && (
        <div className="theme-menu" role="menu" aria-label="Color theme">
          {(
            [
              { value: "light", label: "Light", Icon: Sun },
              { value: "dark", label: "Dark", Icon: Moon },
              { value: "system", label: "Use device setting", Icon: Monitor },
            ] as const
          ).map(({ value, label, Icon }) => (
            <button
              key={value}
              role="menuitemradio"
              aria-checked={preference === value}
              onClick={() => {
                setPreference(value);
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <Icon size={15} />
              <span>{label}</span>
              {preference === value && <Check size={14} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
