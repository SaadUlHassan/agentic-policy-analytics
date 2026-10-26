import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClarificationCard } from "@/components/ClarificationCard";

const question = { question: "Which sector do you mean?", options: ["Information & Communications", "Finance"], version: 3 };

afterEach(() => vi.unstubAllGlobals());

function sentBody(fetchMock: ReturnType<typeof vi.fn>) {
  return JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
}

describe("ClarificationCard", () => {
  it("answers with a chosen option and the question's version", async () => {
    const fetchMock = vi.fn(async () => Response.json({ id: "a1", status: "queued" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    const onAnswered = vi.fn();
    render(<ClarificationCard analysisId="a1" question={question} onAnswered={onAnswered} />);

    fireEvent.click(screen.getByRole("button", { name: "Information & Communications" }));

    await waitFor(() => expect(onAnswered).toHaveBeenCalled());
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(/\/api\/analyses\/a1\/clarify$/);
    expect(sentBody(fetchMock)).toEqual({ clarification_version: 3, answer: "Information & Communications" });
  });

  it("can proceed on the stated assumptions", async () => {
    const fetchMock = vi.fn(async () => Response.json({ id: "a1", status: "queued" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ClarificationCard analysisId="a1" question={question} onAnswered={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Proceed with stated assumptions" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentBody(fetchMock)).toEqual({ clarification_version: 3, proceed_with_assumptions: true });
  });

  it("explains an answer that arrived too late and refreshes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ code: "CLARIFICATION_STALE", title: "Conflicting analysis state" }, { status: 409 })),
    );
    const onAnswered = vi.fn();
    render(<ClarificationCard analysisId="a1" question={question} onAnswered={onAnswered} />);
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "ICT" } });
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already answered");
    expect(onAnswered).toHaveBeenCalled();
  });
});
