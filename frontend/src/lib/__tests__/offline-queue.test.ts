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

  it("adopts the server-confirmed evidence detail from a synced photo upload", async () => {
    stubFetch((url) => {
      if (url.endsWith("/photos")) {
        return jsonRes(200, {
          work_order: {
            id: "order-1",
            status: "WORK_COMPLETED",
            has_before_photo: true,
            has_after_photo: false,
          },
          photos: [
            {
              id: "photo-1",
              category: "BEFORE",
              allowed: true,
              url: "/media/order-1/before.png",
              recorded_at: "2026-09-12T13:00:00Z",
            },
          ],
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    enqueueAction({
      orderId: "order-1",
      kind: "photo",
      category: "BEFORE",
      fileDataUrl: "data:image/png;base64,AAAA",
      fileName: "before.png",
      fileType: "image/png",
      payload: { client_ref: newClientRef(), geo_denied: false },
    });
    const report = await processQueue();
    expect(report.synced).toBe(1);
    expect(report.remaining).toBe(0);
    // The persisted response must survive the queue so handleUploadPhoto can
    // drive both the evidence preview and submit-validation from the same
    // canonical server state — never from a stale local draft.
    expect(report.detail?.work_order.has_before_photo).toBe(true);
    expect(report.detail?.photos[0].id).toBe("photo-1");
  });
});

describe("offline photo budget + queue persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("queues a photo that fits the offline snapshot budget", () => {
    const result = enqueueAction({
      orderId: "order-1",
      kind: "photo",
      category: "BEFORE",
      fileDataUrl: "data:image/jpeg;base64,AAAA",
      fileName: "before.jpg",
      fileType: "image/jpeg",
      payload: { client_ref: newClientRef(), geo_denied: false },
    });
    expect(result.ok).toBe(true);
    expect(pendingCount()).toBe(1);
  });

  it("rejects a photo larger than the offline snapshot budget instead of silently losing it", () => {
    // ~2.1 MB of base64 raw line ≈ >1.5 MB of decoded bytes: a typical real
    // phone camera photo that used to never reach the server.
    const big = `data:image/jpeg;base64,${"A".repeat(2_100_000)}`;
    const result = enqueueAction({
      orderId: "order-1",
      kind: "photo",
      category: "BEFORE",
      fileDataUrl: big,
      fileName: "camera.jpg",
      fileType: "image/jpeg",
      payload: { client_ref: newClientRef(), geo_denied: false },
    });
    expect(result.ok).toBe(false);
    expect(pendingCount()).toBe(0);
  });

  it("fails loudly when the queue cannot be persisted instead of reporting a false success", () => {
    // localStorage quota full: the old code silently dropped the item but still
    // returned ok:true, so the UI showed "Photo uploaded." though nothing was
    // ever queued or sent.
    vi.spyOn(Object.getPrototypeOf(localStorage), "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    const result = enqueueAction({
      orderId: "order-1",
      kind: "accept",
      payload: { client_ref: newClientRef() },
    });
    expect(result.ok).toBe(false);
    expect(pendingCount()).toBe(0);
  });
});