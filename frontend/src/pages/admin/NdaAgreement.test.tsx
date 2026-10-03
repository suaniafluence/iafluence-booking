import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type NdaOverview } from "../../api";
import { NdaAgreement } from "./NdaAgreement";

const FR = { locale: "fr", filename: "NDA-IAfluence.pdf", size: 1234, uploaded_at: "2026-10-05T08:00:00+02:00" };
const CLAIRE = {
  customer_id: 7,
  name: "Claire Durand",
  email: "claire@example.com",
  sent_at: "2026-10-05T08:00:00+02:00",
  signed_at: null,
};
const overview = (over: Partial<NdaOverview> = {}): NdaOverview => ({ documents: [FR], customers: [CLAIRE], ...over });

beforeEach(() => {
  vi.spyOn(api, "adminNda").mockResolvedValue(overview());
});

const row = (label: string) => screen.getByText(label, { selector: "div" }).closest("li")!;

describe("NdaAgreement", () => {
  it("lists the PDF of each language and who received the agreement", async () => {
    render(<NdaAgreement />);
    expect(screen.getByRole("heading", { name: "Accord de confidentialité (NDA)" })).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "NDA-IAfluence.pdf" });
    expect(link).toHaveAttribute("href", "/api/consultant/nda/documents/fr.pdf");
    expect(within(row("English")).getByText("Aucun PDF : le français est envoyé.")).toBeInTheDocument();
    expect(within(row("Français")).getByText("Remplacer")).toBeInTheDocument();
    expect(within(row("English")).getByText("Téléverser le PDF")).toBeInTheDocument();

    expect(screen.getByText("claire@example.com")).toBeInTheDocument();
    expect(screen.getByText("05/10/2026")).toBeInTheDocument();
    expect(screen.getByText("En attente du retour")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "NDA signé reçu de Claire Durand" })).not.toBeChecked();
  });

  it("says the box is not offered without the French PDF, and blocks sending", async () => {
    vi.mocked(api.adminNda).mockResolvedValue(overview({ documents: [], customers: [] }));
    render(<NdaAgreement />);
    expect(await screen.findByText("Aucun PDF : la case n’est pas proposée.")).toBeInTheDocument();
    expect(screen.getByText("Aucun NDA envoyé pour le moment.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Envoyer le NDA" })).toBeDisabled();
  });

  it("uploads a PDF for a language, then reloads", async () => {
    vi.spyOn(api, "adminNdaUpload").mockResolvedValue({ locale: "en", filename: "NDA-EN.pdf", size: 10 });
    const user = userEvent.setup();
    render(<NdaAgreement />);
    await screen.findByRole("link", { name: "NDA-IAfluence.pdf" });
    const file = new File(["%PDF-1.7"], "NDA-EN.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("PDF du NDA en English"), file);
    expect(api.adminNdaUpload).toHaveBeenCalledWith("en", file);
    expect(await screen.findByRole("alert")).toHaveTextContent("NDA (English) enregistré.");
    expect(api.adminNda).toHaveBeenCalledTimes(2);
  });

  it("shows why an upload was refused", async () => {
    vi.spyOn(api, "adminNdaUpload").mockRejectedValue(new ApiError(422, "Ce fichier n'est pas un PDF."));
    const user = userEvent.setup({ applyAccept: false });
    render(<NdaAgreement />);
    await screen.findByRole("link", { name: "NDA-IAfluence.pdf" });
    await user.upload(screen.getByLabelText("PDF du NDA en Français"), new File(["x"], "a.txt"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ce fichier n'est pas un PDF.");
  });

  it("deletes the PDF of a language", async () => {
    vi.spyOn(api, "adminNdaDelete").mockResolvedValue({ status: "deleted" });
    const user = userEvent.setup();
    render(<NdaAgreement />);
    await screen.findByRole("link", { name: "NDA-IAfluence.pdf" });
    await user.click(within(row("Français")).getByRole("button", { name: "Supprimer" }));
    expect(api.adminNdaDelete).toHaveBeenCalledWith("fr");
    expect(await screen.findByRole("alert")).toHaveTextContent("NDA (Français) supprimé.");
  });

  it("sends the agreement to a contact in their language, then clears the form", async () => {
    vi.spyOn(api, "adminNdaSend").mockResolvedValue({ customer_id: 9, sent_at: "2026-10-05T08:00:00+02:00" });
    const user = userEvent.setup();
    render(<NdaAgreement />);
    await screen.findByRole("link", { name: "NDA-IAfluence.pdf" });
    await user.type(screen.getByLabelText("Nom du destinataire"), "Paul");
    await user.type(screen.getByLabelText("Email du destinataire"), "paul@example.com");
    await user.selectOptions(screen.getByLabelText("Langue de l’email"), "es");
    await user.click(screen.getByRole("button", { name: "Envoyer le NDA" }));
    expect(api.adminNdaSend).toHaveBeenCalledWith({ name: "Paul", email: "paul@example.com", locale: "es" });
    expect(await screen.findByRole("alert")).toHaveTextContent("NDA envoyé à paul@example.com.");
    expect(screen.getByLabelText("Nom du destinataire")).toHaveValue("");
  });

  it("keeps the form when Gmail refuses the email", async () => {
    vi.spyOn(api, "adminNdaSend").mockRejectedValue(new ApiError(502, "Gmail a refusé l'email du NDA."));
    const user = userEvent.setup();
    render(<NdaAgreement />);
    await screen.findByRole("link", { name: "NDA-IAfluence.pdf" });
    await user.type(screen.getByLabelText("Nom du destinataire"), "Paul");
    await user.type(screen.getByLabelText("Email du destinataire"), "paul@example.com");
    await user.click(screen.getByRole("button", { name: "Envoyer le NDA" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Gmail a refusé l'email du NDA.");
    expect(screen.getByLabelText("Nom du destinataire")).toHaveValue("Paul");
  });

  it("ticks and unticks « Signé reçu »", async () => {
    vi.spyOn(api, "adminNdaSigned").mockResolvedValue({ customer_id: 7, signed_at: "2026-10-06T10:00:00+02:00" });
    const user = userEvent.setup();
    render(<NdaAgreement />);
    await user.click(await screen.findByRole("checkbox", { name: "NDA signé reçu de Claire Durand" }));
    expect(api.adminNdaSigned).toHaveBeenCalledWith(7, true);
    expect(await screen.findByRole("alert")).toHaveTextContent("NDA de Claire Durand marqué signé.");

    vi.mocked(api.adminNda).mockResolvedValue(
      overview({ customers: [{ ...CLAIRE, signed_at: "2026-10-06T10:00:00+02:00" }] }),
    );
    render(<NdaAgreement />);
    expect(await screen.findByText("Signé (06/10/2026)")).toBeInTheDocument();
  });

  it("puts a signed agreement back on hold", async () => {
    vi.mocked(api.adminNda).mockResolvedValue(overview({ customers: [{ ...CLAIRE, signed_at: "2026-10-06T10:00:00+02:00" }] }));
    vi.spyOn(api, "adminNdaSigned").mockResolvedValue({ customer_id: 7, signed_at: null });
    const user = userEvent.setup();
    render(<NdaAgreement />);
    await user.click(await screen.findByRole("checkbox", { name: "NDA signé reçu de Claire Durand" }));
    expect(api.adminNdaSigned).toHaveBeenCalledWith(7, false);
    expect(await screen.findByRole("alert")).toHaveTextContent("NDA de Claire Durand remis en attente.");
  });

  it("shows a loading error", async () => {
    vi.mocked(api.adminNda).mockRejectedValue(new ApiError(401, "Session expirée."));
    render(<NdaAgreement />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Session expirée.");
  });
});
