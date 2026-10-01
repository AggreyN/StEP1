"""How much of anything a client may send.

Types are not bounds. Pydantic will happily accept a list of ten thousand
preferred locations, each a megabyte long, because each one is a string. These
numbers are what turns "valid" into "reasonable", and they live in one file so
that the API, its tests and the README cannot drift apart.

They are constants, not settings: a bound that an operator can raise by
accident is not a bound.
"""

# --- Account ---
# RFC 5321's limit on a whole address; nothing longer can be delivered to.
EMAIL_MAX = 254
# bcrypt reads the first 72 bytes and ignores the rest, so nothing past that
# adds strength. 128 leaves room for a long passphrase in any script without
# letting someone make us hash a megabyte per login attempt.
PASSWORD_MAX = 128
DISPLAY_NAME_MAX = 80

# --- Profile ---
SCHOOL_MAX = MAJOR_MAX = MINOR_MAX = 120
DEGREE_LEVEL_MAX = 40
# 5.0, not 4.0: some schools grade on a 4.3 or 5.0 scale, and weighted GPAs
# exceed 4. It does not affect matching either way (architecture §4).
GPA_MAX = 5
LOCATIONS_MAX = 20
LOCATION_CHARS_MAX = 100
# The known terms are a season and a year. Eight covers two full years.
TERMS_MAX = 8
# How far either side of this year a target term may be. Behind us only to
# tolerate a term that is ending; ahead as far as anyone recruits.
TERM_YEARS_BEHIND = 1
TERM_YEARS_AHEAD = 6
INTERESTS_MIN, INTERESTS_MAX = 3, 5
SKILLS_MAX = 100
SKILL_CHARS_MAX = 50

# --- Resume ---
FILENAME_MAX = 255
# Any PDF with a page in it is larger than this; smaller is an empty or
# truncated file. The checklist suggested 25 KB, but a plain one-page résumé
# exported as text is often 5-20 KB, and refusing those would be refusing the
# best-formed résumés anyone uploads.
RESUME_MIN_BYTES = 1024
STORAGE_KEY_MAX = 200

# --- Applications ---
NOTE_MAX = 2000
REVIEW_BODY_MAX = 2000
EVENT_KIND_MAX = 40
# "{source}:{source_id}" — 32 + 1 + 128 in the schema.
POSTING_ID_MAX = 170

# --- Feed filters ---
FILTER_LOCATION_MAX = 100
FILTER_TERM_MAX = 40
FILTER_ROLES_MAX = 15

# --- Whole request ---
# The largest legitimate JSON body is a profile with every list full, about
# 10 KB. Anything near this is not a form submission. File uploads have their
# own cap and do not pass through JSON.
JSON_BODY_MAX_BYTES = 64 * 1024

# How much of a rejected value is quoted back in an error message.
ECHO_MAX = 40


def echo(value: object) -> str:
    """A rejected value, shortened, for an error message. Without the cap an
    error would repeat back whatever it was sent, at whatever size."""
    shown = str(value)
    return shown if len(shown) <= ECHO_MAX else shown[:ECHO_MAX] + "…"


# --- Resumes as documents (ResumeDoc, BaseResume) ---
RESUME_NAME_MAX = 120  # the person's name at the top
RESUME_CONTACT_MAX = 8  # contact items
RESUME_CONTACT_CHARS_MAX = 200
RESUME_SECTIONS_MAX = 12
RESUME_TITLE_MAX = 80  # a section title
RESUME_ENTRIES_MAX = 20  # per section
RESUME_FIELD_MAX = 200  # heading, right, sub, sub_right
RESUME_LINES_MAX = 12  # per entry
RESUME_LINE_MAX = 300  # characters in one line
RESUME_INVENTORY_MAX = 200  # skill_inventory items
RESUME_INVENTORY_CHARS_MAX = 80
SAVED_RESUME_NAME_MAX = 80
SAVED_RESUMES_MAX = 100  # per person
JOB_TEXT_MAX = 20_000
