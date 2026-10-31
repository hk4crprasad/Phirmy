import { useEffect } from "react";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { openCookieSettings } from "./components/CookieControls";

export default function LegalPage({ document }: { document: string }) {
  const title = document === "cookies" ? "Cookie policy" : document === "privacy" ? "Privacy notice" : "Website terms";
  useEffect(() => { window.document.title = `${title} — Phirmy`; }, [title]);
  return <div className="legal-site">
    <header className="legal-header"><a href="/" aria-label="Phirmy home"><img src="/brand/phirmy-light.jpg" alt="Phirmy"/></a><a href="/contact">Contact us <ArrowUpRight size={15}/></a></header>
    <main className="legal-content" id="main">
      <a className="legal-back" href="/"><ArrowLeft size={15}/> Back to Phirmy</a>
      <span className="eyebrow">PHIRMY · LAST UPDATED 29 OCTOBER 2026</span>
      <h1>{title}</h1>
      <p className="legal-lead">{document === "cookies" ? "A clear account of what this website stores in your browser." : document === "privacy" ? "What happens to the information you share with us." : "A few things to know when exploring Phirmy."}</p>
      {document === "cookies" ? <>
        <h2>What this policy covers</h2><p>This policy covers the public Phirmy website, its product walkthroughs, and its contact page. Authenticated workspaces and widgets installed on other websites can use separate session and security storage; consult the notice provided with those services.</p>
        <h2>Our current use</h2><p>This website does not set analytics or advertising cookies. Its fonts, product walkthrough media, and interface assets are served from the website itself. Browsing the walkthrough does not start a real AI call or request microphone access.</p>
        <h2>The preference we save</h2><p>When you select “Got it” or “Save preferences,” we store a small record named <code>phirmy:privacy-choice:v1</code> in local storage. It records the notice version, that only necessary storage is used, and an expiry time. It contains no name, email address, or unique visitor identifier and is not sent to our server.</p><p>The saved choice is valid for 180 days. After that, the notice appears again on your next visit. Local storage may remain in your browser until replaced or cleared; our website ignores expired choices.</p>
        <h2>Manage or reset your choice</h2><p>You can reopen the controls at any time, reset the saved choice, or clear site data in your browser. If browser storage is blocked, the notice may appear again. The rest of the public website remains usable.</p><button className="button dark-button" onClick={openCookieSettings}>Cookie settings</button>
        <h2>If our use changes</h2><p>If optional trackers are introduced, we will update this policy and provide controls before enabling them where consent is required. Acknowledging today’s notice does not grant permission for future analytics or advertising.</p>
      </> : document === "privacy" ? <>
        <h2>Information you choose to share</h2><p>Our contact form asks for your name, email address, company if you choose to provide it, product interest, and message. We use this information to respond to your enquiry and discuss the service you requested. Submitting an enquiry does not subscribe you to marketing emails.</p>
        <h2>How enquiries are handled</h2><p>Enquiries are stored in an encrypted delivery queue and sent to the Phirmy support mailbox through our email provider, Hostinger. Delivery status and an enquiry reference help us handle retries and support requests. Avoid including passwords, payment details, or other sensitive information in your message.</p>
        <h2>Technical information</h2><p>Our hosting and security systems process request information, such as IP addresses and request times, to serve the website, prevent abuse, and troubleshoot delivery. The contact endpoint applies rate limits. We do not install advertising pixels or analytics tracking scripts on this public website.</p>
        <h2>Browser storage</h2><p>We store your cookie-notice preference only after you choose to save it. See the <a href="/legal/cookies">cookie policy</a> for the storage name, purpose, and duration.</p>
        <h2>Your requests</h2><p>For questions about your enquiry, retention, access, correction, or deletion of information you have shared, email <a href="mailto:support@phirmy.com">support@phirmy.com</a>. Include your enquiry reference if you have one. We may need to verify a request before changing or releasing information.</p>
        <h2>Product services</h2><p>This notice describes the public website and contact flow. Workspace use, customer conversations, connected providers, and any future paid service require the information and terms presented with that service.</p>
      </> : <>
        <h2>About this website</h2><p>This website introduces Phirmy’s voice and chat product and lets you contact the team. The walkthroughs are illustrations using sample conversations, not live calls, customer testimonials, or evidence of actual bookings.</p>
        <h2>Product availability</h2><p>Features depend on workspace configuration, connected providers, and permissions. Phone channels require their own setup. Public rollout and paid activation are being prepared; an enquiry does not create a subscription or guarantee a launch date, service level, or price.</p>
        <h2>Using the contact form</h2><p>Send information you are entitled to share. Do not use the form for spam, harmful content, or sensitive credentials. We may limit abusive requests to keep the service available.</p>
        <h2>Separate service terms</h2><p>Terms for a configured workspace or a paid service will be provided as part of that service. This page does not replace an agreement you have separately entered into with Phirmy.</p>
      </>}
      <h2>Contact</h2><p>For questions about this {document === "cookies" ? "policy" : "page"}, contact <a href="mailto:support@phirmy.com">support@phirmy.com</a>.</p>
    </main>
    <footer className="legal-footer"><span>© {new Date().getFullYear()} Phirmy</span><a href="/legal/privacy">Privacy</a><a href="/legal/cookies">Cookies</a><a href="/legal/terms">Terms</a><button onClick={openCookieSettings}>Cookie settings</button></footer>
  </div>;
}
