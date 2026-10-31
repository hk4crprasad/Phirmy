import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Check, X } from "lucide-react";

const KEY = "phirmy:privacy-choice:v1";
const LIFETIME = 180 * 24 * 60 * 60 * 1000;
export function openCookieSettings() { window.dispatchEvent(new Event("phirmy:cookie-settings")); }
function hasChoice() {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) || "null");
    return value?.version === 1 && value.necessaryOnly === true && value.expires > Date.now() && value.expires <= Date.now() + LIFETIME;
  } catch { return false; }
}
export default function CookieControls() {
  const [notice, setNotice] = useState(() => !hasChoice());
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const [storageError, setStorageError] = useState("");
  useEffect(() => {
    const open = () => {
      opener.current = document.activeElement as HTMLElement;
      setStorageError("");
      dialog.current?.showModal();
    };
    const sync = () => setNotice(!hasChoice());
    window.addEventListener("phirmy:cookie-settings", open);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener("phirmy:cookie-settings", open); window.removeEventListener("storage", sync); };
  }, []);
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify({ version: 1, necessaryOnly: true, expires: Date.now() + LIFETIME })); }
    catch { setStorageError("Your browser could not save this choice. No optional trackers are enabled; this notice may appear on your next visit."); return; }
    setNotice(false);
    dialog.current?.close();
  }
  return <>
    {notice && <aside className="cookie-notice" aria-labelledby="cookie-notice-title">
      <span className="privacy-dot" aria-hidden="true" />
      <h2 id="cookie-notice-title">A little note on privacy.</h2>
      <p>No analytics or advertising cookies here. We only save your notice preference in this browser. <a href="/legal/cookies">Cookie policy <ArrowUpRight size={12}/></a></p>
      {storageError && <p role="status">{storageError}</p>}
      <div className="cookie-buttons"><button onClick={openCookieSettings}>Manage</button><button className="cookie-primary" onClick={save}>Got it <Check size={14}/></button></div>
    </aside>}
    <dialog ref={dialog} className="cookie-dialog" aria-labelledby="cookie-settings-title" onClose={() => opener.current?.focus()} onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      <div className="cookie-dialog-content">
        <button className="cookie-close" aria-label="Close cookie settings" onClick={() => dialog.current?.close()}><X size={20}/></button>
        <span className="eyebrow">YOUR BROWSER. YOUR CHOICE.</span>
        <h2 id="cookie-settings-title">Privacy, kept simple.</h2>
        <p>This public Phirmy website currently uses only the storage needed to remember this choice. There are no optional trackers to turn on.</p>
        <dl>
          <div><dt>Notice preference <span>Necessary</span></dt><dd>Remembers that you have seen this notice for 180 days. Stored only in this browser.</dd></div>
          <div><dt>Analytics <span>Not used</span></dt><dd>No analytics cookies or visitor measurement scripts are installed.</dd></div>
          <div><dt>Advertising <span>Not used</span></dt><dd>No advertising cookies, retargeting pixels, or cross-site tracking scripts are installed.</dd></div>
        </dl>
        <p>For accounts or embedded widgets, check the notice provided by that service. <a href="/legal/cookies">Read our cookie policy</a>.</p>
        {storageError && <p role="status">{storageError}</p>}
        <div className="cookie-buttons"><button onClick={() => { try { localStorage.removeItem(KEY); setNotice(true); dialog.current?.close(); } catch { setStorageError("Your browser is blocking storage changes."); } }}>Reset saved choice</button><button className="cookie-primary" onClick={save}>Save preferences</button></div>
      </div>
    </dialog>
  </>;
}
