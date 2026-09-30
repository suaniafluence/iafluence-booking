import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api, ApiError, type AdminOverview } from "../../api";
import { deferred, finishedSession, sessionReport, synthese } from "../../test/fixtures";
import { reportLabel, SessionReports } from "./SessionReports";

const reports = (over: Partial<AdminOverview["reports"]> = {}): AdminOverview["reports"] => ({
  enabled: true,
  send_without_review: false,
  sessions: [finishedSession()],
  ...over,
});

describe("reportLabel", () => {
  it.each([
    [null, "Pas de compte rendu", "off"],
    [sessionReport({ status: "waiting_transcript" }), "En attente de la transcription", "wait"],
    [sessionReport({ status: "summarizing" }), "Résumé en cours", "wait"],
    [sessionReport({ status: "ready" }), "Résumé prêt", "wait"],
    [sessionReport({ status: "failed" }), "Échec", "fail"],
    [sessionReport(), "Brouillon créé avec compte rendu", "ok"],
    [sessionReport({ delivery: "sent" }), "Envoyé avec compte rendu", "ok"],
    [sessionReport({ with_summary: false }), "Brouillon créé sans compte rendu", "off"],
    [sessionReport({ with_summary: false, delivery: "sent" }), "Envoyé sans compte rendu", "off"],
  ])("%# → %s", (report, label, tone) => {
    expect(reportLabel(report)).toEqual([label, tone]);
  });
});

