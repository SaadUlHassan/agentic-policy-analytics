import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QueryForm, SAMPLE_QUERIES } from "@/components/QueryForm";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("QueryForm", () => {
  it("blocks submission until the question is long enough", () => {
    render(<QueryForm />);
    const button = screen.getByRole("button", { name: "Run analysis" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Research question"), { target: { value: "  ab  " } });
    expect(button).toBeDisabled();
  });

  it("fills a sample, submits the trimmed question and opens the live view", async () => {
    const fetchMock = vi.fn(async () => Response.json({ id: "abc", status: "queued" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryForm />);
    fireEvent.click(screen.getByRole("button", { name: SAMPLE_QUERIES[0] }));
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/analyses/abc"));
    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(body).toEqual({ query: SAMPLE_QUERIES[0] });
  });

  it("shows the API's error and lets the user retry", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ code: "VALIDATION_ERROR", title: "Request validation failed" }, { status: 422 })));
    render(<QueryForm />);
    fireEvent.change(screen.getByLabelText("Research question"), { target: { value: "ICT jobs since 2020" } });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Request validation failed");
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });
});
