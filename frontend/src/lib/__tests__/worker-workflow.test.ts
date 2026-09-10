import { describe, expect, it } from "vitest";
import type {
  WorkerJob,
  WorkerOrderDetail,
  WorkOrderActivity,
  WorkerVerification,
} from "@/lib/field-worker-api";
import { buildWorkflow, checkInActivity, isSameLocalDay } from "@/lib/worker-workflow";

function activity(type: string, recordedAt = "2026-01-02T09:00:00Z"): WorkOrderActivity {
  return {
    id: `act-${type}-${recordedAt}`,
    activity_type: type,
    note: null,
    latitude: null,
    longitude: null,
    geo_denied: false,
    media_id: null,
    worker_name: null,
    recorded_at: recordedAt,
  };
}

function job(overrides: Partial<WorkerJob> = {}): WorkerJob {
  return {
    id: "order-1",
    complaint_id: "comp-1",
    incident: "Dumped garbage",
    department: "WASTE",
    priority: "P1_CRITICAL",
    status: "ASSIGNED",
    has_before_photo: false,
    has_after_photo: false,
    ...overrides,
  };
}

function detail(overrides: Partial<WorkerOrderDetail> = {}): WorkerOrderDetail {
  return {
    work_order: job(),
    complaint_id: "comp-1",
    complaint_title: "Dumped garbage",
    photos: [],
    activities: [],
    status_history: [],
    ...overrides,
  };
}

const verified: WorkerVerification = {
  id: "ver-1",
  work_order_id: "order-1",
  complaint_id: "comp-1",
  before_url: "",
  after_url: "",
  repair_evidence: "Debris cleared",
  remaining_issue: null,
  confidence: 0.92,
  verification_status: "VERIFIED",
  human_review_required: false,
  source: "groq",
  review_note: null,
  reviewed_at: null,
  created_at: "2026-01-02T10:00:00Z",
};

