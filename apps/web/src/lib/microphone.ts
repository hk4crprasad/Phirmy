/** Permission is requested only by a visitor's explicit voice action. */
export function checkMicrophone() {
  if (!navigator.mediaDevices?.getUserMedia)
    throw Error("Microphone access requires HTTPS and a supported browser. You can still type your message.");
  const policy = (document as Document & {
    permissionsPolicy?: { allowsFeature: (name: string) => boolean };
    featurePolicy?: { allowsFeature: (name: string) => boolean };
  });
  if ((policy.permissionsPolicy || policy.featurePolicy)?.allowsFeature("microphone") === false)
    throw Error("This website blocks microphone access. Ask the website owner to allow microphone access for this widget, or use text chat.");
}

export function microphoneError(error: unknown): string {
  const name = (error as Error)?.name;
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Microphone access is blocked. Allow it in your browser’s site settings, then try again. You can still use text chat.";
  if (name === "NotFoundError")
    return "No microphone was found. Connect a microphone, then try again.";
  if (name === "NotReadableError" || name === "AbortError")
    return "Your microphone is unavailable. Check your device permissions and other apps using it, then try again.";
  return (error as Error)?.message || "Microphone access failed. Please try again or use text chat.";
}
