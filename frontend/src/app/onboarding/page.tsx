"use client";
// One sectioned page, not a wizard: six fields, a file, and the ranked
// interests that drive the score.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { getProfile, putProfile, uploadResume, validateResume } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { DEFAULT_SCHOOL, DEGREE_LEVELS, TERMS } from "@/lib/labels";
import { LIMITS, tooLong } from "@/lib/limits";
import type { Profile, Resume } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { ChipInput } from "@/components/ChipInput";
import { DeleteAccount } from "@/components/DeleteAccount";
import { InterestRanker, MAX_INTERESTS, MIN_INTERESTS } from "@/components/InterestRanker";
import { Button, Chip, ErrorNote, Spinner } from "@/components/ui";
import { CheckIcon, XIcon } from "@/components/icons";

const input =
  "h-11 w-full rounded-control border border-line-strong bg-surface px-3 text-[15px] text-fg placeholder:text-faint focus:border-accent focus:outline-none";

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border border-line bg-surface p-3.5 sm:p-5">
      <h2 className="text-base font-semibold">{title}</h2>
      {hint && <p className="mt-0.5 text-sm text-muted">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Field({
  label,
  optional,
  error,
  children,
}: {
  label: string;
  optional?: boolean;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">
        {label} {optional && <span className="font-normal text-faint">(optional)</span>}
      </span>
      {children}
      {error && (
        <span role="alert" className="mt-1 block text-sm text-danger">
          {error}
        </span>
      )}
    </label>
  );
}

const thisYear = new Date().getFullYear();

export default function OnboardingPage() {
  const authed = useRequireAuth();
  const router = useRouter();

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [existing, setExisting] = useState<Profile | null>(null);

  const [school, setSchool] = useState(DEFAULT_SCHOOL);
  const [major, setMajor] = useState("");
  const [minor, setMinor] = useState("");
  const [degree, setDegree] = useState("Bachelor's");
  const [gradYear, setGradYear] = useState(String(thisYear + 2));
  const [terms, setTerms] = useState<string[]>(["Summer 2027"]);
  const [locations, setLocations] = useState<string[]>([]);
  const [remoteOk, setRemoteOk] = useState(true);
  const [interests, setInterests] = useState<string[]>([]);
  const [resume, setResume] = useState<Resume | null>(null);
  const [skills, setSkills] = useState<string[]>([]);

  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    getProfile()
      .then((p) => {
        if (cancelled) return;
        setExisting(p);
        if (p) {
          setSchool(p.school ?? DEFAULT_SCHOOL);
          setMajor(p.major ?? "");
          setMinor(p.minor ?? "");
          if (p.degree_level) setDegree(p.degree_level);
          if (p.grad_year) setGradYear(String(p.grad_year));
          setTerms(p.target_terms);
          setLocations(p.preferred_locations);
          setRemoteOk(p.remote_ok);
          setInterests([...p.interests].sort((a, b) => a.rank - b.rank).map((i) => i.role));
          setResume(p.resume);
          setSkills(p.resume?.skills ?? []);
        }
      })
      .catch((e: Error) => !cancelled && setLoadError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [authed]);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setUploadError(null);
    const err = validateResume(file);
    if (err) {
      setUploadError(err);
      return;
    }
    setUploading(true);
    try {
      const r = await uploadResume(file);
      setResume(r);
      setSkills(r.skills);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const interestsOk = interests.length >= MIN_INTERESTS && interests.length <= MAX_INTERESTS;
  const gradYearNum = Number(gradYear);
  const schoolError = tooLong("School", school, LIMITS.school);
  const majorError = tooLong("Major", major, LIMITS.major);
  const minorError = tooLong("Minor", minor, LIMITS.minor);
  const formOk =
    interestsOk &&
    school.trim() &&
    major.trim() &&
    terms.length > 0 &&
    Number.isInteger(gradYearNum) &&
    gradYearNum >= thisYear - 1 &&
    gradYearNum <= thisYear + 8 &&
    !schoolError &&
    !majorError &&
    !minorError;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!formOk) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await putProfile({
        school: school.trim(),
        major: major.trim(),
        minor: minor.trim() || null,
        degree_level: degree,
        grad_year: gradYearNum,
        target_terms: terms,
        preferred_locations: locations,
        remote_ok: remoteOk,
        interests: interests.map((role, i) => ({ role, rank: i + 1 })),
        ...(resume ? { skills } : {}),
      });
      router.push(`/onboarding/building?retry=${res.retryAfter}`);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Couldn't save your profile.");
      setSaving(false);
    }
  }

  if (!authed) return null;

  return (
    <AppShell>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight">{existing ? "Your profile" : "Tell us what you're looking for"}</h1>
        <p className="mt-1 text-sm text-muted">
          {existing
            ? "Changes re-rank your matches. Your ranked fields matter most."
            : "A few fields and a resume. Your ranked fields matter most: they drive the score on every posting."}
        </p>
      </div>

      {loading ? (
        <Spinner label="Loading your profile" />
      ) : loadError ? (
        <ErrorNote onRetry={() => location.reload()}>{loadError}</ErrorNote>
      ) : (
        <>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Section title="Fields of interest" hint={`Pick ${MIN_INTERESTS}–${MAX_INTERESTS} and put your top choice first. #1 scores highest.`}>
            <InterestRanker value={interests} onChange={setInterests} />
          </Section>

          <Section title="School">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Field label="School" error={schoolError}>
                  <input className={input} value={school} onChange={(e) => setSchool(e.target.value)} required />
                </Field>
              </div>
              <Field label="Major" error={majorError}>
                <input className={input} value={major} onChange={(e) => setMajor(e.target.value)} required placeholder="Information Science" />
              </Field>
              <Field label="Minor" optional error={minorError}>
                <input className={input} value={minor} onChange={(e) => setMinor(e.target.value)} />
              </Field>
              <Field label="Degree level">
                <select className={input} value={degree} onChange={(e) => setDegree(e.target.value)}>
                  {DEGREE_LEVELS.map((d) => (
                    <option key={d}>{d}</option>
                  ))}
                </select>
              </Field>
              <Field label="Expected graduation year">
                <input
                  className={`${input} font-mono`}
                  inputMode="numeric"
                  value={gradYear}
                  onChange={(e) => setGradYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
                  required
                />
              </Field>
            </div>
          </Section>

          <Section title="When and where" hint="Terms you can intern, places you'd go.">
            <p className="mb-2 text-sm font-medium">Target terms</p>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Target terms">
              {TERMS.map((t) => {
                const on = terms.includes(t);
                return (
                  <button
                    type="button"
                    key={t}
                    aria-pressed={on}
                    onClick={() => setTerms(on ? terms.filter((x) => x !== t) : [...terms, t])}
                    className={`inline-flex h-10 items-center gap-1.5 rounded-control border px-3.5 text-sm ${
                      on ? "border-accent bg-accent-soft text-accent-text font-medium" : "border-line-strong bg-surface text-fg"
                    }`}
                  >
                    {on && <CheckIcon />}
                    {t}
                  </button>
                );
              })}
            </div>
            {terms.length === 0 && <p className="mt-2 text-sm text-danger">Pick at least one term.</p>}

            <p className="mb-2 mt-5 text-sm font-medium">Preferred locations</p>
            <ChipInput
              label="Preferred locations"
              value={locations}
              onChange={setLocations}
              placeholder="Washington, DC"
              max={LIMITS.locations}
              maxLength={LIMITS.locationLength}
            />
            <label className="mt-4 flex cursor-pointer items-center gap-3">
              <input type="checkbox" checked={remoteOk} onChange={(e) => setRemoteOk(e.target.checked)} className="h-5 w-5 accent-[var(--accent)]" />
              <span className="text-[15px]">Remote is fine</span>
            </label>
          </Section>

          <Section title="Resume" hint="PDF, 1 KB to 5 MB. Your skills are read from it to match against postings.">
            <div className="flex flex-wrap items-center gap-3">
              <input
                ref={fileRef}
                type="file"
                accept="application/pdf,.pdf"
                className="sr-only"
                id="resume-file"
                onChange={(e) => onFile(e.target.files?.[0])}
                disabled={uploading}
              />
              <label
                htmlFor="resume-file"
                className={`inline-flex h-11 cursor-pointer items-center rounded-control border border-line-strong bg-surface px-4 text-sm font-medium hover:bg-surface-2 ${uploading ? "pointer-events-none opacity-45" : ""}`}
              >
                {resume ? "Replace PDF" : "Upload PDF"}
              </label>
              {uploading && <Spinner label="Uploading and reading…" />}
              {!uploading && resume && (
                <span className="text-sm text-muted">
                  <span className="font-medium text-fg">{resume.filename}</span> · uploaded{" "}
                  {new Date(resume.uploaded_at).toLocaleDateString()}
                </span>
              )}
            </div>
            {uploadError && <div className="mt-3"><ErrorNote>{uploadError}</ErrorNote></div>}
            {resume?.needs_ocr && (
              <p className="mt-3 rounded-control bg-surface-2 px-3 py-2 text-sm text-muted" role="status">
                This PDF looks image-only, so we couldn&apos;t extract skills from it. Try exporting a text PDF from your
                editor, or add skills below by hand.
              </p>
            )}
            {resume && (
              <div className="mt-4">
                <p className="mb-2 text-sm font-medium">
                  Skills we found <span className="font-normal text-faint">(remove any that are wrong)</span>
                </p>
                {skills.length ? (
                  <ul className="flex flex-wrap gap-2" aria-label="Extracted skills">
                    {skills.map((s) => (
                      <li key={s}>
                        <Chip tone="strong" className="!py-0 !pr-0">
                          {s}
                          <button
                            type="button"
                            onClick={() => setSkills(skills.filter((x) => x !== s))}
                            aria-label={`Remove skill ${s}`}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-chip text-muted hover:text-fg"
                          >
                            <XIcon />
                          </button>
                        </Chip>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-faint">No skills listed.</p>
                )}
              </div>
            )}
          </Section>

          {saveError && <ErrorNote>{saveError}</ErrorNote>}

          <div className="pt-1">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted" data-testid="submit-hint">
                {!interestsOk
                  ? `Pick ${MIN_INTERESTS}–${MAX_INTERESTS} fields to continue.`
                  : !formOk
                    ? (schoolError ?? majorError ?? minorError ?? "Fill in your major, a term, and a valid graduation year.")
                    : existing
                      ? "We'll re-rank your matches."
                      : "We'll rank every open internship for you."}
              </p>
              <Button type="submit" variant="primary" disabled={!formOk || saving} data-testid="submit-profile">
                {saving ? "Saving…" : existing ? "Save and re-rank" : "Find my matches"}
              </Button>
            </div>
          </div>
        </form>
        <div className="mt-10">
          <DeleteAccount />
        </div>
        </>
      )}
    </AppShell>
  );
}
