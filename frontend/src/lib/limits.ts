// The server's input bounds, mirrored so the form can say what is wrong
// before a request is made. The server still enforces them; if these drift,
// its 422 message is shown as-is.

export const LIMITS = {
  school: 120,
  major: 120,
  minor: 120,
  displayName: 80,
  locations: 20,
  locationLength: 100,
  note: 2000,
  resumeMinBytes: 1024, // 1 KB
  resumeMaxBytes: 5 * 1024 * 1024, // 5 MB
};

/** "Major can be at most 120 characters (you have 131)." or null if fine. */
export function tooLong(label: string, value: string, max: number): string | null {
  const n = value.trim().length;
  return n > max ? `${label} can be at most ${max} characters (you have ${n}).` : null;
}
