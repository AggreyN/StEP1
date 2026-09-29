"use client";
// "Delete my account", at the bottom of the Profile screen. Quiet on the
// page, explicit in the dialog: it lists what goes and needs something typed
// and a ticked box before the button works. What is typed depends on how
// people sign in: the password (local), or the word DELETE (Cognito, where
// this site has no password to ask for).
import { useState, type FormEvent } from "react";
import { deleteAccount } from "@/lib/api";
import { clearLocalState, leaveNotice, signOutDestination } from "@/lib/auth";
import { AUTH_MODE } from "@/lib/config";

const COGNITO = AUTH_MODE === "cognito";
const WORD = "DELETE";
import { Dialog } from "./Dialog";
import { Button, ErrorNote } from "./ui";

function DeleteForm({ onCancel }: { onCancel: () => void }) {
  // the password in local mode, the word DELETE in cognito mode
  const [typed, setTyped] = useState("");
  const [sure, setSure] = useState(false);
  const typedOk = COGNITO ? typed.trim().toUpperCase() === WORD : typed.length > 0;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!typedOk || !sure || busy) return;
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(COGNITO ? undefined : typed);
      clearLocalState();
      // Cognito mode leaves by way of Cognito's sign-out, which can't carry a
      // query string back, so the message waits in this tab instead.
      if (COGNITO) leaveNotice("deleted");
      // A full page load, so nothing of the old session survives in memory.
      window.location.assign(signOutDestination("/login?deleted=1"));
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

      {COGNITO ? (
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Type {WORD} to confirm</span>
          <input
            type="text"
            data-autofocus
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="h-11 w-full rounded-control border border-line-strong bg-surface px-3 font-mono text-[15px]"
          />
        </label>
      ) : (
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Your password</span>
          <input
            type="password"
            data-autofocus
            autoComplete="current-password"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="h-11 w-full rounded-control border border-line-strong bg-surface px-3 text-[15px]"
          />
        </label>
      )}

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
        <Button type="submit" variant="danger" disabled={!typedOk || !sure || busy} data-testid="confirm-delete">
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
