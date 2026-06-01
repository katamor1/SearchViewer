import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

declare global {
  interface Window {
    __searchViewerClientLog?: (payload: Record<string, unknown>) => void;
  }
}

export function reportClientEvent(payload: Record<string, unknown>) {
  if (window.__searchViewerClientLog) {
    window.__searchViewerClientLog(payload);
    return;
  }
  fetch("/api/client-log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {});
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function showStartupError(error: unknown) {
  const rootElement = document.getElementById("root");
  if (!rootElement) {
    return;
  }
  rootElement.innerHTML = "";
  const shell = document.createElement("main");
  shell.className = "startup-error";
  const title = document.createElement("h1");
  title.textContent = "SearchViewer startup error";
  const message = document.createElement("p");
  message.textContent = errorMessage(error);
  shell.append(title, message);
  rootElement.append(shell);
}

try {
  const rootElement = document.getElementById("root");
  if (!rootElement) {
    throw new Error("Root element #root was not found.");
  }
  createRoot(rootElement).render(
    <StrictMode>
      <App />
    </StrictMode>
  );
} catch (error) {
  reportClientEvent({
    type: "react_startup_error",
    message: errorMessage(error),
  });
  showStartupError(error);
}
