"use client";
// Who is signed in, as the API sees it (GET /me). Fetched once per session
// and shared, so the nav, the Profile page and /admin don't each ask.
import { useEffect, useState } from "react";
import { getMe } from "./api";
import { getToken, useAuthState } from "./auth";
import type { Me } from "./types";

let cached: { token: string; me: Promise<Me> } | null = null;

export function loadMe(): Promise<Me> {
  const token = getToken() ?? "";
  if (!cached || cached.token !== token) {
    const me = getMe();
    cached = { token, me };
    // A failed answer is not kept: the next caller asks again.
    me.catch(() => {
      if (cached?.me === me) cached = null;
    });
  }
  return cached.me;
}

/** The signed-in person, or null while it loads (or if it can't be loaded). */
export function useMe(): Me | null {
  const auth = useAuthState();
  const [me, setMe] = useState<{ token: string; me: Me } | null>(null);
  useEffect(() => {
    if (auth !== "in") return;
    let cancelled = false;
    const token = getToken() ?? "";
    loadMe()
      .then((m) => !cancelled && setMe({ token, me: m }))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [auth]);
  return auth === "in" && me && me.token === getToken() ? me.me : null;
}
