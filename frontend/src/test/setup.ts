import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// jsdom says "en-US": pages without a language prefix would be in English. Tests opt in to other languages.
beforeEach(() => {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR", "fr"]);
});

afterEach(cleanup);
