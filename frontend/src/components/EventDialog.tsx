"use client";
// Records one timeline event. `kind` comes from the API's next_transitions
// (or is "note"); this component doesn't know what may follow what.
import { useState } from "react";
import { addEvent } from "@/lib/api";
import { dateInputToIso, todayInput } from "@/lib/format";
import { kindLabel } from "@/lib/labels";
import type { ApplicationDetail } from "@/lib/types";
import { Dialog } from "./Dialog";
import { Button, ErrorNote } from "./ui";

const field =
  "w-full rounded-lg border border-line-strong bg-surface px-3 text-[15px] placeholder:text-faint focus:border-accent focus:outline-none";

function EventForm({
  applicationId,
  kind,
  onClose,
  onSaved,
}: {
  applicationId: number;
  kind: string;
  onClose: () => void;
  onSaved: (detail: ApplicationDetail) => void;
}) {
  const isNote = kind === "note";
  const [date, setDate] = useState(todayInput());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const occurred_at = dateInputToIso(date);
      const detail = await addEvent(applicationId, {
        kind,
        ...(occurred_at ? { occurred_at } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      onSaved(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that.");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <label className="block">
        <span className="mb-1 block text-sm font-medium">
          Date <span className="font-normal text-faint">(optional)</span>
        </span>
        <input
          type="date"
          value={date}
          max={todayInput()}
          onChange={(e) => setDate(e.target.value)}
          className={`${field} h-11`}
        />
      </label>
      <label className="block">
        <span className="mb-1 block text-sm font-medium">
          Note {!isNote && <span className="font-normal text-faint">(optional)</span>}
        </span>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder={isNote ? "What do you want to remember?" : "Who you spoke to, what's next…"}
          className={`${field} py-2`}
        />
      </label>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={save} disabled={busy || (isNote && !note.trim())} data-testid="save-event">
          {busy ? "Saving…" : isNote ? "Add note" : `Mark as ${kindLabel(kind).toLowerCase()}`}
        </Button>
      </div>
    </div>
  );
}

export function EventDialog({
  applicationId,
  kind,
  onClose,
  onSaved,
}: {
  applicationId: number;
  kind: string | null;
  onClose: () => void;
  onSaved: (detail: ApplicationDetail) => void;
}) {
  return (
    <Dialog open={!!kind} onClose={onClose} title={kind === "note" ? "Add a note" : kind ? kindLabel(kind) : ""}>
      {/* keyed so each open starts with a fresh form */}
      {kind && <EventForm key={kind} applicationId={applicationId} kind={kind} onClose={onClose} onSaved={onSaved} />}
    </Dialog>
  );
}
