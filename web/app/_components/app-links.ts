// Where the Elmify app (the Django dashboard) lives. The landing page is a
// separate site, so every "sign up", "log in" and "book a demo" goes there.
// Set NEXT_PUBLIC_APP_URL to the app's address when deploying (for example
// https://app.elmify.com); locally the app runs on port 8000.
const APP_URL = (process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://elmify.com").replace(/\/$/, "");

export const appLinks = {
  signup: `${APP_URL}/signup/`,
  login: `${APP_URL}/accounts/login/`,
  demo: `${APP_URL}/demo/`,
  studentDemo: `${APP_URL}/demo/?audience=student`,
  agencyDemo: `${APP_URL}/demo/?audience=agency`,
  terms: `${APP_URL}/legal/terms/`,
  privacy: `${APP_URL}/legal/privacy_notice_direct/`,
};
