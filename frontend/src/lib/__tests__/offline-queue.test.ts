import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "@/lib/auth-api";
import {
  enqueueAction,
  newClientRef,
  pendingCount,
  processQueue,
} from "@/lib/offline-queue";

function jsonRes(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("processQueue permanent-error handling", () => {
  beforeEach(() => {
    localStorage.clear();
    // A valid session so the sync actually reaches the action endpoints.
    setSession({
      access_token: "at",
      refresh_token: "rt",
      token_type: "bearer",
      expires_in: 3600,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/auth/refresh")) {
          return jsonRes(200, {
            access_token: "at",
            refresh_token: "rt",
            token_type: "bearer",
            expires_in: 3600,
          });
        }
        return handler(url, init);
      })
    );
  }

  it("reports a permanently rejected action as failed instead of silently dropping it", async () => {
    stubFetch((url) => {
      if (url.endsWith("/photos")) {
        return jsonRes(400, { detail: "Unsupported image type." });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    enqueueAction({
      orderId: "order-1",
      kind: "photo",
      category: "BEFORE",
      fileDataUrl: "data:image/jpeg;base64,AAAA",
      fileName: "before.jpg",
      fileType: "image/jpeg",
      payload: { client_ref: newClientRef(), geo_denied: false },
    });
    expect(pendingCount()).toBe(1);

    const report = await processQueue();

    // The failure is surfaced so the UI can show a real error (not "Photo
    // uploaded."), while the poison action is dropped so it can't block later syncs.
    expect(report.synced).toBe(0);
    expect(report.remaining).toBe(0);
    expect(report.failed).toBeDefined();
    expect(report.failed![0]).toContain("Unsupported image type.");
    expect(report.error).toContain("Unsupported image type.");
    expect(pendingCount()).toBe(0);
  });

  it("keeps syncing later actions after a poisoned one is dropped", async () => {
    stubFetch((url) => {
      if (url.endsWith("/accept")) return jsonRes(200, { ok: true });
      if (url.endsWith("/photos")) return jsonRes(400, { detail: "Unsupported image type." });
      throw new Error(`unexpected fetch: ${url}`);
    });

    enqueueAction({
      orderId: "order-1",
      kind: "photo",
      category: "BEFORE",
      fileDataUrl: "data:image/jpeg;base64,AAAA",
      fileName: "before.jpg",
      fileType: "image/jpeg",
      payload: { client_ref: newClientRef(), geo_denied: false },
    });
    enqueueAction({
      orderId: "order-1",
      kind: "accept",
      payload: { client_ref: newClientRef() },
    });

    const report = await processQueue();
    expect(report.synced).toBe(1);
    expect(report.failed?.[0]).toContain("Unsupported image type.");
    expect(pendingCount()).toBe(0);
  });

  it("reports a successful sync with no failed actions", async () => {
    stubFetch((url) => {
      if (url.endsWith("/accept")) return jsonRes(200, { ok: true });
      throw new Error(`unexpected fetch: ${url}`);
    });
    enqueueAction({
      orderId: "order-1",
      kind: "accept",
      payload: { client_ref: newClientRef() },
    });
    const report = await processQueue();
    expect(report.synced).toBe(1);
    expect(report.failed).toBeUndefined();
    expect(pendingCount()).toBe(0);
  });
});