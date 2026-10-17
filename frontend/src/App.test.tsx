import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders into the DOM", () => {
    render(<App />);

    expect(
      screen.getByText("The brand list is not available yet."),
    ).toBeInTheDocument();
  });
});
