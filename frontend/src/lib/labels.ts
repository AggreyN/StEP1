// Display vocabulary only. This file maps API identifiers to human labels and
// fixes the order groups are listed in. It intentionally says nothing about
// which state may follow which — the backend owns that graph and sends the
// legal moves as `next_transitions`.

export const TERMS = ["Summer 2027", "Fall 2027", "Winter 2027", "Spring 2027", "Summer 2028"];

export const DEGREE_LEVELS = ["Associate's", "Bachelor's", "Master's", "PhD"];

export const DEFAULT_SCHOOL = "University of Maryland, College Park";

/** Status + event-kind labels. Key order = display order for grouped lists. */
export const KIND_LABELS: Record<string, string> = {
  saved: "Saved",
  applied: "Applied",
  acknowledged: "Acknowledged",
  oa_sent: "Online assessment sent",
  oa_completed: "Online assessment completed",
  interview_scheduled: "Interview scheduled",
  interviewed: "Interviewed",
  additional_round: "Additional round",
  offer: "Offer",
  accepted: "Accepted",
  ghosted: "Ghosted",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  note: "Note",
  outreach_sent: "Outreach sent",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** Visual tone per status — purely cosmetic. */
export type Tone = "accent" | "neutral" | "quiet" | "negative" | "positive";

export function statusTone(status: string): Tone {
  switch (status) {
    case "offer":
    case "accepted":
      return "positive";
    case "rejected":
      return "negative";
    case "ghosted":
    case "withdrawn":
      return "quiet";
    default:
      return "neutral";
  }
}
