// Starts the real FastAPI backend for the E2E suite, on a freshly migrated database.
// Google, Stripe, Gmail, Fireflies and Codex are replaced by the in-memory demo fakes (FAKE_INTEGRATIONS=true).
// The end-of-session and session report jobs run every second; emails are also saved in OUTBOX_DIR.
//
// Env: E2E_DATABASE_URL (PostgreSQL, wiped at start), E2E_API_PORT, E2E_OUTBOX_DIR, UV (path to uv, default "uv").
import { execFileSync, spawn } from "node:child_process";
import { rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { ADMIN_PASSWORD, API_PORT, DATABASE_URL, OUTBOX_DIR } from "./env.mjs";

const backend = fileURLToPath(new URL("../../backend/", import.meta.url));
const uv = process.env.UV ?? "uv";

const env = {
  ...process.env,
  DATABASE_URL,
  FAKE_INTEGRATIONS: "true",
  PUBLIC_BASE_URL: "http://127.0.0.1:5174",
  SESSION_SECRET: "e2e-secret",
  COOKIE_SECURE: "false",
  FOLLOW_UP_POLL_SECONDS: "1",
  FIREFLIES_POLL_SECONDS: "1",
  DEMO_OUTBOX_DIR: OUTBOX_DIR,
  PYTHONUTF8: "1",
};

rmSync(OUTBOX_DIR, { recursive: true, force: true });

const run = (...args) => execFileSync(uv, ["run", ...args], { cwd: backend, env, stdio: ["ignore", "pipe", "inherit"] });

run("alembic", "downgrade", "base");
run("alembic", "upgrade", "head");
run("python", "-m", "scripts.seed_settings", "--admin-email", "admin@iafluence.test", "--booking-calendar", "demo");
env.ADMIN_PASSWORD_HASH = run(
  "python",
  "-c",
  `from argon2 import PasswordHasher; print(PasswordHasher().hash(${JSON.stringify(ADMIN_PASSWORD)}))`,
)
  .toString()
  .trim();

const api = spawn(uv, ["run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(API_PORT)], {
  cwd: backend,
  env,
  stdio: "inherit",
});
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => api.kill(sig));
api.on("exit", (code) => process.exit(code ?? 0));
