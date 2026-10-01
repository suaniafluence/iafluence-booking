import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../../api";
import { deferred, firefliesStatus } from "../../test/fixtures";
import { FirefliesConnection } from "./FirefliesConnection";

const CONNECTED = firefliesStatus({ state: "connected", source: "admin", email: "suan@iafluence.fr", name: "Suan Tay" });

beforeEach(() => {
  vi.spyOn(api, "adminFirefliesStatus").mockResolvedValue(firefliesStatus());
});

describe("FirefliesConnection", () => {
  it("connects with a pasted API key, then forgets it", async () => {
    const connect = deferred<ReturnType<typeof firefliesStatus>>();
    vi.spyOn(api, "adminFirefliesConnect").mockReturnValue(connect.promise);
    const user = userEvent.setup();
    render(<FirefliesConnection />);
    expect(screen.getByRole("heading", { name: "Connexion Fireflies" })).toBeInTheDocument();
    expect(await screen.findByText("Non connecté")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Connecter Fireflies" });
    expect(button).toBeDisabled();

    const input = screen.getByLabelText("Clé API Fireflies");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "off");
    await user.type(input, "ff-key-123");
    await user.click(button);
    expect(api.adminFirefliesConnect).toHaveBeenCalledWith("ff-key-123");
    expect(screen.getByRole("button", { name: "Vérification…" })).toBeDisabled();

    connect.resolve(CONNECTED);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Fireflies est connecté : les transcriptions des séances seront récupérées automatiquement.",
    );
    expect(screen.getByText("Connecté")).toBeInTheDocument();
    expect(screen.getByText(/Compte Fireflies/)).toHaveTextContent("Compte Fireflies : suan@iafluence.fr · Suan Tay");
    expect(screen.queryByLabelText("Clé API Fireflies")).not.toBeInTheDocument();
  });

  it("shows why Fireflies refused the key and keeps it for a retry", async () => {
    vi.spyOn(api, "adminFirefliesConnect").mockRejectedValue(
      new ApiError(400, "Fireflies a refusé la connexion : clé API Fireflies refusée."),
    );
    const user = userEvent.setup();
    render(<FirefliesConnection />);
    await user.type(await screen.findByLabelText("Clé API Fireflies"), "wrong");
    await user.click(screen.getByRole("button", { name: "Connecter Fireflies" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Fireflies a refusé la connexion : clé API Fireflies refusée.",
    );
    expect(screen.getByLabelText("Clé API Fireflies")).toHaveValue("wrong");
    expect(screen.getByRole("button", { name: "Connecter Fireflies" })).toBeEnabled();
  });

  it("disconnects", async () => {
    vi.mocked(api.adminFirefliesStatus).mockResolvedValue(CONNECTED);
    vi.spyOn(api, "adminFirefliesDisconnect").mockResolvedValue(firefliesStatus());
    const user = userEvent.setup();
    render(<FirefliesConnection />);
    await user.click(await screen.findByRole("button", { name: "Déconnecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Fireflies est déconnecté.");
    expect(screen.getByText("Non connecté")).toBeInTheDocument();
    expect(screen.getByLabelText("Clé API Fireflies")).toBeInTheDocument();
  });

  it("shows a key set on the server, without disconnect", async () => {
    vi.mocked(api.adminFirefliesStatus).mockResolvedValue(firefliesStatus({ state: "connected", source: "server" }));
    render(<FirefliesConnection />);
    expect(await screen.findByText("Connecté")).toBeInTheDocument();
    expect(screen.getByText(/Clé définie sur le serveur/)).toHaveTextContent(
      "Clé définie sur le serveur (FIREFLIES_API_KEY).",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("asks to reconnect when the stored key is unreadable", async () => {
    const detail = "La clé enregistrée n’est plus lisible (SESSION_SECRET a changé) : reconnectez Fireflies.";
    vi.mocked(api.adminFirefliesStatus).mockResolvedValue(firefliesStatus({ detail }));
    render(<FirefliesConnection />);
    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(screen.getByLabelText("Clé API Fireflies")).toBeInTheDocument();
  });

  it("shows a status load error", async () => {
    vi.mocked(api.adminFirefliesStatus).mockRejectedValue(new ApiError(0, "Connexion impossible."));
    render(<FirefliesConnection />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Connexion impossible.");
    expect(screen.queryByText("Vérification de la connexion…")).not.toBeInTheDocument();
  });
});
