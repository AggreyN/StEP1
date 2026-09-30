// The footer on every screen: where the listings come from, and the two
// public pages. Signed-in screens also get a link to leave a review. No
// hooks, so public pages can render it on the server.
import Link from "next/link";
import { SOURCES } from "@/lib/site";

const link = "underline underline-offset-2 hover:text-muted";

export function SiteFooter({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <footer className="font-ui mt-auto border-t border-line px-4 py-5 text-center text-xs leading-5 text-faint">
      <p>
        Listings from{" "}
        <a className={link} href={SOURCES[0].url} target="_blank" rel="noreferrer">
          {SOURCES[0].name}
        </a>{" "}
        and{" "}
        <a className={link} href={SOURCES[1].url} target="_blank" rel="noreferrer">
          {SOURCES[1].name}
        </a>
        . Every listing links out to the original posting. StEP1 doesn&apos;t own or host them.
      </p>
      <nav aria-label="Site" className="mt-1.5 flex justify-center gap-4">
        <Link className={link} href="/about">
          About
        </Link>
        <Link className={link} href="/privacy">
          Privacy
        </Link>
        {signedIn && (
          <Link className={link} href="/review">
            Leave a review
          </Link>
        )}
      </nav>
    </footer>
  );
}
