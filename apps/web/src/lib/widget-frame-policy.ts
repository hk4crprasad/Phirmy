import { createClient } from "@redis/client";
import config from "../../../../config/widget-frame-cache.json";

const newClient = () => createClient({
  url: process.env.REDIS_URL,
  socket: { connectTimeout: 150, socketTimeout: 200, reconnectStrategy: false },
  disableOfflineQueue: true,
  commandsQueueMaxLength: 128,
});
type CacheClient = ReturnType<typeof newClient>;
let client: CacheClient | undefined;
let connecting: Promise<CacheClient | undefined> | undefined;
let retryAfter = 0;

async function cacheClient() {
  if (!process.env.REDIS_URL || Date.now() < retryAfter) return;
  if (client?.isReady) return client;
  if (connecting) return connecting;
  const candidate = newClient();
  // Never log a Redis URL, credential or raw network exception.
  candidate.on("error", () => {});
  connecting = (async () => {
    try {
      await candidate.connect();
      const policy = await candidate
        .withCommandOptions({ abortSignal: AbortSignal.timeout(100) })
        .configGet("maxmemory-policy");
      if (policy["maxmemory-policy"] !== "noeviction") {
        candidate.destroy();
        retryAfter = Date.now() + 60_000;
        return;
      }
      client = candidate;
      return candidate;
    } catch {
      if (candidate.isOpen) candidate.destroy();
      retryAfter = Date.now() + 1000;
      return;
    } finally {
      connecting = undefined;
    }
  })();
  return connecting;
}

function origins(policy: unknown): string[] {
  if (!policy || typeof policy !== "object") return [];
  const values = (policy as { frame_ancestors?: unknown }).frame_ancestors;
  if (!Array.isArray(values)) return [];
  return values.flatMap((value: unknown) => {
    if (typeof value !== "string") return [];
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && value === url.origin
        ? [url.origin]
        : [];
    } catch {
      return [];
    }
  });
}

export async function widgetFrameAncestors(id: string): Promise<string[]> {
  try {
    const cache = await cacheClient();
    if (cache) {
      const cached = await cache
        .withCommandOptions({ abortSignal: AbortSignal.timeout(100) })
        .eval(config.read_script, {
          keys: [`${process.env.WIDGET_FRAME_CACHE_NAMESPACE || config.namespace}:${id}`],
          arguments: [],
        });
      if (typeof cached === "string") return origins(JSON.parse(cached));
    }
  } catch {
    // No process-local stale grants. Fall through to the authoritative API.
  }
  try {
    const response = await fetch(
      `${process.env.API_ORIGIN || "http://127.0.0.1:8100"}/v1/public/widgets/${encodeURIComponent(id)}/frame-policy`,
      { cache: "no-store", signal: AbortSignal.timeout(2000) },
    );
    if (response.ok) return origins(await response.json());
  } catch {}
  return []; // An unavailable policy never permits external framing.
}
