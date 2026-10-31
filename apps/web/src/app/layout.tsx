import type { Metadata } from "next";
import localFont from "next/font/local";
import { headers } from "next/headers";
import "./globals.css";
import "./theme.css";
import "./interaction.css";
import { ThemeProvider } from "@/components/theme-provider";
const bodyFont = localFont({
  src: "./fonts/dm-sans.woff2",
  weight: "400 700",
  variable: "--font-body",
  display: "swap",
});
const displayFont = localFont({
  src: "./fonts/manrope.woff2",
  weight: "400 800",
  variable: "--font-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Phirmy · Your website. Answering customers.",
  description:
    "Turn your website into an assistant you can try right now. No signup. No setup.",
  icons: {
    icon: "/brand/phirmy-symbol.jpg",
    shortcut: "/brand/phirmy-symbol.jpg",
    apple: "/brand/phirmy-symbol.jpg",
  },
};

export const dynamic = "force-dynamic";

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const nonce = (await headers()).get("x-nonce") || undefined;
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={bodyFont.variable + " " + displayFont.variable}
    >
      <head>
        <script
          nonce={nonce}
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var p=localStorage.getItem('studio.color-theme');var t=p==='light'||p==='dark'?p:matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';document.documentElement.dataset.theme=t;document.documentElement.style.colorScheme=t}catch(e){}})()`,
          }}
        />
      </head>
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
