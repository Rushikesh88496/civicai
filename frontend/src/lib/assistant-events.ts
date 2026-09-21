"use client";

// Lightweight bridge so any citizen surface can open the floating CivicAI
// assistant widget (optionally prefilled with a question). The widget listens
// for this event; if the widget is not mounted nothing happens.
export function openCivicAssistant(query?: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("civicai:open-assistant", {
      detail: query ? { query } : undefined,
    })
  );
}