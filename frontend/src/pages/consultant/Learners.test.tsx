import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../../api";
import { learnerList, learnerRow } from "../../test/fixtures";
import { Learners } from "./Learners";

const plain = (s: string | null) => (s ?? "").replace(/\p{Zs}/gu, " ");
const show = () =>
  render(
    <MemoryRouter>
      <Learners />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.spyOn(api, "learners").mockResolvedValue(learnerList());
});

describe("Learners", () => {
  it("shows each learner's time and links to their page", async () => {
    show();
    expect(screen.getByRole("status")).toHaveTextContent("Chargement des apprenants…");
    const link = await screen.findByRole("link");
    const item = link.closest("li")!;
    expect(link).toHaveAttribute("href", "/consultant/apprenants/7");
    expect(plain(link.textContent)).toContain("Jean DupontEn coursDupont Conseil · jean@dupont-conseil.fr");
    expect(link).toHaveTextContent("2 séances faites sur 5");
    expect(link).toHaveTextContent("3 séances restantes");
    expect(link).toHaveTextContent("Une séance tous les 14 j · fin estimée lundi 16 novembre 2026");
    expect(link).toHaveTextContent("Prochaine : Jeudi 8 octobre 2026 · 14:00");
    expect(within(item).getByText("Pas encore de plan d'action")).toHaveAttribute("data-level", "info");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("singular, idle and prospect learners", async () => {
    vi.mocked(api.learners).mockResolvedValue(
      learnerList({
        learners: [
          learnerRow({ sessions_done: 1, sessions_to_deliver: 1, pace_days: null, next_session: null, idle_days: 1, company: null }),
          learnerRow({ customer_id: 8, name: "Paul", status: "prospect", hours_purchased: 0, next_session: null, idle_days: null, alerts: [] }),
        ],
      }),
    );
    show();
    const links = await screen.findAllByRole("link");
    expect(links[0]).toHaveTextContent("1 séance faite sur 5");
    expect(links[0]).toHaveTextContent("1 séance restante");
    expect(links[0]).toHaveTextContent("Inactif depuis 1 jour");
    expect(links[0]).not.toHaveTextContent("Une séance tous les");
    expect(plain(links[0].textContent)).toContain("En coursjean@dupont-conseil.fr");
    expect(links[1]).toHaveTextContent("Aucune heure achetée");
    expect(links[1]).toHaveTextContent("Prospect");
    expect(links[1]).toHaveTextContent("—");
  });

  it("shows the hidden learners on demand", async () => {
    vi.mocked(api.learners)
      .mockResolvedValueOnce(learnerList({ learners: [], hidden_count: 2 }))
      .mockResolvedValueOnce(learnerList({ learners: [learnerRow({ hidden: true, idle_days: 70, next_session: null })], hidden_count: 2 }));
    const user = userEvent.setup();
    show();
    expect(await screen.findByText("Aucun apprenant actif.")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Afficher les apprenants inactifs depuis plus de 60 jours (2)" }));
    expect(api.learners).toHaveBeenLastCalledWith(true);
    const link = await screen.findByRole("link");
    expect(link).toHaveTextContent("Inactif depuis 70 jours");
    expect(link.closest("li")).toHaveClass("opacity-60");
  });

  it("shows a load error", async () => {
    vi.mocked(api.learners).mockRejectedValue(new ApiError(500, "Erreur serveur."));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Erreur serveur.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
