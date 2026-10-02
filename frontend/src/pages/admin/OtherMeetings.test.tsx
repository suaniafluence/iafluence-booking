import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type Meeting } from "../../api";
import { deferred } from "../../test/fixtures";
import { OtherMeetings } from "./OtherMeetings";

const meeting = (over: Partial<Meeting> = {}): Meeting => ({
  transcript_id: "ff_ext",
  title: "Point projet - Exemple SAS",
  start: "2026-10-05T10:30:00+02:00",
  end: "2026-10-05T11:15:00+02:00",
  participants: ["claire@exemple.fr", "paul@exemple.fr"],
  suggested_email: "claire@exemple.fr",
  suggested_name: null,
  report_id: null,
  ...over,
});

const meetings = [
  meeting(),
  meeting({ transcript_id: "ff_old", title: null, participants: [], suggested_email: null, report_id: 4 }),
];

beforeEach(() => {
  vi.spyOn(api, "adminMeetings").mockResolvedValue({ meetings });
  vi.spyOn(api, "adminCreateMeetingReport").mockResolvedValue({ report_id: 9, booking_id: 3 });
});

async function openList(onCreated = vi.fn()) {
  const user = userEvent.setup();
  render(<OtherMeetings onCreated={onCreated} />);
  expect(api.adminMeetings).not.toHaveBeenCalled(); // Fireflies quota: on demand only
  await user.click(screen.getByRole("button", { name: "Voir les réunions des 7 derniers jours" }));
  const list = await screen.findByRole("list", { name: "Réunions Fireflies" });
  return { user, list, onCreated };
}

describe("OtherMeetings", () => {
  it("lists the recordings on demand", async () => {
    const { list } = await openList();
    const [ext, old] = within(list).getAllByRole("listitem");
    expect(ext).toHaveTextContent("Point projet - Exemple SAS");
    expect(ext).toHaveTextContent("Lundi 5 octobre 2026 · 10:30 - 11:15");
    expect(ext).toHaveTextContent("claire@exemple.fr, paul@exemple.fr");
    expect(old).toHaveTextContent("Réunion sans titre");
    expect(old).toHaveTextContent("Compte rendu déjà demandé");
    expect(within(old).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Actualiser" })).toBeInTheDocument();
  });

  it("asks for the report of a meeting, for the suggested guest", async () => {
    const { user, list, onCreated } = await openList();
    await user.click(within(list).getByRole("button", { name: "Faire le compte rendu de Point projet - Exemple SAS" }));
    expect(screen.getByLabelText("Email")).toHaveValue("claire@exemple.fr");
    await user.type(screen.getByLabelText("Nom du destinataire"), "Claire Martin");
    await user.selectOptions(screen.getByLabelText("Langue du compte rendu"), "en");
    await user.click(screen.getByRole("button", { name: "Lancer le résumé" }));

    expect(api.adminCreateMeetingReport).toHaveBeenCalledWith({
      transcript_id: "ff_ext",
      title: "Point projet - Exemple SAS",
      start: "2026-10-05T10:30:00+02:00",
      end: "2026-10-05T11:15:00+02:00",
      name: "Claire Martin",
      email: "claire@exemple.fr",
      locale: "en",
    });
    expect(onCreated).toHaveBeenCalledWith(
      "Compte rendu demandé pour Claire Martin : le brouillon Gmail sera prêt dans quelques minutes.",
    );
    expect(within(list).getAllByText("Compte rendu déjà demandé")).toHaveLength(2);
    expect(screen.queryByLabelText("Nom du destinataire")).not.toBeInTheDocument();
  });

  it("prefills a known customer's name", async () => {
    vi.mocked(api.adminMeetings).mockResolvedValue({ meetings: [meeting({ suggested_name: "Claire M." })] });
    const { user, list } = await openList();
    await user.click(within(list).getByRole("button", { name: /Faire le compte rendu/ }));
    expect(screen.getByLabelText("Nom du destinataire")).toHaveValue("Claire M.");
  });

  it("shows why the report could not be asked for, and can be closed", async () => {
    const pending = deferred<{ report_id: number; booking_id: number }>();
    vi.mocked(api.adminCreateMeetingReport).mockReturnValue(pending.promise);
    const { user, list, onCreated } = await openList();
    await user.click(within(list).getByRole("button", { name: /Faire le compte rendu/ }));
    await user.type(screen.getByLabelText("Nom du destinataire"), "Claire");
    await user.click(screen.getByRole("button", { name: "Lancer le résumé" }));
    expect(screen.getByRole("button", { name: "Envoi…" })).toBeDisabled();
    pending.reject(new ApiError(409, "Cette réunion a déjà un compte rendu."));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cette réunion a déjà un compte rendu.");
    expect(onCreated).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(screen.queryByLabelText("Nom du destinataire")).not.toBeInTheDocument();
  });

  it("says when Fireflies does not answer, or has nothing", async () => {
    vi.mocked(api.adminMeetings).mockRejectedValueOnce(new ApiError(502, "Fireflies ne répond pas : quota."));
    const user = userEvent.setup();
    render(<OtherMeetings onCreated={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Voir les réunions des 7 derniers jours" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Fireflies ne répond pas : quota.");

    vi.mocked(api.adminMeetings).mockResolvedValueOnce({ meetings: [] });
    await user.click(screen.getByRole("button", { name: "Voir les réunions des 7 derniers jours" }));
    expect(await screen.findByText("Aucun enregistrement Fireflies ces 7 derniers jours.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the listing in progress", async () => {
    const pending = deferred<{ meetings: Meeting[] }>();
    vi.mocked(api.adminMeetings).mockReturnValue(pending.promise);
    const user = userEvent.setup();
    render(<OtherMeetings onCreated={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Voir les réunions des 7 derniers jours" }));
    expect(screen.getByRole("button", { name: "Chargement…" })).toBeDisabled();
    pending.resolve({ meetings });
    expect(await screen.findByRole("list", { name: "Réunions Fireflies" })).toBeInTheDocument();
  });
});
