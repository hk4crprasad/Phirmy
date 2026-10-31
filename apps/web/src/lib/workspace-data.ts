"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, Row, APIError } from "./api";

type Snapshot = {
  base: string;
  data: Record<string, Row[]>;
  summary: Row;
  loaded: string[];
  errors: Record<string, string>;
  pending: string[];
};
const empty = (base: string): Snapshot => ({
  base,
  data: {},
  summary: {},
  loaded: [],
  errors: {},
  pending: [],
});
const FRESH_MS = 45_000;

// Only authenticated, current-workspace memory is retained. No private API data
// goes into browser storage; a full reload always rechecks the session/server.
export function useWorkspaceData(
  base: string,
  view: string,
  unauthorized: () => void,
) {
  const [snapshot, setSnapshot] = useState<Snapshot>(() => empty(base));
  const activeBase = useRef(base);
  activeBase.current = base;
  const onUnauthorized = useRef(unauthorized);
  onUnauthorized.current = unauthorized;
  const flights = useRef(new Map<string, Promise<void>>());
  const controllers = useRef(new Map<string, AbortController>());
  const checked = useRef(new Map<string, number>());
  const change = useCallback(
    (scope: string, update: (current: Snapshot) => Snapshot) => {
      if (activeBase.current !== scope) return;
      setSnapshot((previous) =>
        update(previous.base === scope ? previous : empty(scope)),
      );
    },
    [],
  );
  const load = useCallback(
    async (page: string, force = false): Promise<void> => {
      if (!base) return;
      const key = base + ":" + page;
      const flight = flights.current.get(key);
      if (flight) {
        if (!force) return flight;
        await flight; // Mutation refresh follows any earlier read instead of sharing stale results.
        if (activeBase.current !== base) return;
        const followup = flights.current.get(key);
        if (followup) return followup;
      }
      if (!force && Date.now() - (checked.current.get(key) || 0) < FRESH_MS)
        return;
      const controller = new AbortController();
      controllers.current.set(key, controller);
      const deadline = setTimeout(() => controller.abort("timeout"), 15000);
      change(base, (current) => ({
        ...current,
        pending: [...new Set([...current.pending, page])],
        errors: { ...current.errors, [page]: "" },
      }));
      const task = (async () => {
        try {
          const result = await api(
            base + "/bootstrap?view=" + encodeURIComponent(page),
            { signal: controller.signal },
          );
          if (controller.signal.aborted || activeBase.current !== base) return;
          checked.current.set(key, Date.now());
          change(base, (current) => ({
            ...current,
            summary: page === "summary" ? result.summary : current.summary,
            data: { ...current.data, ...result.data },
            loaded: [...new Set([...current.loaded, page])],
            errors: { ...current.errors, [page]: "" },
          }));
        } catch (error) {
          if (
            activeBase.current !== base ||
            (controller.signal.aborted &&
              controller.signal.reason !== "timeout")
          )
            return;
          if (controller.signal.reason === "timeout") {
            change(base, (current) => ({
              ...current,
              errors: {
                ...current.errors,
                [page]:
                  "Loading took too long. Your navigation is still available; try this page again.",
              },
            }));
          } else if (error instanceof APIError && error.status === 401)
            onUnauthorized.current();
          else
            change(base, (current) => ({
              ...current,
              errors: { ...current.errors, [page]: (error as Error).message },
            }));
        } finally {
          clearTimeout(deadline);
          if (controllers.current.get(key) === controller) {
            controllers.current.delete(key);
            flights.current.delete(key);
            change(base, (current) => ({
              ...current,
              pending: current.pending.filter((item) => item !== page),
            }));
          }
        }
      })();
      flights.current.set(key, task);
      return task;
    },
    [base, change],
  );
  useEffect(() => {
    return () => {
      controllers.current.forEach((controller) => controller.abort());
      controllers.current.clear();
      flights.current.clear();
      checked.current.clear();
    };
  }, [base]);
  useEffect(() => {
    if (base) {
      void load("summary");
      void load(view);
    }
  }, [base, view, load]);
  useEffect(() => {
    const resume = () => {
      if (!document.hidden && base) {
        void load(view);
        void load("summary");
      }
    };
    window.addEventListener("focus", resume);
    window.addEventListener("online", resume);
    document.addEventListener("visibilitychange", resume);
    return () => {
      window.removeEventListener("focus", resume);
      window.removeEventListener("online", resume);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [base, view, load]);
  const refresh = useCallback(async () => {
    checked.current.clear();
    await Promise.all([load("summary", true), load(view, true)]);
  }, [view, load]);
  // Poll only the visible page, only while visible, and never overlap a fetch.
  const current = snapshot.base === base ? snapshot : empty(base);
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.hidden) return;
      const jobsActive = (current.data.jobs || []).some((job) =>
        ["queued", "running"].includes(job.state),
      );
      const callsActive = (current.data.calls || []).some(
        (call) =>
          !["completed", "failed", "canceled", "busy", "no_answer"].includes(
            call.state,
          ),
      );
      if (
        (jobsActive &&
          ["overview", "agents", "knowledge", "products"].includes(view)) ||
        (callsActive && ["overview", "calls"].includes(view))
      ) {
        if (!flights.current.size) {
          void load(view, true);
          void load("summary", true);
        }
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [current.data.jobs, current.data.calls, view, load]);
  return {
    ...current,
    refresh,
    retry: () => {
      void load(view, true);
      void load("summary", true);
    },
  };
}
