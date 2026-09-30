"use client";
// "Leave a review": a rating and a few words, sent to the owner.
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { submitReview } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useMe } from "@/lib/me";
import { AppShell } from "@/components/AppShell";
import { StarRating } from "@/components/StarRating";
import { Button, ErrorNote } from "@/components/ui";

const MAX = 2000;

export default function ReviewPage() {
  const authed = useRequireAuth();
  const me = useMe();
  const [rating, setRating] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const length = text.trim().length;
  const tooLong = length > MAX;
  const ready = rating !== null && length > 0 && !tooLong;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await submitReview({ rating: rating!, body: text.trim() });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Your review couldn't be sent.");
    } finally {
      setBusy(false);
    }
  }

  if (!authed) return null;

  return (
    <AppShell>
      <h1 className="text-xl font-semibold tracking-tight">Leave a review</h1>

      {sent ? (
        <div role="status" data-testid="review-sent" className="mt-4 rounded-card border border-line bg-surface p-4 sm:p-5">
          <p className="text-base font-semibold">Thank you. Your review is on its way to Aggrey.</p>
          <p className="mt-1 text-sm text-muted">Every review is read, and it helps decide what gets built next.</p>
          <Link href="/" className="mt-4 inline-block font-medium text-accent-text underline underline-offset-2">
            Back to Matches
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} noValidate className="mt-4 space-y-5 rounded-card border border-line bg-surface p-4 sm:p-5">
          <p className="text-sm text-muted" data-testid="review-notice">
            Your review goes to Aggrey, who runs StEP1, by email, with your email address
            {me ? (
              <>
                {" "}
                (<span className="font-medium text-fg">{me.email}</span>)
              </>
            ) : null}{" "}
            attached so the reply can come straight back to you. It isn&apos;t published anywhere.
          </p>

          <div>
            <p id="rating-label" className="mb-1.5 text-sm font-medium">
              Your rating
            </p>
            <StarRating value={rating} onChange={setRating} labelledBy="rating-label" />
          </div>

          <label className="block">
            <span className="mb-1 block text-sm font-medium">Your review</span>
            <span className="mb-1.5 block text-sm text-muted" id="review-prompt">
              What&apos;s working, what isn&apos;t, what you wish it did.
            </span>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={7}
              aria-describedby="review-prompt review-count"
              aria-invalid={tooLong ? true : undefined}
              className="w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-[15px] placeholder:text-faint"
            />
            <span
              id="review-count"
              data-testid="review-count"
              className={`mt-1 block font-mono text-[13px] ${tooLong ? "text-danger" : "text-faint"}`}
            >
              {length.toLocaleString()} of {MAX.toLocaleString()} characters
              {tooLong ? `. That is ${(length - MAX).toLocaleString()} too many.` : ""}
            </span>
          </label>

          {error && <ErrorNote>{error}</ErrorNote>}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted" data-testid="review-hint">
              {rating === null ? "Choose a rating to send." : length === 0 ? "Write a few words to send." : tooLong ? "Shorten it to send." : ""}
            </p>
            <Button type="submit" variant="primary" disabled={!ready} busy={busy} data-testid="send-review">
              {busy ? "Sending…" : "Send review"}
            </Button>
          </div>
        </form>
      )}
    </AppShell>
  );
}
