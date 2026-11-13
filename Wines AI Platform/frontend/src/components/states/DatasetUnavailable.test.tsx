import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiProblem, NetworkProblem } from "@/lib/problem";
import { unavailableReason } from "@/lib/unavailable";
import { DatasetUnavailable } from "./DatasetUnavailable";

const problem = (status: number, code: string, retryAfter: number | null = null) =>
  new ApiProblem({ type: "about:blank", title: "t", status, code, detail: "d" }, retryAfter);

describe("unavailableReason", () => {
  it("treats a 429 as rate limiting, not a missing dataset", () => {
    expect(unavailableReason(problem(429, "rate_limited", 12))).toEqual({
      kind: "rate_limited",
      retryAfter: 12,
    });
  });
  it("treats readyz 503 as the dataset being unavailable", () => {
    expect(unavailableReason(problem(503, "http_error"))).toEqual({ kind: "dataset" });
  });
  it("treats network failures and other errors as unreachable", () => {
    expect(unavailableReason(new NetworkProblem())).toEqual({ kind: "unreachable" });
    expect(unavailableReason(problem(500, "internal"))).toEqual({ kind: "unreachable" });
    expect(unavailableReason(new Error("boom"))).toEqual({ kind: "unreachable" });
  });
});

describe("DatasetUnavailable", () => {
  it("says 'dataset not loaded' only for the dataset reason", () => {
    render(<DatasetUnavailable reason={{ kind: "dataset" }} />);
    expect(screen.getByRole("heading", { name: "Recommendations unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/dataset is not loaded/)).toBeInTheDocument();
  });
  it("tells a rate-limited user to wait, with the retry time", () => {
    render(<DatasetUnavailable reason={{ kind: "rate_limited", retryAfter: 30 }} />);
    expect(screen.getByRole("heading", { name: /Too many requests/ })).toBeInTheDocument();
    expect(screen.getByText(/about 30s/)).toBeInTheDocument();
    expect(screen.queryByText(/dataset is not loaded/)).not.toBeInTheDocument();
  });
  it("says the server is unreachable when nothing answered", () => {
    render(<DatasetUnavailable reason={{ kind: "unreachable" }} />);
    expect(screen.getByRole("heading", { name: "Can't reach Wines AI" })).toBeInTheDocument();
  });
});