describe("buildWorkflow", () => {
  it("starts at Accept Task for a freshly assigned job", () => {
    const wf = buildWorkflow(detail(), null);
    expect(wf.doneCount).toBe(0);
    expect(wf.steps[0].current).toBe(true);
    expect(wf.pendingStepKey).toBe("accept");
    expect(wf.currentStatus).toBe("Assigned — awaiting acceptance");
  });

  it("moves to check-in after accept", () => {
    const d = detail({
      work_order: job({ accepted_at: "2026-01-02T09:00:00Z" }),
    });
    const wf = buildWorkflow(d, null);
    expect(wf.steps[0].done).toBe(true);
    expect(wf.steps[1].current).toBe(true);
    expect(wf.pendingStepKey).toBe("check-in");
  });

  it("moves to start after check-in", () => {
    const d = detail({
      work_order: job({ accepted_at: "2026-01-02T09:00:00Z" }),
      activities: [activity("CHECK_IN")],
    });
    const wf = buildWorkflow(d, null);
    expect(wf.steps[1].done).toBe(true);
    expect(wf.steps[2].current).toBe(true);
    expect(wf.pendingStepKey).toBe("start");
    expect(wf.currentStatus).toBe("Accepted — head to the location");
  });

  it("asks to finish the physical work once work has started", () => {
    const d = detail({
      work_order: job({
        accepted_at: "2026-01-02T09:00:00Z",
        started_at: "2026-01-02T09:10:00Z",
        status: "IN_PROGRESS",
      }),
      activities: [activity("CHECK_IN"), activity("START_WORK")],
    });
    const wf = buildWorkflow(d, null);
    expect(wf.steps[2].done).toBe(true);
    expect(wf.steps[3].current).toBe(true);
    expect(wf.pendingStepKey).toBe("finish");
  });

  it("asks for the resolution evidence once work is finished", () => {
    const d = detail({
      work_order: job({
        accepted_at: "2026-01-02T09:00:00Z",
        started_at: "2026-01-02T09:10:00Z",
        status: "WORK_COMPLETED",
        completed_at: "2026-01-02T10:00:00Z",
      }),
      activities: [
        activity("CHECK_IN"),
        activity("START_WORK"),
        activity("FINISH_WORK"),
      ],
    });
    const wf = buildWorkflow(d, null);
    expect(wf.steps[3].done).toBe(true);
    expect(wf.steps[4].current).toBe(true);
    expect(wf.pendingStepKey).toBe("evidence");
  });

  it("waits for officer verification once the resolution evidence is submitted", () => {
    const d = detail({
      work_order: job({
        accepted_at: "2026-01-02T09:00:00Z",
        started_at: "2026-01-02T09:10:00Z",
        completed_at: "2026-01-02T10:00:00Z",
        evidence_submitted_at: "2026-01-02T10:05:00Z",
        status: "EVIDENCE_SUBMITTED",
        has_before_photo: true,
        has_after_photo: true,
      }),
      activities: [
        activity("CHECK_IN"),
        activity("START_WORK"),
        activity("FINISH_WORK"),
        activity("SUBMIT_EVIDENCE"),
      ],
    });
    const wf = buildWorkflow(d, null);
    expect(wf.total).toBe(6);
    expect(wf.steps[4].done).toBe(true);
    expect(wf.steps[5].done).toBe(false);
    expect(wf.steps[5].current).toBe(true);
    // The worker must NOT see an AI verification step (that is officer-side).
    expect(wf.steps[5].key).toBe("officer-verification");
    expect(wf.steps.find((s) => s.key === "ai-verification")).toBeUndefined();
    expect(wf.pendingStepKey).toBe(null);
    expect(wf.currentStatus).toContain("awaiting officer verification");
    expect(wf.nextAction).toContain("waiting for the officer to verify");
  });

  it("marks officer verification once reviewed and completed", () => {
    const d = detail({
      work_order: job({
        accepted_at: "2026-01-02T09:00:00Z",
        started_at: "2026-01-02T09:10:00Z",
        completed_at: "2026-01-02T10:00:00Z",
        evidence_submitted_at: "2026-01-02T10:05:00Z",
        status: "CLOSED",
        has_before_photo: true,
        has_after_photo: true,
      }),
      activities: [
        activity("CHECK_IN"),
        activity("START_WORK"),
        activity("FINISH_WORK"),
        activity("SUBMIT_EVIDENCE"),
      ],
    });
    const wf = buildWorkflow(d, { ...verified, reviewed_at: "2026-01-02T11:00:00Z" });
    expect(wf.doneCount).toBe(6);
    expect(wf.steps[4].done).toBe(true);
    expect(wf.steps[5].done).toBe(true);
    expect(wf.currentStatus).toBe("Completed — resolution verified");
    expect(wf.verified).toBe(true);
  });

  it("reports follow-up when an officer review reopens the job", () => {
    const d = detail({
      work_order: job({
        accepted_at: "2026-01-02T09:00:00Z",
        started_at: "2026-01-02T09:10:00Z",
        status: "IN_PROGRESS",
        has_before_photo: true,
        has_after_photo: true,
      }),
      activities: [],
    });
    const wf = buildWorkflow(d, { ...verified, reviewed_at: "2026-01-02T11:00:00Z" });
    expect(wf.steps[5].done).toBe(true);
    expect(wf.currentStatus).toBe("Officer requested follow-up");
  });
});

describe("check-in markers", () => {
  it.each(["EN_ROUTE", "ARRIVED"])(
    "unlocks Start Work when the server records a %s check-in",
    (kind) => {
      // Regression: the backend stores actual check-ins as EN_ROUTE / ARRIVED
      // activity rows — these must count as checked in, or Start Work stays
      // locked forever in the real app.
      const d = detail({
        work_order: job({ accepted_at: "2026-01-02T09:00:00Z" }),
        activities: [activity(kind)],
      });
      const wf = buildWorkflow(d, null);
      expect(wf.steps[1].done).toBe(true);
      expect(wf.pendingStepKey).toBe("start");
    }
  );

  it("does not unlock Start Work without a check-in", () => {
    const d = detail({
      work_order: job({ accepted_at: "2026-01-02T09:00:00Z" }),
      activities: [],
    });
    const wf = buildWorkflow(d, null);
    expect(wf.pendingStepKey).toBe("check-in");
  });
});

