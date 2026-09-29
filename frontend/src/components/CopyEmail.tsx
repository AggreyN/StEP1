"use client";
import { useState } from "react";
import { CONTACT_EMAIL } from "@/lib/site";

export function CopyEmail() {
  const [copied, setCopied] = useState(false);

  async function copyEmail() {
    try {
      await navigator.clipboard.writeText(CONTACT_EMAIL);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard can be refused (http, older browsers, permissions).
      // The address is rendered as select-all text, so this degrades fine.
      setCopied(false);
    }
  }

  return (
    <>
      <code className="select-all break-all rounded-[3px] border border-[var(--line)] bg-[var(--paper)] px-[10px] py-[7px] font-mono text-[0.88rem] text-[var(--ink)]">
        {CONTACT_EMAIL}
      </code>
      <button
        type="button"
        onClick={copyEmail}
        className="font-ui min-h-9 cursor-pointer rounded-[4px] border border-[var(--line-2)] bg-transparent px-[14px] py-[9px] text-[0.82rem] font-medium text-[var(--ink-2)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? "Email address copied" : ""}
      </span>
    </>
  );
}
