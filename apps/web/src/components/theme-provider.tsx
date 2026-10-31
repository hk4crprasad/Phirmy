"use client";

import { createContext, useContext, useEffect, useState, useRef } from "react";

type Preference = "light" | "dark" | "system";
type Theme = {
  preference: Preference;
  resolved: "light" | "dark";
  setPreference: (value: Preference) => void;
};
const Context = createContext<Theme>({
  preference: "system",
  resolved: "light",
  setPreference: () => {},
});
export const THEME_KEY = "studio.color-theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = useState<Preference>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("light");
  const memory = useRef<Preference>("system");
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    function sync() {
      let choice: Preference = "system";
      try {
        const saved = localStorage.getItem(THEME_KEY);
        if (saved === "light" || saved === "dark") choice = saved;
      } catch {
        choice = memory.current;
      }
      const theme =
        choice === "system" ? (media.matches ? "dark" : "light") : choice;
      document.documentElement.dataset.theme = theme;
      document.documentElement.style.colorScheme = theme;
      setPreferenceState(choice);
      memory.current = choice;
      setResolved(theme);
    }
    sync();
    media.addEventListener("change", sync);
    window.addEventListener("storage", sync);
    return () => {
      media.removeEventListener("change", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  function setPreference(value: Preference) {
    memory.current = value;
    try {
      localStorage.setItem(THEME_KEY, value);
    } catch {}
    // Also apply immediately when browser storage is unavailable.
    const theme =
      value === "system"
        ? window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light"
        : value;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    setPreferenceState(value);
    setResolved(theme);
  }
  return (
    <Context.Provider value={{ preference, resolved, setPreference }}>
      {children}
    </Context.Provider>
  );
}

export const useTheme = () => useContext(Context);
