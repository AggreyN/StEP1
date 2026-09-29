"use client";
// "Delete my account", at the bottom of the Profile screen. Quiet on the
// page, explicit in the dialog: it lists what goes, asks for the password,
// and needs a ticked box before the button works.
import { useState, type FormEvent } from "react";
import { deleteAccount } from "@/lib/api";
import { clearLocalState } from "@/lib/auth";
import { Dialog } from "./Dialog";
import { Button, ErrorNote } from "./ui";

function DeleteForm({ onCancel }: { onCancel: () => void }) {
  const [password, setPassword] = useState("");
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password || !sure || busy) return;
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password);
      clearLocalState();
      // A full page load, so nothing of the old session survives in memory.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login?deleted=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't delete the account.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div className="text-sm">
        <p className="font-medium">This removes, immediately and for good:</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted" data-testid="delete-list">
          <li>your account and sign-in</li>
          <li>your profile and ranked fields</li>
          <li>your resume file, and the text and skills read from it</li>
          <li>your saved postings</li>
          <li>every application you tracked, with its events and notes</li>
        </ul>
        <p className="mt-2 text-muted">There is no undo and no backup to restore from.</p>
      </div>

      <label className="block">
        <span className="mb-1 block text-sm font-medium">Your password</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="h-11 w-full rounded-control border border-line-strong bg-surface px-3 text-[15px] focus:border-accent focus:outline-none"
        />
      </label>

      <label className="flex cursor-pointer items-start gap-3 text-sm">
        <input
          type="checkbox"
          checked={sure}
          onChange={(e) => setSure(e.target.checked)}
          className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--danger)]"
        />
        <span>I understand this deletes everything and can&apos;t be undone.</span>
      </label>

      {error && <ErrorNote>{error}</ErrorNote>}

      <div className="flex justify-end gap-2">
        <Button type="button" onClick={onCancel} disabled={busy}>
          Keep my account
        </Button>
        <Button type="submit" variant="danger" disabled={!password || !sure || busy} data-testid="confirm-delete">
          {busy ? "Deleting…" : "Delete my account"}
        </Button>
      </div>
    </form>
  );
}

export function DeleteAccount() {
  const [open, setOpen] = useState(false);
  return (
    <section
      aria-labelledby="delete-account-heading"
      className="rounded-card border border-line bg-surface p-3.5 sm:p-5"
    >
      <h2 id="delete-account-heading" className="text-base font-semibold">
        Delete my account
      </h2>
      <p className="mt-0.5 max-w-prose text-sm text-muted">
        Removes your account, your resume file and all of your history, immediately. This can&apos;t be undone.
      </p>
      <Button variant="danger" size="sm" className="mt-3" onClick={() => setOpen(true)} data-testid="open-delete">
        Delete my account…
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Delete your account?">
        {/* remounted on each open, so a half-typed password never lingers */}
        <DeleteForm onCancel={() => setOpen(false)} />
      </Dialog>
    </section>
  );
}
