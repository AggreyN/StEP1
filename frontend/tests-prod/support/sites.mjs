// The sites the production suite builds and serves, and the stand-in
// sign-in service. One definition, used by the Playwright config, the build
// step and the specs.
export const OIDC = { port: 3400, client: "test-client" };

const cognitoPort = 3300;

export const SITES = {
  // Local sign-in, registration open: what `npm run build` makes by default.
  local: { port: 3200, dir: ".next-export", env: { NEXT_PUBLIC_API_BASE: "mock" } },
  // Local sign-in, registration closed.
  closed: {
    port: 3201,
    dir: ".next-export-closed",
    env: { NEXT_PUBLIC_API_BASE: "mock", NEXT_PUBLIC_REGISTRATION: "closed" },
  },
  // Cognito sign-in, against the stand-in.
  cognito: {
    port: cognitoPort,
    dir: ".next-export-cognito",
    connect: [`http://localhost:${OIDC.port}`],
    env: {
      NEXT_PUBLIC_API_BASE: "mock",
      NEXT_PUBLIC_AUTH_MODE: "cognito",
      NEXT_PUBLIC_COGNITO_DOMAIN: `http://localhost:${OIDC.port}`,
      NEXT_PUBLIC_COGNITO_CLIENT_ID: OIDC.client,
      NEXT_PUBLIC_COGNITO_REDIRECT_URI: `http://localhost:${cognitoPort}/auth/callback`,
      NEXT_PUBLIC_COGNITO_LOGOUT_URI: `http://localhost:${cognitoPort}/login`,
    },
  },
};
