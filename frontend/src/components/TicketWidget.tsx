import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

// The IAfluence floating "report a problem" widget (ticket-widget project). Empty VITE_TICKET_WIDGET_URL = no widget.
const WIDGET_URL = import.meta.env.VITE_TICKET_WIDGET_URL ?? "https://tickets.widget.iafluence.fr/static/ticket.js";
const SCRIPT_ID = "iafluence-ticket-script";
const HOST_ID = "iafluence-ticket-root";

// A booking link carries its access token in the path, and the widget files the page URL in the Gitea issue:
// no widget there.
const TOKEN_PAGE = /^\/(?:(?:fr|en|es)\/)?reservation\/[^/]+/;

export const isTokenPage = (pathname: string) => TOKEN_PAGE.test(pathname);

export function TicketWidget() {
  const { pathname } = useLocation();
  const excluded = isTokenPage(pathname);
  const excludedRef = useRef(excluded);
  excludedRef.current = excluded;

  useEffect(() => {
    // The widget's shadow root resets its host's styles (`all: initial`): only an inline style hides it.
    const apply = () => {
      const host = document.getElementById(HOST_ID);
      if (host) host.style.display = excludedRef.current ? "none" : "";
    };
    apply();
    // Loaded on the first page that allows it, so a booking link opened directly never runs the third-party script.
    if (excluded || !WIDGET_URL || document.getElementById(SCRIPT_ID)) return;
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = WIDGET_URL;
    script.dataset.app = "booking";
    script.defer = true;
    // The visitor may have reached a booking link while it loaded.
    script.addEventListener("load", apply);
    document.body.append(script);
  }, [excluded]);

  return null;
}
