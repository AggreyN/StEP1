"use client";
// "I applied" — confirm the date, then POST /applications.
import { useState } from "react";
import { createApplication } from "@/lib/api";
import { dateInputToIso, todayInput } from "@/lib/format";
import type { ApplicationDetail, Posting } from "@/lib/types";
import { Dialog } from "./Dialog";
import { Button, ErrorNote } from "./ui";

export function ApplyDialog({
  posting,
  onClose,
  onCreated,
}: {
  posting: Posting | null;
  onClose: () => void;
  onCreated: (app: ApplicationDetail) => void;
}) {
  const [date, setDate] = useState(todayInput());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    if (!posting) return;
    setBusy(true);
    setError(null);
    try {
      const app = await createApplication(posting.id, dateInputToIso(date));
      onCreated(app);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={!!posting} onClose={onClose} title="Track this application">
      {posting && (
        <div className="space-y-4">
          <p className="text-sm text-muted">
            <span className="font-medium text-fg">{posting.title}</span> at {posting.company.name}. We&apos;ll start a
            timeline so you can log what happens next.
          </p>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Date applied</span>
            <input
              type="date"
              value={date}
              max={todayInput()}
              onChange={(e) => setDate(e.target.value)}
              className="h-11 w-full rounded-control border border-line-strong bg-surface px-3 text-[15px] focus:border-accent focus:outline-none"
            />
          </label>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="flex justify-end gap-2">
            <Button onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button variant="primary" onClick={confirm} disabled={busy} data-testid="confirm-applied">
              {busy ? "Saving…" : "I applied"}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
