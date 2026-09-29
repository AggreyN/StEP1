// Run before a build that is going to be deployed. It refuses to build a
// site that would not work, or would quietly be the wrong site.
//
//   npm run check:deploy
//
// The settings are read at build time and baked into the files, so a
// mistake here can't be corrected after the build. The most important
// check: without NEXT_PUBLIC_API_BASE the app falls back to its in-browser
// mock, and a deployed site would show made-up data.
const env = process.env;
const problems = [];

function url(name, { https = true, required = true } = {}) {
  const value = env[name];
  if (!value) {
    if (required) problems.push(`${name} is not set.`);
    return null;
  }
  let u;
  try {
    u = new URL(value);
  } catch {
    problems.push(`${name} is not a URL: ${value}`);
    return null;
  }
  const local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
  if (https && u.protocol !== "https:" && !local) problems.push(`${name} must start with https:// (${value}).`);
  return u;
}

if (!env.NEXT_PUBLIC_API_BASE || env.NEXT_PUBLIC_API_BASE === "mock") {
  problems.push("NEXT_PUBLIC_API_BASE is not set to the API's address. The site would run on made-up data.");
} else {
  const api = url("NEXT_PUBLIC_API_BASE");
  if (api && api.pathname !== "/" && api.pathname !== "") {
    problems.push(`NEXT_PUBLIC_API_BASE should be the API's origin, with no path (${env.NEXT_PUBLIC_API_BASE}).`);
  }
}
url("NEXT_PUBLIC_UPLOAD_ORIGIN", { required: false });

const mode = env.NEXT_PUBLIC_AUTH_MODE || "local";
if (mode !== "local" && mode !== "cognito") {
  problems.push(`NEXT_PUBLIC_AUTH_MODE must be "local" or "cognito" (${mode}).`);
}
if (mode === "cognito") {
  url("NEXT_PUBLIC_COGNITO_DOMAIN");
  if (!env.NEXT_PUBLIC_COGNITO_CLIENT_ID) problems.push("NEXT_PUBLIC_COGNITO_CLIENT_ID is not set.");
  const redirect = url("NEXT_PUBLIC_COGNITO_REDIRECT_URI");
  if (redirect && redirect.pathname !== "/auth/callback") {
    problems.push(
      `NEXT_PUBLIC_COGNITO_REDIRECT_URI must end in /auth/callback, with no trailing slash (${env.NEXT_PUBLIC_COGNITO_REDIRECT_URI}).`
    );
  }
  if (redirect && (redirect.search || redirect.hash)) {
    problems.push("NEXT_PUBLIC_COGNITO_REDIRECT_URI must not have a query string or a fragment.");
  }
  url("NEXT_PUBLIC_COGNITO_LOGOUT_URI");
}
const registration = env.NEXT_PUBLIC_REGISTRATION || "open";
if (registration !== "open" && registration !== "closed") {
  problems.push(`NEXT_PUBLIC_REGISTRATION must be "open" or "closed" (${registration}).`);
}
if (mode === "local" && registration === "open") {
  console.warn(
    "check-deploy-env: warning: local sign-in with open registration. Anyone who finds the site can make an account."
  );
}

if (problems.length) {
  console.error("check-deploy-env: this build is not ready to deploy:\n" + problems.map((p) => `  - ${p}`).join("\n"));
  process.exit(1);
}
console.log(`check-deploy-env: ok (API ${new URL(env.NEXT_PUBLIC_API_BASE).origin}, sign-in: ${mode}).`);