describe("checkInActivity", () => {
  it("returns null when there is no check-in", () => {
    const d = detail({
      work_order: job({ accepted_at: "2026-01-02T09:00:00Z" }),
      activities: [activity("ACCEPT")],
    });
    expect(checkInActivity(d)).toBeNull();
    expect(checkInActivity(null)).toBeNull();
  });

  it("returns the most recent check-in activity", () => {
    const older = { ...activity("EN_ROUTE"), id: "act-1", recorded_at: "2026-01-02T09:00:00Z" };
    const newer = { ...activity("ARRIVED"), id: "act-2", recorded_at: "2026-01-02T09:05:00Z" };
    const d = detail({
      work_order: job({ accepted_at: "2026-01-02T09:00:00Z" }),
      activities: [older, activity("ACCEPT"), newer, activity("START_WORK")],
    });
    const found = checkInActivity(d);
    expect(found?.id).toBe("act-2");
    expect(found?.activity_type).toBe("ARRIVED");
  });

  it("ignores round-1 check-ins once a rework was requested", () => {
    const roundOne = { ...activity("EN_ROUTE"), id: "act-1", recorded_at: "2026-01-02T09:00:00Z" };
    const fresh = { ...activity("ARRIVED"), id: "act-2", recorded_at: "2026-01-02T11:15:00Z" };
    const d = detail({
      work_order: job({ accepted_at: "2026-01-02T09:00:00Z" }),
      activities: [roundOne, fresh],
      status_history: [
        { action: "REWORK_REQUESTED", note: null, recorded_at: "2026-01-02T11:00:00Z" },
      ],
    });
    expect(checkInActivity(d)?.id).toBe("act-2");
  });

  it("returns null for a reworked job with no post-rework check-in", () => {
    const d = detail({
      work_order: job({
        accepted_at: "2026-01-02T09:00:00Z",
        status: "RETURNED_FOR_REWORK",
      }),
      activities: [activity("ARRIVED", "2026-01-02T10:30:00Z")],
      status_history: [
        { action: "REWORK_REQUESTED", note: null, recorded_at: "2026-01-02T11:00:00Z" },
      ],
    });
    expect(checkInActivity(d)).toBeNull();
  });
});

