// Settings that are fixed when the site is built. Next replaces each
// `process.env.NEXT_PUBLIC_*` below with its value at build time, so the
// exported files carry them; nothing is read at run time.

/** How people sign in.
 *   local    email and password, checked by the StEP1 API (the default)
 *   cognito  Amazon Cognito's managed login; this site never sees a password */
export const AUTH_MODE: "local" | "cognito" =
  process.env.NEXT_PUBLIC_AUTH_MODE === "cognito" ? "cognito" : "local";

/** Local mode only: whether the sign-in page offers to create an account.
 *  "closed" hides it; the API's own registration is expected to be off too. */
export const REGISTRATION_OPEN = process.env.NEXT_PUBLIC_REGISTRATION !== "closed";

const trim = (v: string | undefined) => (v ?? "").replace(/\/+$/, "");

export const COGNITO = {
  /** The user pool's domain, e.g. https://<prefix>.auth.<region>.amazoncognito.com */
  domain: trim(process.env.NEXT_PUBLIC_COGNITO_DOMAIN),
  /** The app client. It is a public client: there is no client secret. */
  clientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "",
  /** Where Cognito sends the browser after sign-in: <site>/auth/callback.
   *  Must match an allowed callback URL of the app client exactly. */
  redirectUri: process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI ?? "",
  /** Where Cognito sends the browser after sign-out. Must match an allowed
   *  sign-out URL of the app client exactly. */
  logoutUri: process.env.NEXT_PUBLIC_COGNITO_LOGOUT_URI ?? "",
  /** openid is needed for an ID token; email and profile put the address and
   *  the name in it. */
  scope: "openid email profile",
};

/**
 * WHICH TOKEN GOES TO THE API
 *
 * Cognito issues two signed tokens at sign-in. StEP1 sends the **ID token**
 * as the bearer token on every API request.
 *
 *   - Its `aud` claim is the app client id and its `token_use` is "id",
 *     which is what the API checks.
 *   - It carries `email` and `name`. The API creates the user's row from
 *     those on first sight. The access token carries neither, so the API
 *     would have to call Cognito again for every new user.
 *
 * The access token is not sent anywhere and is not kept.
 */
export const API_TOKEN_USE = "id";
