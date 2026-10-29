import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SeverityBadge from "../components/SeverityBadge";

describe("risk level wording", () => {
  it("shows MODERATE wherever the API says MEDIUM, and the other levels unchanged", () => {
    const { rerender } = render(<SeverityBadge level="MEDIUM" />);
    expect(screen.getByText(/MODERATE/)).toBeInTheDocument();
    expect(screen.queryByText(/MEDIUM/)).not.toBeInTheDocument();
    for (const l of ["LOW", "HIGH", "CRITICAL"] as const) {
      rerender(<SeverityBadge level={l} />);
      expect(screen.getByText(new RegExp(l))).toBeInTheDocument();
    }
  });
});
