import { NextRequest, NextResponse } from "next/server";
import { legalDocuments } from "@/lib/legal";
import { widgetFrameAncestors } from "@/lib/widget-frame-policy";

const publicAssets = new Set([
  "/widget.js", "/bot-challenge.js", "/pcm-capture.js", "/widget-designs.css",
]);

export async function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const development = process.env.NODE_ENV === "development";
  const isWidget = request.nextUrl.pathname.startsWith("/widget/");
  // Next's listener origin can be 0.0.0.0 even when the browser uses loopback.
  const pageOrigin = new URL(request.nextUrl.origin);
  const host = request.headers.get("host");
  if (host && /^[A-Za-z0-9.:[\]-]+$/.test(host)) pageOrigin.host = host;
  const connectionOrigins = new Set([pageOrigin.origin.replace(/^http/, "ws")]);
  const localPage = ["localhost", "127.0.0.1"].includes(pageOrigin.hostname);
  for (const configured of [
    process.env.PUBLIC_API_ORIGIN,
    localPage ? process.env.API_ORIGIN : undefined,
  ]) {
    if (!configured) continue;
    try {
      const api = new URL(configured);
      if (
        ["http:", "https:"].includes(api.protocol) &&
        (localPage || !["localhost", "127.0.0.1"].includes(api.hostname))
      ) {
        connectionOrigins.add(api.origin);
        connectionOrigins.add(api.origin.replace(/^http/, "ws"));
      }
    } catch {}
  }
  const ancestors = ["'self'"];
  if (isWidget) {
    const id = request.nextUrl.pathname.split("/")[2];
    if (/^[A-Za-z0-9_-]{1,100}$/.test(id)) {
      ancestors.push(...await widgetFrameAncestors(id));
    }
  }
  const policy = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    // Existing UI uses inline style attributes. Executable inline scripts still require a nonce.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' https: data: blob:",
    "font-src 'self'",
    `connect-src 'self' ${[...connectionOrigins].join(" ")} https://challenges.cloudflare.com${!isWidget ? " https://api.razorpay.com https://checkout.razorpay.com" : ""}`,
    "media-src 'self' blob: data:",
    "worker-src 'self' blob:",
    `frame-src 'self' https://challenges.cloudflare.com${!isWidget ? " https://api.razorpay.com https://checkout.razorpay.com" : ""}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    `frame-ancestors ${isWidget ? ancestors.join(" ") : "'none'"}`,
    ...(!development && request.nextUrl.protocol === "https:"
      ? ["upgrade-insecure-requests"]
      : []),
  ].join("; ");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const legalParts = request.nextUrl.pathname.split("/");
  const invalidLegal =
    request.nextUrl.pathname.startsWith("/legal/") &&
    (legalParts.length !== 3 || !Object.hasOwn(legalDocuments, legalParts[2]));
  const response = invalidLegal
    ? new NextResponse("Legal document not found", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      })
    : NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("Cache-Control",
    publicAssets.has(request.nextUrl.pathname) && ["GET", "HEAD"].includes(request.method)
      ? "public, max-age=60, must-revalidate"
      : "private, no-store",
  );
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  if (!isWidget) response.headers.set("X-Frame-Options", "DENY");
  if (!development)
    response.headers.set(
      "Strict-Transport-Security",
      "max-age=31536000; includeSubDomains",
    );
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|backend/|favicon.ico).*)"],
};
