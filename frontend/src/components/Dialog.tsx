"use client";
// Native <dialog> (focus trap, Esc, backdrop for free). `sheet` renders as a
// bottom sheet — used for the mobile filter panel.
import { useEffect, useRef, type ReactNode } from "react";
import { XIcon } from "./icons";

export function Dialog({
  open,
  onClose,
  title,
  children,
  sheet = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  sheet?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  const pos = sheet
    ? "mt-auto mb-0 w-full max-w-none rounded-t-card max-h-[85vh]"
    : "m-auto w-[calc(100%-2rem)] max-w-md rounded-card max-h-[90vh]";

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // backdrop click
      }}
      aria-label={title}
      className={`${pos} overflow-hidden border border-line bg-surface p-0 text-fg`}
    >
      {open && (
        <div className="flex max-h-[inherit] flex-col">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="text-base font-semibold">{title}</h2>
            <button
              onClick={onClose}
              aria-label="Close"
              className="-mr-2 inline-flex h-9 w-9 items-center justify-center rounded-control text-muted hover:bg-surface-2 hover:text-fg"
            >
              <XIcon />
            </button>
          </div>
          <div className="overflow-y-auto p-4">{children}</div>
        </div>
      )}
    </dialog>
  );
}
