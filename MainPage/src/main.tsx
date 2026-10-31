import React from "react";
import ReactDOM from "react-dom/client";
import { MotionConfig } from "motion/react";
import App from "./App";
import ContactPage from "./ContactPage";
import "./styles.css";
import "./editorial.css";
import CookieControls from "./components/CookieControls";
import LegalPage from "./LegalPage";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MotionConfig reducedMotion="user">
      {/^\/legal\/(cookies|privacy|terms)\/?$/.test(window.location.pathname) ? <LegalPage document={window.location.pathname.split("/")[2]}/> : window.location.pathname.replace(/\/$/, "") === "/contact" ? (
        <ContactPage />
      ) : (
        <App />
      )}
      <CookieControls/>
    </MotionConfig>
  </React.StrictMode>,
);
