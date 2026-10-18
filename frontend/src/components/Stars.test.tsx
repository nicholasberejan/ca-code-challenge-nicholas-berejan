import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatRating, Stars } from "./Stars";

describe("formatRating", () => {
  // One decimal place, half up from the API's two-decimal value, the same
  // rule the server-rendered brand page uses.
  it.each([
    [3.92, "3.9"],
    [3.04, "3.0"],
    [1.15, "1.2"],
    [2.45, "2.5"],
    [2.15, "2.2"],
    [4.95, "5.0"],
    [5, "5.0"],
    [0, "0.0"],
  ])("%s -> %s", (value, expected) => {
    expect(formatRating(value)).toBe(expected);
  });
});

describe("Stars", () => {
  it("fills whole stars and labels the rating", () => {
    const { container } = render(<Stars rating={3.92} />);

    expect(
      screen.getByRole("img", { name: "Rated 3.9 out of 5" }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".stars__star--full")).toHaveLength(3);
    expect(container.querySelectorAll(".stars__star--empty")).toHaveLength(2);
  });
});
