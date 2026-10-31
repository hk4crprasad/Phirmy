import { csrf, authenticatedFetch } from "./api";

export async function generation(
  path: string,
  body: unknown,
  onStage?: (stage: string) => void,
): Promise<string> {
  const response = await authenticatedFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json();
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Generation request failed",
    );
  }
  const reader = response.body!.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    result = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const packet = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const kind = packet
        .split("\n")
        .find((x) => x.startsWith("event: "))
        ?.slice(7);
      const raw = packet
        .split("\n")
        .find((x) => x.startsWith("data: "))
        ?.slice(6);
      if (!raw) continue;
      const data = JSON.parse(raw);
      if (kind === "generation.stage") onStage?.(data.stage);
      if (kind === "generation.completed") result = data.instructions;
      if (kind === "generation.failed") throw Error(data.message);
    }
  }
  if (!result) throw Error("Generation ended without a complete draft");
  return result;
}
