"use client";
// Owns the mutations shared by the dashboard and the saved list: optimistic
// save/unsave with rollback, and "I applied". Fetching stays in the page.
import { useState } from "react";
import { savePosting, unsavePosting } from "@/lib/api";
import type { ApplicationDetail, Posting } from "@/lib/types";
import { ApplyDialog } from "./ApplyDialog";
import { PostingCard } from "./PostingCard";
import { ErrorNote } from "./ui";

export function PostingList({
  items,
  onPatch,
  onUnsaved,
}: {
  items: Posting[];
  /** Apply a change to one posting in the page's list state. */
  onPatch: (id: string, fn: (p: Posting) => Posting) => void;
  /** Saved page: remove the card once the unsave is confirmed. */
  onUnsaved?: (id: string) => void;
}) {
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [applying, setApplying] = useState<Posting | null>(null);
  const [error, setError] = useState<string | null>(null);

  const patch = onPatch;

  async function toggleSave(p: Posting) {
    const was = p.saved;
    setError(null);
    setPending((s) => new Set(s).add(p.id));
    patch(p.id, (x) => ({ ...x, saved: !was }));
    try {
      if (was) await unsavePosting(p.id);
      else await savePosting(p.id);
      if (was) onUnsaved?.(p.id);
    } catch (e) {
      patch(p.id, (x) => ({ ...x, saved: was })); // rollback
      setError(e instanceof Error ? e.message : "Couldn't update your saved list.");
    } finally {
      setPending((s) => {
        const n = new Set(s);
        n.delete(p.id);
        return n;
      });
    }
  }

  function created(app: ApplicationDetail) {
    patch(app.posting.id, (x) => ({ ...x, application: { id: app.id, status: app.status } }));
    setApplying(null);
  }

  return (
    <>
      {error && (
        <div className="mb-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}
      <ul className="space-y-3">
        {items.map((p) => (
          <li key={p.id}>
            <PostingCard posting={p} onToggleSave={toggleSave} onApply={setApplying} saving={pending.has(p.id)} />
          </li>
        ))}
      </ul>
      <ApplyDialog posting={applying} onClose={() => setApplying(null)} onCreated={created} />
    </>
  );
}
