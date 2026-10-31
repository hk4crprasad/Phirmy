/* Shared by the React preview and the standalone widget. No secrets or bypass. */
(() => {
  if (window.StudioBotChallenge) return;
  let loading;
  function load() {
    if (window.turnstile) return Promise.resolve(window.turnstile);
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const timer = setTimeout(() => fail(), 15000);
      function fail() {
        clearTimeout(timer); script.remove(); loading = null;
        reject(Error("Bot verification could not load. Please retry."));
      }
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true; script.defer = true;
      script.onerror = fail;
      script.onload = () => {
        clearTimeout(timer);
        if (!window.turnstile) return fail();
        window.turnstile.ready(() => resolve(window.turnstile));
      };
      document.head.append(script);
    });
    return loading;
  }
  window.StudioBotChallenge = {
    async obtain(container, config, signal) {
      if (!config?.required) return "";
      if (!config.site_key) throw Error("This assistant is awaiting bot-protection configuration.");
      const provider = await load();
      if (signal?.aborted) throw new DOMException("Canceled", "AbortError");
      return new Promise((resolve, reject) => {
        let id, settled = false;
        const timer = setTimeout(() => finish(null, Error("Bot verification expired. Please retry.")), 120000);
        function finish(token, error) {
          if (settled) return;
          settled = true; clearTimeout(timer);
          signal?.removeEventListener("abort", canceled);
          if (id !== undefined) provider.remove(id);
          error ? reject(error) : resolve(token);
        }
        function canceled() { finish(null, new DOMException("Canceled", "AbortError")); }
        signal?.addEventListener("abort", canceled, { once: true });
        id = provider.render(container, {
          sitekey: config.site_key, action: config.action, theme: "auto", size: "flexible",
          callback: (token) => finish(token),
          "error-callback": () => finish(null, Error("Bot verification failed. Please retry.")),
          "expired-callback": () => finish(null, Error("Bot verification expired. Please retry.")),
        });
      });
    },
  };
})();