describe("SessionReports", () => {
  it("lists finished sessions with their report status", () => {
    render(
      <SessionReports
        reports={reports({
          sessions: [
            finishedSession(),
            finishedSession(
              sessionReport({
                id: 8,
                status: "waiting_transcript",
                transcript_found: false,
                transcript_attempts: 3,
                next_attempt_at: "2026-10-08T15:20:00+02:00",
                synthese: null,
                has_image: false,
                drafted_at: null,
              }),
              { booking_id: 32, customer: "Paul Durand" },
            ),
            finishedSession(null, { booking_id: 33, customer: "Anne Ancienne" }),
          ],
        })}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("heading", { name: "Comptes rendus de séance" })).toBeInTheDocument();
    expect(screen.getByText(/résumée par votre agent Codex/)).toBeInTheDocument();
    const items = within(screen.getByRole("list", { name: "Séances terminées" })).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent(
      "Marie MartinJeudi 8 octobre 2026 · 14:00 · Conseil IA - 3hBrouillon créé avec compte renduPréparé le Jeudi 8 octobre 2026 à 15:12Aperçu",
    );
    expect(items[1]).toHaveTextContent(
      "En attente de la transcriptionFireflies interrogé 3 fois · prochaine vérification à 15:20 · abandon à 21:00",
    );
    expect(within(items[1]).getByRole("button", { name: "Relancer Fireflies" })).toBeInTheDocument();
    expect(within(items[1]).getByRole("button", { name: "Créer le brouillon sans résumé" })).toBeInTheDocument();
    expect(within(items[1]).queryByRole("button", { name: /Aperçu/ })).not.toBeInTheDocument();
    expect(items[2]).toHaveTextContent(/^Anne AncienneJeudi 8 octobre 2026 · 14:00 · Conseil IA - 3hPas de compte rendu$/);
    expect(within(items[0]).queryByRole("button", { name: /Relancer/ })).not.toBeInTheDocument();
  });

  it("shows errors, erased reports and attempts", () => {
    render(
      <SessionReports
        reports={reports({
          sessions: [
            finishedSession(
              sessionReport({
                status: "failed",
                summary_attempts: 2,
                error: "Résumé impossible : sortie Codex invalide",
                synthese: null,
                has_image: false,
              }),
            ),
            finishedSession(
              sessionReport({ id: 9, erased: true, synthese: null, has_image: false, drafted_at: null }),
              { booking_id: 40 },
            ),
            finishedSession(sessionReport({ id: 10, status: "summarizing", summary_attempts: 1 }), { booking_id: 41 }),
            finishedSession(
              sessionReport({ id: 11, status: "waiting_transcript", next_attempt_at: null, transcript_found: true }),
              { booking_id: 42 },
            ),
          ],
        })}
        onChange={() => {}}
      />,
    );
    const items = within(screen.getByRole("list", { name: "Séances terminées" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Échec2 tentative(s) de résuméRésumé impossible : sortie Codex invalide");
    expect(within(items[0]).getByRole("button", { name: "Relancer le résumé" })).toBeInTheDocument();
    expect(items[1]).toHaveTextContent(/Brouillon créé avec compte rendu1 tentative\(s\) de résuméCompte rendu effacé \(durée de conservation écoulée\)\.$/);
    expect(items[2]).toHaveTextContent(/Résumé en coursAperçu$/);
    expect(items[3]).toHaveTextContent("Fireflies interrogé 2 fois · abandon à 21:00");
  });

  it("previews the summary and the infographic", async () => {
    const user = userEvent.setup();
    render(<SessionReports reports={reports()} onChange={() => {}} />);
    const toggle = screen.getByRole("button", { name: "Aperçu du compte rendu de Marie Martin" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveTextContent("Masquer l’aperçu");
    expect(screen.getByRole("img", { name: "Infographie de la séance de Marie Martin" })).toHaveAttribute(
      "src",
      "/api/admin/reports/7/image.png",
    );
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Objectifs", "Points abordés", "Vos actions", "Prochaines étapes"]); // no empty section
    expect(screen.getByText("Choix de l'outil")).toBeInTheDocument();
    await user.click(toggle);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("previews a summary without image, or an image without summary", async () => {
    const user = userEvent.setup();
    render(
      <SessionReports
        reports={reports({
          sessions: [
            finishedSession(sessionReport({ has_image: false })),
            finishedSession(sessionReport({ id: 12, synthese: null }), { booking_id: 50, customer: "Léa" }),
          ],
        })}
        onChange={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Aperçu du compte rendu de Marie Martin" }));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(synthese.actions_client[0])).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Aperçu du compte rendu de Léa" }));
    expect(screen.getByRole("img", { name: "Infographie de la séance de Léa" })).toBeInTheDocument();
    expect(screen.queryByText(synthese.actions_client[0])).not.toBeInTheDocument(); // one preview at a time
  });

  it.each([
    [false, "Relancer Fireflies", "Recherche Fireflies relancée pour Marie Martin (6 h)."],
    [true, "Relancer le résumé", "Nouveau résumé demandé pour Marie Martin."],
  ])("retries (transcript found: %s)", async (found, button, message) => {
    const retry = deferred<{ id: number; status: "waiting_transcript" }>();
    vi.spyOn(api, "adminRetryReport").mockReturnValue(retry.promise);
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <SessionReports
        reports={reports({ sessions: [finishedSession(sessionReport({ status: "failed", transcript_found: found }))] })}
        onChange={onChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: button }));
    expect(api.adminRetryReport).toHaveBeenCalledWith(7);
    expect(screen.getByRole("button", { name: button })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Créer le brouillon sans résumé" })).toBeDisabled();
    retry.resolve({ id: 7, status: "waiting_transcript" });
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: button })).toBeEnabled();
  });

  it("drafts without summary, and shows refusals", async () => {
    vi.spyOn(api, "adminDraftWithoutSummary")
      .mockRejectedValueOnce(new ApiError(409, "Le résumé est en cours de rédaction : réessayez dans quelques minutes."))
      .mockResolvedValueOnce({ id: 7, status: "drafted" });
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <SessionReports
        reports={reports({ sessions: [finishedSession(sessionReport({ status: "waiting_transcript" }))] })}
        onChange={onChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Créer le brouillon sans résumé" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Le résumé est en cours de rédaction : réessayez dans quelques minutes.",
    );
    expect(onChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Créer le brouillon sans résumé" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Brouillon sans résumé créé pour Marie Martin.");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("saves the « send without review » option", async () => {
    const save = deferred<{ send_without_review: boolean }>();
    vi.spyOn(api, "adminSetReportSettings").mockReturnValueOnce(save.promise);
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<SessionReports reports={reports()} onChange={onChange} />);
    const box = screen.getByRole("checkbox", { name: /Envoyer aussi les résumés sans relecture/ });
    expect(box).not.toBeChecked();
    await user.click(box);
    expect(box).toBeChecked(); // at once
    expect(api.adminSetReportSettings).toHaveBeenCalledWith(true);
    save.resolve({ send_without_review: true });
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));

    vi.mocked(api.adminSetReportSettings).mockRejectedValueOnce(new ApiError(500, "Erreur."));
    await user.click(box);
    expect(await screen.findByRole("alert")).toHaveTextContent("Erreur.");
    expect(box).not.toBeChecked(); // back to the saved value
  });

  it("shows the saved option and the disabled feature", () => {
    render(<SessionReports reports={reports({ enabled: false, send_without_review: true, sessions: [] })} onChange={() => {}} />);
    expect(screen.getByRole("checkbox", { name: /sans relecture/ })).toBeChecked();
    expect(screen.getByText(/Désactivé : sans clé Fireflies ni Codex/)).toBeInTheDocument();
    expect(screen.getByText("Aucune séance terminée pour le moment.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
