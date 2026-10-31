/* Public installer: installation ID only; no dashboard, Fish, OpenAI or carrier keys. */
(() => {
  const script = document.currentScript;
  const installation =
    script?.getAttribute("data-widget-id") ||
    script?.getAttribute("data-installation");
  const publicKey = script?.getAttribute("data-public-key") || "";
  if (document.querySelector("[data-voice-studio-widget]")) return;
  if (!installation) return;
  const base = new URL(script.src).origin + "/backend";
  const appOrigin = new URL(script.src).origin;
  let variables = {};
  try {
    const supplied = JSON.parse(script.getAttribute("data-variables") || "{}");
    if (supplied && typeof supplied === "object" && !Array.isArray(supplied))
      variables = supplied;
  } catch {}
  const host = document.createElement("div");
  host.setAttribute("data-voice-studio-widget", "");
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `
:host{--paper:#faf9f7;--surface:#fff;--ink:#242321;--muted:#77716b;--line:#eae6e1;--soft:#f5f2ee;--primary:#242321;--on-primary:#fff;position:fixed;bottom:22px;right:22px;z-index:2147483000;font:14px system-ui,-apple-system,sans-serif;color:var(--ink);color-scheme:light}
@media(prefers-color-scheme:dark){:host{--paper:#242321;--surface:#2c2a27;--ink:#eeeae5;--muted:#aaa199;--line:#44403b;--soft:#302d29;--primary:#f0ece7;--on-primary:#242321;color-scheme:dark}}
*{box-sizing:border-box}button,input{font:inherit;color:inherit}button{cursor:pointer}.launcher{border:0;background:var(--primary);color:var(--on-primary);padding:15px 20px;border-radius:30px;box-shadow:0 5px 25px #24232120}.panel{display:none;width:min(350px,calc(100vw - 32px));height:min(510px,calc(100dvh - 110px));margin-bottom:12px;background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:0 16px 60px #24232120;overflow:hidden;flex-direction:column}.panel.open{display:flex}.header{padding:18px;background:var(--soft);display:flex;justify-content:space-between;align-items:center}.header strong{font-size:14px}.header button{background:none;border:0;font-size:20px}.log{overflow:auto;flex:1;padding:16px;display:flex;flex-direction:column;gap:12px}.message{font-size:13px;line-height:1.65;background:var(--soft);padding:10px 13px;border-radius:10px;white-space:pre-wrap;overflow-wrap:anywhere;max-width:92%}.user{align-self:flex-end;background:var(--primary);color:var(--on-primary)}.composer{display:flex;gap:8px;border-top:1px solid var(--line);padding:12px}.composer input{width:0;flex:1;border:1px solid var(--line);background:var(--surface);padding:10px;border-radius:8px;min-width:0}.composer button{background:var(--primary);color:var(--on-primary);border:0;border-radius:8px;padding:9px 12px}.footer{padding:8px 12px;font-size:10px;color:var(--muted)}.error{color:#b14c3e;font-size:12px;padding:10px 16px}.product{display:block;color:inherit;text-decoration:underline;font-size:12px;margin-top:8px}button:focus-visible,input:focus-visible{outline:2px solid #00a88e;outline-offset:2px}
`;
  style.textContent += `
.launcher{display:flex;gap:8px;align-items:center;justify-content:center}.launcher svg,.launcher img{width:20px;height:20px;flex:none;object-fit:contain}.launcher img{border-radius:50%}.launcher.circle{width:52px;height:52px;padding:0;border-radius:50%}.launcher.circle .launcher-text{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.composer input{font-size:16px}.header strong{display:flex;align-items:center;gap:8px;min-width:0}.header img{flex:none}.user{background:var(--user-color,var(--primary));color:var(--user-text,var(--on-primary))}
`;
  shadow.appendChild(style);
  const panel = document.createElement("section");
  panel.className = "panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Business support chat");
  const header = document.createElement("div");
  header.className = "header";
  const title = document.createElement("strong");
  title.textContent = "How can we help?";
  const close = document.createElement("button");
  close.type = "button";
  close.setAttribute("aria-label", "Close chat");
  close.textContent = "×";
  header.append(title, close);
  const log = document.createElement("div");
  log.className = "log";
  log.setAttribute("aria-live", "polite");
  new ResizeObserver(() => {
    log.scrollTop = log.scrollHeight;
  }).observe(log);
  const error = document.createElement("div");
  error.className = "error";
  error.setAttribute("role", "alert");
  const composer = document.createElement("form");
  composer.className = "composer";
  const input = document.createElement("input");
  input.placeholder = "Ask a question…";
  input.required = true;
  input.maxLength = 8000;
  input.setAttribute("aria-label", "Chat message");
  const send = document.createElement("button");
  send.type = "submit";
  send.textContent = "Send";
  const mic = document.createElement("button");
  mic.type = "button";
  mic.className = "mic";
  mic.title = "Voice input";
  mic.setAttribute("aria-label", "Start voice input");
  const microphoneIcon =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>';
  mic.innerHTML = microphoneIcon;
  mic.hidden = true;
  composer.append(input, mic, send);
  const liveStatus = document.createElement("div");
  liveStatus.className = "live-status";
  liveStatus.setAttribute("role", "status");
  liveStatus.style.cssText =
    "padding:8px 16px;font-size:12px;border-bottom:1px solid var(--line)";

  const footer = document.createElement("div");
  footer.className = "footer";
  footer.textContent = "Phirmy · AI assistant";
  panel.append(header, liveStatus, log, error, composer, footer);
  const voiceButton = document.createElement("button");
  voiceButton.type = "button";
  voiceButton.textContent = "Talk to this agent";
  voiceButton.className = "voice-button";
  voiceButton.style.cssText =
    "display:none;margin:0 12px 10px;padding:10px;border:1px solid var(--line);border-radius:9px;background:var(--soft);color:var(--ink);font:inherit";
  panel.insertBefore(voiceButton, footer);
  const launcher = document.createElement("button");
  launcher.type = "button";
  launcher.className = "launcher";
  launcher.textContent = "Let’s talk";
  launcher.setAttribute("aria-expanded", "false");
  const designRoot = document.createElement("div");
  designRoot.className = "wd-root";
  designRoot.style.display = "flex";
  designRoot.style.flexDirection = "column";
  designRoot.append(panel, launcher);
  shadow.append(designRoot);
  panel.classList.add("wd-panel");
  header.classList.add("wd-header");
  log.classList.add("wd-log");
  composer.classList.add("wd-composer");
  footer.classList.add("wd-footer");
  launcher.classList.add("wd-launcher");
  const designSheet = document.createElement("link");
  designSheet.rel = "stylesheet";
  designSheet.href = appOrigin + "/widget-designs.css";
  shadow.append(designSheet);
  const storageKey = "cynerza-widget:" + appOrigin + ":" + installation;
  function readStored() {
    try {
      return JSON.parse(sessionStorage.getItem(storageKey) || "null");
    } catch {
      return null;
    }
  }
  function saveStored(value) {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(value));
    } catch {}
  }
  const executed = new Set(readStored()?.actions || []);
  function applyActions(actions) {
    for (const action of actions || []) {
      if (!action || typeof action.id !== "string" || executed.has(action.id))
        continue;
      try {
        const url = new URL(action.url);
        if (
          url.origin !== location.origin ||
          url.username ||
          url.password ||
          !["http:", "https:"].includes(url.protocol)
        )
          continue;
        if (
          action.type === "scroll" &&
          typeof action.section_id === "string" &&
          /^[A-Za-z][\w:.-]{0,99}$/.test(action.section_id)
        ) {
          if (url.pathname !== location.pathname) continue;
          document.getElementById(action.section_id)?.scrollIntoView({
            behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
              ? "auto"
              : "smooth",
          });
        } else if (action.type !== "navigate") continue;
        executed.add(action.id);
        saveStored({
          ...readStored(),
          actions: [...executed].slice(-100),
          open: true,
        });
        if (action.type === "navigate") location.assign(url.href);
      } catch {}
    }
  }
  function productCards(parent, products) {
    const list = document.createElement("div");
    list.className = "wd-products";
    for (const product of (products || []).slice(0, 6)) {
      try {
        const url = new URL(product.canonical_url);
        if (
          !["http:", "https:"].includes(url.protocol) ||
          url.username ||
          url.password
        )
          continue;
        const card = document.createElement("a");
        card.className = "product";
        card.href = url.href;
        if (url.origin !== location.origin) {
          card.target = "_blank";
          card.rel = "noopener noreferrer";
        }

        if (
          product.image_url &&
          new URL(product.image_url).protocol === "https:"
        ) {
          const img = document.createElement("img");
          img.src = product.image_url;
          img.alt = product.title;
          img.loading = "lazy";
          img.referrerPolicy = "no-referrer";
          // Source sites or browser policy may block remote images. Keep the
          // grounded product text/link usable instead of showing a broken image.
          img.addEventListener("error", () => img.remove(), { once: true });
          img.style.cssText =
            "width:100%;height:110px;object-fit:contain;border-radius:6px";
          card.append(img);
        }
        const name = document.createElement("strong");
        name.textContent = product.title;
        card.append(name);
        const price = document.createElement("span");
        price.textContent =
          product.currency +
          " " +
          (product.price_minor / 100).toLocaleString() +
          " · " +
          String(product.availability || "unknown").replaceAll("_", " ");
        card.append(price);
        const detail = document.createElement("span");
        detail.textContent = String(product.description || "").slice(0, 160);
        card.append(detail);
        list.append(card);
      } catch {}
    }
    if (list.childNodes.length) parent.append(list);
  }
  let session = null,
    busy = false;
  let voiceFrame = null;
  function closeVoice() {
    if (voiceFrame) {
      voiceFrame.remove();
      voiceFrame = null;
    }
    log.style.display = "";
    composer.style.display = "";
    voiceButton.style.display = session?.theme?.voice_enabled
      ? "block"
      : "none";
  }
  voiceButton.onclick = () => {
    if (!session?.voice_available || voiceFrame) return;
    stopRecording(true);
    voiceFrame = document.createElement("iframe");
    voiceFrame.title = "Voice assistant";
    voiceFrame.allow = "microphone";
    voiceFrame.referrerPolicy = "no-referrer";
    voiceFrame.src =
      appOrigin + "/widget/" + encodeURIComponent(installation) + "?mode=voice";
    voiceFrame.style.cssText =
      "border:0;width:100%;min-height:350px;flex:1;background:var(--paper)";
    log.style.display = "none";
    composer.style.display = "none";
    voiceButton.style.display = "none";
    panel.insertBefore(voiceFrame, footer);
  };
  window.addEventListener("message", (event) => {
    if (
      event.origin !== appOrigin ||
      !voiceFrame ||
      event.source !== voiceFrame.contentWindow
    )
      return;
    if (event.data?.type === "voice-studio:ready")
      voiceFrame.contentWindow.postMessage(
        {
          type: "voice-studio:authorize",
          token: session.session_token,
          page_url: location.origin + location.pathname,
        },
        appOrigin,
      );
    if (event.data?.type === "voice-studio:close") {
      closeVoice();
      connect();
    }
    if (event.data?.type === "voice-studio:website") {
      applyActions(event.data.actions);
      if (event.data.products)
        productCards(
          message("Here are the matching products."),
          event.data.products,
        );
    }
  });
  function message(text, role = "assistant") {
    const element = document.createElement("div");
    element.className =
      "message wd-message " + (role === "user" ? "user wd-user" : "");
    element.textContent = text;
    log.appendChild(element);
    log.scrollTop = log.scrollHeight;
    return element;
  }
  function contrast(hex) {
    const n = parseInt(hex.slice(1), 16),
      r = n >> 16,
      g = (n >> 8) & 255,
      b = n & 255;
    const linear = (x) => {
      x /= 255;
      return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b) > 0.179
      ? "#242321"
      : "#ffffff";
  }
  function safeColor(value, fallback) {
    return /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
  }
  function bounded(value, fallback, low, high) {
    return Number.isInteger(value) && value >= low && value <= high
      ? value
      : fallback;
  }
  function chatIcon(kind) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    for (const [key, value] of Object.entries({
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "1.7",
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
    }))
      svg.setAttribute(key, value);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute(
      "d",
      kind === "sparkle"
        ? "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3z"
        : "M21 11.5a8.5 8.5 0 01-8.5 8.5H5l-4 3v-7.5A8.5 8.5 0 111 11.5",
    );
    svg.append(path);
    return svg;
  }
  function logoSource(theme) {
    if (
      typeof theme.logo_path === "string" &&
      theme.logo_path.startsWith("/v1/public/installations/")
    )
      return base + theme.logo_path;
    try {
      const url = new URL(theme.logo_url);
      if (url.protocol === "https:" && !url.username && !url.password)
        return url.href;
    } catch {}
    return "";
  }
  let activeTheme = {};
  function applyTheme(theme) {
    activeTheme = theme;
    const dark =
      theme.color_mode === "dark" ||
      (theme.color_mode !== "light" &&
        matchMedia("(prefers-color-scheme: dark)").matches);
    const automaticDark = theme.color_mode === "auto" && dark;
    const surface = automaticDark
      ? "#272624"
      : safeColor(theme.background_color, dark ? "#272624" : "#ffffff");
    const ink = automaticDark
      ? "#f4f1ec"
      : safeColor(theme.text_color, contrast(surface));
    const primary = safeColor(theme.accent_color, dark ? "#eeeae5" : "#242321");
    const onPrimary = safeColor(theme.button_text_color, contrast(primary));
    const values = {
      "--surface": surface,
      "--paper": surface,
      "--ink": ink,
      "--primary": primary,
      "--on-primary": onPrimary,
      "--soft": dark ? "#ffffff0a" : "#00000006",
      "--line": automaticDark
        ? "#48443f"
        : safeColor(theme.border_color, dark ? "#48443f" : "#e7e3de"),
      "--muted": ink,
      "--user-color": safeColor(theme.user_message_color, primary),
      "--user-text": safeColor(theme.user_text_color, onPrimary),
    };
    for (const [key, value] of Object.entries(values))
      host.style.setProperty(key, value);
    host.style.colorScheme = dark ? "dark" : "light";
    host.style.fontFamily =
      {
        system: "system-ui,-apple-system,sans-serif",
        serif: "Georgia,serif",
        rounded: "ui-rounded,system-ui,sans-serif",
      }[theme.font_family] || "system-ui,-apple-system,sans-serif";
    const x = bounded(theme.offset_x, 22, 8, 64),
      y = bounded(theme.offset_y, 22, 8, 64);
    host.style.bottom = y + "px";
    host.style.left = theme.position === "left" ? x + "px" : "auto";
    host.style.right = theme.position === "left" ? "auto" : x + "px";
    designRoot.style.alignItems =
      theme.position === "left" ? "flex-start" : "flex-end";
    const preset = theme.preset || "minimal";
    designRoot.dataset.widgetDesign = preset;
    const width = bounded(
      theme.widget_width,
      preset === "compact" ? 300 : preset === "panel" ? 390 : 350,
      280,
      480,
    );
    const height = bounded(
      theme.widget_height,
      preset === "compact" ? 390 : 510,
      360,
      720,
    );
    panel.style.width = "min(" + width + "px, calc(100vw - " + x * 2 + "px))";
    panel.style.height =
      "min(" + height + "px, calc(100dvh - " + (y * 2 + 70) + "px))";
    panel.style.borderRadius =
      bounded(theme.corner_radius, preset === "bubble" ? 25 : 16, 0, 28) + "px";
    header.style.background = preset === "classic" ? primary : "";
    header.style.color = preset === "classic" ? onPrimary : "";
    close.style.color = "inherit";
    title.textContent = theme.assistant_name || "How can we help?";
    const logoUrl = logoSource(theme);
    if (logoUrl) {
      const logo = document.createElement("img");
      logo.src = logoUrl;
      logo.alt = "";
      logo.referrerPolicy = "no-referrer";
      logo.style.cssText = "width:30px;height:30px;object-fit:contain";
      logo.addEventListener("error", () => logo.remove(), { once: true });
      title.prepend(logo);
    }
    const label = String(theme.launcher_label || "Let’s talk");
    launcher.replaceChildren();
    launcher.setAttribute("aria-label", label);
    launcher.classList.toggle("circle", theme.launcher_shape === "circle");
    launcher.style.borderRadius =
      theme.launcher_shape === "rounded" ? "10px" : "50px";
    const kind = theme.launcher_icon || "none";
    if (kind === "logo" && logoUrl) {
      const image = document.createElement("img");
      image.src = logoUrl;
      image.alt = "";
      image.addEventListener(
        "error",
        () => image.replaceWith(chatIcon("chat")),
        { once: true },
      );
      launcher.append(image);
    } else if (kind !== "none" || theme.launcher_shape === "circle")
      launcher.append(chatIcon(kind));
    const text = document.createElement("span");
    text.className = "launcher-text";
    text.textContent = label;
    launcher.append(text);
    input.placeholder = theme.input_placeholder || "Ask a question…";
    send.textContent = theme.send_button_label || "Send";
    footer.textContent = theme.status_text || "Phirmy · AI assistant";
  }
  const deviceTheme = matchMedia("(prefers-color-scheme: dark)");
  deviceTheme.addEventListener("change", () => {
    if (!activeTheme.color_mode || activeTheme.color_mode === "auto")
      applyTheme(activeTheme);
  });
  let connecting = false;
  let visitor = null,
    chatController = null,
    recorder = null,
    microphone = null,
    recordTimer = null,
    recordingEpoch = 0,
    requestingMicrophone = false,
    transcribing = false;
  let conversationState = "open",
    historySignature = "",
    syncing = false;
  function stopRecording(discard = false) {
    if (discard) {
      recordingEpoch++;
      requestingMicrophone = false;
      transcribing = false;
      mic.disabled = false;
      mic.setAttribute("aria-label", "Start voice input");
      mic.setAttribute("aria-pressed", "false");
      mic.innerHTML = microphoneIcon;
      liveStatus.textContent = "";
    }
    if (recorder?.state === "recording") {
      recorder.discard = discard;
      recorder.stop();
    }
    microphone?.getTracks().forEach((track) => track.stop());
    microphone = null;
    clearTimeout(recordTimer);
  }
  mic.onclick = async () => {
    if (recorder?.state === "recording") {
      stopRecording();
      return;
    }
    if (!session || busy || conversationState === "resolved" || requestingMicrophone || transcribing) return;
    const epoch = ++recordingEpoch;
    requestingMicrophone = true;
    mic.disabled = true;
    error.textContent = "";
    liveStatus.textContent = "Allow microphone access in your browser to begin.";
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
        throw Error("Microphone input requires HTTPS and a supported browser.");
      const policy = document.permissionsPolicy || document.featurePolicy;
      if (policy?.allowsFeature("microphone") === false)
        throw Error("This website blocks microphone access. Ask the website owner to allow it, or type your message.");
      const captured = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (epoch !== recordingEpoch) {
        captured.getTracks().forEach((track) => track.stop());
        return;
      }
      microphone = captured;
      const mime = [
        "audio/webm;codecs=opus",
        "audio/mp4",
        "audio/ogg;codecs=opus",
      ].find((type) => MediaRecorder.isTypeSupported(type));
      if (!mime)
        throw Error(
          "Voice recording is unavailable in this browser. Please type your message.",
        );
      recorder = new MediaRecorder(microphone, { mimeType: mime });
      const chunks = [],
        active = recorder;
      active.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      active.onstop = async () => {
        if (epoch !== recordingEpoch || active.discard) return;
        mic.setAttribute("aria-label", "Start voice input");
        mic.innerHTML = microphoneIcon;
        mic.setAttribute("aria-pressed", "false");
        transcribing = true;
        mic.disabled = true;
        liveStatus.textContent = "Transcribing…";
        try {
          const response = await fetch(base + "/v1/public/voice/transcribe", {
            method: "POST",
            credentials: "omit",
            headers: {
              Authorization: "Bearer " + session.session_token,
              "Content-Type": mime,
            },
            body: new Blob(chunks, { type: mime }),
            signal: AbortSignal.timeout(45000),
          });
          const result = await response.json();
          if (epoch !== recordingEpoch) return;
          if (!response.ok)
            throw Error(
              typeof result.detail === "string"
                ? result.detail
                : "Transcription failed",
            );
          if (!result.text)
            throw Error("No speech detected. Try again or type your message.");
          input.value = (input.value + " " + result.text).trim().slice(0, 8000);
          input.focus();
          liveStatus.textContent = "Review your voice message, then send.";
        } catch (e) {
          if (epoch === recordingEpoch) error.textContent = e.message;
        } finally {
          if (epoch === recordingEpoch) {
            transcribing = false;
            mic.disabled = false;
          }
        }
      };
      active.onerror = () => {
        if (epoch !== recordingEpoch) return;
        stopRecording(true);
        error.textContent = "Recording stopped unexpectedly. Check your microphone and try again.";
      };
      active.start();
      mic.setAttribute("aria-label", "Stop voice input");
      mic.setAttribute("aria-pressed", "true");
      mic.textContent = "■";
      liveStatus.textContent =
        "Listening… tap stop when finished (up to 30 seconds).";
      recordTimer = setTimeout(() => stopRecording(), 30000);
    } catch (e) {
      if (epoch !== recordingEpoch) return;
      stopRecording(true);
      error.textContent = ["NotAllowedError", "SecurityError"].includes(e.name)
        ? "Microphone access is blocked. Allow it in your browser’s site settings, then try again. You can still type your message."
        : e.name === "NotFoundError"
          ? "No microphone was found. Connect a microphone, then try again."
          : ["NotReadableError", "AbortError"].includes(e.name)
            ? "Your microphone is unavailable. Check your device permissions and other apps using it, then try again."
            : e.message;
    } finally {
      if (epoch === recordingEpoch) {
        requestingMicrophone = false;
        mic.disabled = false;
      }
    }
  };
  function renderHistory(items) {
    log.replaceChildren();
    if (!items.length) message(session.greeting);
    for (const item of items) {
      if (item.metadata_data?.interrupted && !item.text_content) continue;
      const bubble = message(
        item.role === "operator"
          ? "Support team · " + item.text_content
          : item.text_content,
        item.role,
      );
      if (item.role === "operator") bubble.dataset.operator = "true";
      if (item.metadata_data?.interrupted) {
        const note = document.createElement("small");
        note.textContent = " · AI paused";
        bubble.append(note);
      }
      productCards(bubble, item.metadata_data?.products);
    }
    requestAnimationFrame(() => {
      log.scrollTop = log.scrollHeight;
    });
  }
  async function syncConversation() {
    if (
      !session ||
      syncing ||
      document.hidden ||
      !panel.classList.contains("open")
    )
      return;
    syncing = true;
    try {
      const response = await fetch(base + "/v1/public/conversation", {
        method: "POST",
        credentials: "omit",
        headers: { Authorization: "Bearer " + session.session_token },
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) {
        if ([401, 403, 404].includes(response.status)) {
          session = null;
          chatController?.abort();
          stopRecording(true);
          closeVoice();
          input.disabled = true;
          send.disabled = true;
          mic.hidden = true;
          liveStatus.textContent =
            "Chat session is unavailable. Reconnect to continue.";
          error.replaceChildren();
          const reconnect = document.createElement("button");
          reconnect.type = "button";
          reconnect.textContent = "Reconnect";
          reconnect.onclick = connect;
          error.append(reconnect);
          configurationPromise = null;
        }
        return;
      }
      const result = await response.json();
      conversationState = result.state;
      if (conversationState === "resolved" && (requestingMicrophone || transcribing || recorder?.state === "recording"))
        stopRecording(true);
      mic.disabled = conversationState === "resolved" || requestingMicrophone || transcribing;
      if (conversationState !== "open" && busy) chatController?.abort();
      if (!busy) {
        const signature = JSON.stringify(result.items);
        if (signature !== historySignature) {
          renderHistory(result.items);
          historySignature = signature;
        }
      }
      if (recorder?.state !== "recording" && !mic.disabled)
        liveStatus.textContent =
          conversationState === "human"
            ? "Support team connected · AI paused"
            : conversationState === "resolved"
              ? "Conversation closed"
              : "AI assistant · your team can join this chat";
      input.disabled = conversationState === "resolved";
      send.disabled = busy || conversationState === "resolved";
      voiceButton.disabled =
        conversationState !== "open" || !session.voice_available;
    } catch (e) {
      if (!busy) liveStatus.textContent = "Reconnecting to the conversation…";
    } finally {
      syncing = false;
    }
  }
  setInterval(syncConversation, 2000);
  window.addEventListener("pagehide", () => stopRecording(true));
  let configurationPromise = null;
  function loadConfiguration() {
    if (!configurationPromise)
      configurationPromise = (async () => {
        const response = await fetch(
          base +
            "/v1/public/installations/" +
            encodeURIComponent(installation) +
            "?public_key=" +
            encodeURIComponent(publicKey),
          { method: "POST", credentials: "omit" },
        );
        const config = await response.json();
        if (!response.ok) {
          if ([403, 404, 409].includes(response.status))
            host.style.display = "none";
          throw Error(
            typeof config.detail === "string"
              ? config.detail
              : "This assistant is unavailable",
          );
        }
        applyTheme(config.theme || {});
        return config;
      })().catch((error) => {
        configurationPromise = null;
        throw error;
      });
    return configurationPromise;
  }
  async function challengeToken(configuration) {
    if (!configuration.challenge?.required) return "";
    if (!window.StudioBotChallenge)
      await new Promise((resolve, reject) => {
        const helper = document.createElement("script");
        const timer = setTimeout(() => reject(Error("Bot verification is unavailable")), 10000);
        helper.src = appOrigin + "/bot-challenge.js";
        helper.onload = () => { clearTimeout(timer); resolve(); };
        helper.onerror = () => { clearTimeout(timer); reject(Error("Bot verification is unavailable")); };
        document.head.append(helper);
      });
    const container = document.createElement("div");
    log.append(container);
    try { return await window.StudioBotChallenge.obtain(container, configuration.challenge); }
    finally { container.remove(); }
  }
  function emailVerification(current, initialEmail) {
    panel.querySelector(".email-verification")?.remove();
    const details = document.createElement("details"), summary = document.createElement("summary");
    details.className = "email-verification";
    details.style.cssText = "padding:10px 16px;font-size:12px;max-height:240px;overflow:auto";
    summary.textContent = "Verify email for follow-up";
    const form = document.createElement("form"), email = document.createElement("input"), code = document.createElement("input");
    form.style.cssText = "display:grid;gap:8px;padding:8px 0";
    email.type = "email"; email.required = true; email.maxLength = 254; email.value = initialEmail;
    email.setAttribute("aria-label", "Email for verification"); email.placeholder = "Your email";
    code.inputMode = "numeric"; code.autocomplete = "one-time-code"; code.pattern = "[0-9]{6}"; code.maxLength = 6;
    code.setAttribute("aria-label", "Email verification code"); code.placeholder = "Six-digit verification code"; code.hidden = true;
    const consent = document.createElement("label"), opt = document.createElement("input");
    opt.type = "checkbox"; consent.append(opt); consent.hidden = true;
    const button = document.createElement("button"), change = document.createElement("button"), note = document.createElement("p");
    button.type = "submit"; button.textContent = "Send verification code";
    change.type = "button"; change.textContent = "Change email or resend"; change.hidden = true;
    note.setAttribute("role", "status"); note.textContent = "Enter your code only here, never in chat.";
    form.append(email, code, consent, button, change, note); details.append(summary, form); panel.insertBefore(details, composer);
    let challenge = null;
    change.onclick = () => { challenge = null; email.disabled = false; code.hidden = true; code.required = false;
      opt.checked = false; consent.hidden = true; change.hidden = true; button.textContent = "Send verification code"; };
    form.onsubmit = async (event) => {
      event.preventDefault(); button.disabled = change.disabled = true;
      try {
        const response = await fetch(base + "/v1/public/email/" + (challenge ? "verify" : "request"), {
          method: "POST", credentials: "omit", headers: { "Content-Type": "application/json", Authorization: "Bearer " + current.session_token },
          body: JSON.stringify(challenge ? { challenge_id: challenge.challenge_id, code: code.value, marketing_opt_in: opt.checked } : { email: email.value }),
          signal: AbortSignal.timeout(10000),
        });
        const result = await response.json();
        if (!response.ok) throw Error(typeof result.detail === "string" ? result.detail : "Email verification failed");
        if (challenge) { summary.textContent = "Email verified"; form.replaceChildren(); details.open = false; }
        else {
          challenge = result; email.disabled = true; code.hidden = false; code.required = true; change.hidden = false;
          consent.hidden = !result.consent_enabled; consent.append(document.createTextNode(result.consent_text));
          button.textContent = "Verify email"; note.textContent = "Check your email. Enter your code only here.";
        }
      } catch (failure) { note.textContent = failure.message; }
      finally { button.disabled = change.disabled = false; }
    };
  }
  async function connect() {
    if (connecting) return;
    connecting = true;
    error.textContent = "";
    send.disabled = true;
    try {
      const configuration = await loadConfiguration();
      const definitions = configuration.variables || [];
      const missing = definitions.filter(
        (item) =>
          item.required &&
          !String(variables[item.name] ?? item.default ?? "").trim(),
      );
      if (missing.length) {
        log.replaceChildren();
        message("A little context first.");
        const contextForm = document.createElement("form");
        contextForm.style.cssText = "display:grid;gap:12px";
        for (const item of missing) {
          const label = document.createElement("label"),
            field = document.createElement("input");
          label.textContent =
            item.description || item.name.replaceAll("_", " ");
          label.style.cssText = "display:grid;gap:5px;font-size:12px";
          field.name = item.name;
          field.required = true;
          field.maxLength = 2000;
          field.style.cssText =
            "padding:10px;border:1px solid #dce4d1;border-radius:8px;width:100%";
          label.appendChild(field);
          contextForm.appendChild(label);
        }
        const proceed = document.createElement("button");
        proceed.textContent = "Start conversation";
        proceed.type = "submit";
        proceed.className = "launcher";
        contextForm.appendChild(proceed);
        contextForm.onsubmit = (event) => {
          event.preventDefault();
          for (const [key, value] of new FormData(contextForm))
            variables[key] = String(value);
          connect();
        };
        log.appendChild(contextForm);
        return;
      }
      const stored = readStored();
      let response;
      if (stored?.resume_token)
        response = await fetch(base + "/v1/public/sessions/resume", {
          method: "POST",
          credentials: "omit",
          headers: { Authorization: "Bearer " + stored.resume_token },
        });
      if (
        !response?.ok &&
        configuration.theme?.collect_email === true &&
        !visitor
      ) {
        log.replaceChildren();
        message("Let’s get started");
        const form = document.createElement("form");
        form.className = "lead-form";
        form.style.cssText = "display:grid;gap:14px;padding:6px;font-size:13px";
        const description = document.createElement("p");
        description.textContent =
          "Enter your email to start the conversation and let our team follow up.";
        const emailLabel = document.createElement("label");
        emailLabel.textContent = "Email address";
        const email = document.createElement("input");
        email.type = "email";
        email.required = true;
        email.maxLength = 254;
        email.autocomplete = "email";
        email.setAttribute("aria-label", "Email address");
        email.style.cssText =
          "padding:13px;width:100%;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink);font:inherit;margin-top:8px";
        emailLabel.append(email);
        const next = document.createElement("button");
        next.type = "submit";
        next.className = "launcher wd-launcher";
        next.textContent = "Continue";
        form.append(description, emailLabel, next);
        log.append(form);
        liveStatus.textContent = "Your conversation starts here";
        input.disabled = true;
        composer.style.display = "none";
        mic.hidden = true;
        form.onsubmit = (event) => {
          event.preventDefault();
          visitor = {
            visitor_email: email.value.trim(),
          };
          connect();
        };
        email.focus();
        return;
      }
      if (!response?.ok) {
        const bot_token = await challengeToken(configuration);
        response = await fetch(base + "/v1/public/sessions", {
          method: "POST",
          credentials: "omit",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            installation_public_id: installation,
            public_key: publicKey,
            variables,
            bot_token: bot_token || undefined,
            ...(visitor || {}),
          }),
        });
      }
      const result = await response.json();
      if (!response.ok)
        throw Error(
          typeof result.detail === "string"
            ? result.detail
            : "Chat is unavailable for this website",
        );
      session = result;
      const visitorEmail = visitor?.visitor_email || "";
      visitor = null;
      composer.style.display = "flex";
      input.disabled = false;
      mic.hidden = !result.voice_input_available;
      conversationState = result.state || "open";
      saveStored({
        ...stored,
        resume_token: result.resume_token,
        actions: [...executed],
      });
      voiceButton.style.display = result.theme?.voice_enabled
        ? "block"
        : "none";
      voiceButton.disabled = !result.voice_available;
      voiceButton.textContent = result.voice_available
        ? "Talk to this agent"
        : "Voice is temporarily unavailable";
      log.replaceChildren();
      if (result.history?.length)
        for (const item of result.history) {
          const bubble = message(
            item.role === "operator"
              ? "Support team · " + item.text
              : item.text,
            item.role,
          );
          productCards(bubble, item.products);
        }
      else message(result.greeting);
      emailVerification(result, visitorEmail);
      const theme = result.theme || configuration.theme || {};
      applyTheme(theme);
      syncConversation();
      if (result.mode !== "live-llm")
        footer.textContent =
          (theme.status_text ? theme.status_text + " · " : "Phirmy · ") +
          "Development response mode";
    } catch (e) {
      error.textContent = e.message;
    } finally {
      connecting = false;
      send.disabled = !session;
    }
  }
  launcher.onclick = () => {
    const opened = panel.classList.toggle("open");
    launcher.setAttribute("aria-expanded", String(opened));
    saveStored({ ...readStored(), open: opened });
    if (opened) {
      if (!session) connect();
      input.focus();
    } else {
      closeVoice();
      stopRecording(true);
    }
  };
  close.onclick = () => {
    closeVoice();
    stopRecording(true);
    panel.classList.remove("open");
    launcher.setAttribute("aria-expanded", "false");
    saveStored({ ...readStored(), open: false });
    launcher.focus();
  };
  composer.onsubmit = async (event) => {
    event.preventDefault();
    if (
      !session ||
      busy ||
      conversationState === "resolved" ||
      !input.value.trim()
    )
      return;
    stopRecording(true);
    const text = input.value.trim();
    input.value = "";
    message(text, "user");
    const answer =
      conversationState === "human"
        ? document.createElement("div")
        : message("Thinking…");
    busy = true;
    send.disabled = true;
    error.textContent = "";
    try {
      chatController = new AbortController();
      const response = await fetch(base + "/v1/public/chat", {
        signal: chatController.signal,
        method: "POST",
        credentials: "omit",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + session.session_token,
        },
        body: JSON.stringify({
          session_id: session.id,
          message: text,
          client_message_id: crypto.randomUUID(),
          page_url: location.origin + location.pathname,
        }),
      });
      if (!response.ok) {
        const result = await response.json();
        if (response.status === 401) session = null;
        throw Error(
          typeof result.detail === "string"
            ? result.detail
            : "Chat request failed",
        );
      }
      const reader = response.body.getReader(),
        decoder = new TextDecoder();
      let buffer = "",
        spoken = "",
        products = [],
        actions = [];
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
          if (kind === "chat.text.delta") {
            spoken += data.text;
            answer.textContent = spoken;
          }
          if (kind === "chat.products") products = data.products;
          if (kind === "chat.actions") actions.push(...data.actions);
          if (kind === "chat.completed") {
            spoken = data.text;
            answer.textContent = spoken;
            products = data.products || products;
            actions = data.actions || actions;
          }
          if (kind === "chat.human_queued" || kind === "chat.interrupted") {
            answer.remove();
            conversationState = "human";
          }
          if (kind === "chat.failed") throw Error(data.message);
          log.scrollTop = log.scrollHeight;
        }
      }
      productCards(answer, products);
      log.scrollTop = log.scrollHeight;
      applyActions(actions);
    } catch (e) {
      if (e.name !== "AbortError") error.textContent = e.message;
      if (e.name === "AbortError" || answer.textContent === "Thinking…")
        answer.remove();
    } finally {
      busy = false;
      syncConversation();
      send.disabled = !session || conversationState === "resolved";
      if (!session) {
        const retry = document.createElement("button");
        retry.type = "button";
        retry.textContent = "Reconnect";
        retry.onclick = connect;
        error.appendChild(retry);
      }
    }
  };
  loadConfiguration().catch(() => {});
  if (readStored()?.open) {
    panel.classList.add("open");
    launcher.setAttribute("aria-expanded", "true");
    connect();
  }
})();
