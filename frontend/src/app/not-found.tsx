// The page for an address that has no file. Exported as 404.html, which the
// host serves (with a 404 status) for anything it can't find.
//
// Before saying "not found" it checks whether the address is an older form
// of one that does exist, and goes there instead. That is what keeps
// /applications/12 links working on a host that only serves files.
import type { Metadata } from "next";
import { NotFound } from "@/components/NotFound";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFoundPage() {
  return <NotFound />;
}
