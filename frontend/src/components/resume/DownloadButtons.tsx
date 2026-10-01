"use client";
// Download PDF and Download DOCX. `prepare` returns the saved resume's id,
// saving first if there are unsaved changes, so what downloads is always
// what is on screen.
import { useState } from "react";
import { downloadResume, saveFile, type ResumeFormat } from "@/lib/api";
import { Button, ErrorNote } from "../ui";

export function DownloadButtons({
  prepare,
  name,
  disabled = false,
}: {
  prepare: () => Promise<number | null>;
  name: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState<ResumeFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function get(format: ResumeFormat) {
    setBusy(format);
    setError(null);
    try {
      const id = await prepare();
      if (id === null) return;
      const { blob, filename } = await downloadResume(id, format, name);
      saveFile(blob, filename);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make the file.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {(["pdf", "docx"] as const).map((f) => (
          <Button
            key={f}
            size="sm"
            onClick={() => get(f)}
            busy={busy === f}
            disabled={disabled || (busy !== null && busy !== f)}
            data-testid={`download-${f}`}
          >
            {busy === f ? "Preparing…" : `Download ${f.toUpperCase()}`}
          </Button>
        ))}
      </div>
      {error && (
        <div className="mt-2">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}
    </div>
  );
}
