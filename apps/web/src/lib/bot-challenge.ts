import { Row } from "./api";

let loading: Promise<void> | undefined;
export async function botToken(root: HTMLElement, config: Row, signal?: AbortSignal) {
  if (!config?.required) return "";
  if (!(window as any).StudioBotChallenge) {
    loading ??= new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      const timer=setTimeout(()=>{script.remove();loading=undefined;reject(Error("Bot verification is unavailable"));},10000);
      script.src = "/bot-challenge.js";
      script.onload = () => {clearTimeout(timer);resolve();};
      script.onerror = () => {clearTimeout(timer);loading = undefined; reject(Error("Bot verification is unavailable")); };
      document.head.append(script);
    });
    await loading;
  }
  return (window as any).StudioBotChallenge.obtain(root, config, signal) as Promise<string>;
}
