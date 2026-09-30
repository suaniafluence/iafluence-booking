// Shared by playwright.config.ts, the API launcher and the specs.
import { tmpdir } from "node:os";

export const API_PORT = Number(process.env.E2E_API_PORT ?? 8001);
export const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5174);
export const DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? "postgresql+psycopg://postgres:dev@127.0.0.1:5433/iafluence_e2e";
export const ADMIN_PASSWORD = "e2e-admin-password";
// Demo emails are also written here as .eml files (DEMO_OUTBOX_DIR), wiped at start.
export const OUTBOX_DIR = process.env.E2E_OUTBOX_DIR ?? `${tmpdir()}/iafluence-e2e-outbox`;