describe("rework", () => {
  const REWORK_AT = "2026-01-02T11:00:00Z";
  // Round-1 state that must be IGNORED once the officer requested rework.
  const roundOne = () =>
    detail({
      work_order: job({
        accepted_at: "2026-01-02T09:00:00Z",
        started_at: "2026-01-02T09:10:00Z",
        completed_at: "2026-01-02T10:00:00Z",
        evidence_submitted_at: "2026-01-02T10:05:00Z",
        status: "RETURNED_FOR_REWORK",
        has_before_photo: true,
        has_after_photo: true,
      }),
      activities: [
        activity("CHECK_IN"),
        activity("START_WORK"),
        activity("FINISH_WORK"),
        activity("SUBMIT_EVIDENCE"),
      ],
      status_history: [
        { action: "REWORK_REQUESTED", note: "Debris still present", recorded_at: REWORK_AT },
      ],
    });
  // Round-1 verification dated BEFORE the rework request — must be ignored.
  const staleVerification = {
    ...verified,
    reviewed_at: "2026-01-02T10:30:00Z",
  };

  it("returns the job for a FRESH GPS check-in after REQUEST_REWORK", () => {
    const wf = buildWorkflow(roundOne(), staleVerification);
    expect(wf.reworkRequestedAt).toBe(REWORK_AT);
    expect(wf.steps[4].done).toBe(false);
    expect(wf.steps[5].done).toBe(false);
    expect(wf.verified).toBe(false);
    expect(wf.pendingStepKey).toBe("check-in");
    expect(wf.currentStatus).toBe("Returned for rework — officer requested fixes");
  });

  it("unlocks Start Rework only after a rework-window check-in", () => {
    // A round-1 check-in is NOT enough.
    const noFresh = buildWorkflow(roundOne(), staleVerification);
    expect(noFresh.checkedIn).toBe(false);

    const d = roundOne();
    d.activities.push(activity("EN_ROUTE", "2026-01-02T11:15:00Z"));
    const wf = buildWorkflow(d, staleVerification);
    expect(wf.checkedIn).toBe(true);
    expect(wf.started).toBe(false);
    expect(wf.pendingStepKey).toBe("rework");
    expect(wf.currentStatus).toBe("Returned for rework — officer requested fixes");
  });

  it("moves into rework once START REWORK has run", () => {
    const d = roundOne();
    d.activities.push(
      activity("EN_ROUTE", "2026-01-02T11:15:00Z"),
      activity("START_REWORK", "2026-01-02T11:20:00Z")
    );
    d.work_order.started_at = "2026-01-02T11:20:00Z";
    const wf = buildWorkflow(d, staleVerification);
    expect(wf.started).toBe(true);
    expect(wf.finished).toBe(false);
    expect(wf.pendingStepKey).toBe("finish");
    expect(wf.currentStatus).toBe("Rework in progress");
  });

  it("tracks the finished rework and asks for a FRESH evidence submission", () => {
    const d = roundOne();
    d.activities.push(
      activity("EN_ROUTE", "2026-01-02T11:15:00Z"),
      activity("START_REWORK", "2026-01-02T11:20:00Z"),
      activity("FINISH_WORK", "2026-01-02T11:40:00Z")
    );
    d.work_order.started_at = "2026-01-02T11:20:00Z";
    d.work_order.completed_at = "2026-01-02T11:40:00Z";
    const wf = buildWorkflow(d, staleVerification);
    expect(wf.finished).toBe(true);
    expect(wf.evidenceSubmitted).toBe(false);
    expect(wf.pendingStepKey).toBe("evidence");
    expect(wf.currentStatus).toBe("Rework finished — submit resolution evidence");
  });

  it("ignores the stale round-1 verification and waits for a fresh officer verdict", () => {
    const d = roundOne();
    d.activities.push(
      activity("EN_ROUTE", "2026-01-02T11:15:00Z"),
      activity("START_REWORK", "2026-01-02T11:20:00Z"),
      activity("FINISH_WORK", "2026-01-02T11:40:00Z"),
      activity("SUBMIT_EVIDENCE", "2026-01-02T11:45:00Z")
    );
    d.work_order.started_at = "2026-01-02T11:20:00Z";
    d.work_order.completed_at = "2026-01-02T11:40:00Z";
    d.work_order.evidence_submitted_at = "2026-01-02T11:45:00Z";
    d.work_order.status = "EVIDENCE_SUBMITTED";
    const wf = buildWorkflow(d, staleVerification);
    expect(wf.steps[4].done).toBe(true);
    expect(wf.verified).toBe(false);
    expect(wf.pendingStepKey).toBe(null);
    expect(wf.currentStatus).toBe("Rework finished — awaiting officer verification");
    expect(wf.nextAction).toContain("waiting for the officer to verify");
  });

  it("treats a fresh post-rework verification as the completed resolution", () => {
    const d = roundOne();
    d.activities.push(
      activity("EN_ROUTE", "2026-01-02T11:15:00Z"),
      activity("START_REWORK", "2026-01-02T11:20:00Z"),
      activity("FINISH_WORK", "2026-01-02T11:40:00Z"),
      activity("SUBMIT_EVIDENCE", "2026-01-02T11:45:00Z")
    );
    d.work_order.started_at = "2026-01-02T11:20:00Z";
    d.work_order.completed_at = "2026-01-02T11:40:00Z";
    d.work_order.evidence_submitted_at = "2026-01-02T11:45:00Z";
    d.work_order.status = "EVIDENCE_SUBMITTED";
    const wf = buildWorkflow(d, {
      ...verified,
      created_at: "2026-01-02T11:50:00Z",
      reviewed_at: "2026-01-02T11:55:00Z",
    });
    expect(wf.doneCount).toBe(6);
    expect(wf.verified).toBe(true);
    expect(wf.currentStatus).toBe("Completed — resolution verified");
  });
});

describe("isSameLocalDay", () => {
  it("matches same calendar day in local time", () => {
    const today = new Date();
    const isoToday = today.toISOString();
    expect(isSameLocalDay(isoToday, today)).toBe(true);
  });

  it("rejects null, empty, and invalid values", () => {
    expect(isSameLocalDay(null, new Date())).toBe(false);
    expect(isSameLocalDay(undefined, new Date())).toBe(false);
    expect(isSameLocalDay("garbage", new Date())).toBe(false);
  });
});