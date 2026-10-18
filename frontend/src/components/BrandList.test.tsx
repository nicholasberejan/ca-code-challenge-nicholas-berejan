import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Brand, BrandPage, Industry } from "../api";
import { BrandList } from "./BrandList";

// --- A small fake of the API boundary ----------------------------------------
// Only fetch is replaced. The fixtures are explicit; the fake applies the
// documented query parameters (industry, ordering, page, page_size) so the
// component can be exercised end to end.

const INDUSTRIES: Industry[] = [
  { slug: "finance", name: "Finance" },
  { slug: "insurance", name: "Insurance" },
  { slug: "telecom", name: "Telecom" },
];

function makeBrand(
  n: number,
  industries: Industry[],
  overrides: Partial<Brand> = {},
): Brand {
  const slug = `brand-${String(n).padStart(2, "0")}`;
  return {
    name: `Brand ${String(n).padStart(2, "0")}`,
    slug,
    industries,
    average_rating: 4,
    review_count: n,
    short_description: `About brand ${n}.`,
    top_review: null,
    ...overrides,
  };
}

// 13 insurance brands (two pages of 12) and 2 telecom brands.
const INSURANCE = INDUSTRIES[1]!;
const TELECOM = INDUSTRIES[2]!;
const BRANDS: Brand[] = [
  ...Array.from({ length: 13 }, (_, i) => makeBrand(i + 1, [INSURANCE])),
  makeBrand(14, [TELECOM]),
  makeBrand(15, [TELECOM]),
];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function brandPage(url: URL, brands: Brand[] = BRANDS): Response {
  const params = url.searchParams;
  const industry = params.get("industry");
  const ordering = params.get("ordering") ?? "-average_rating";
  const page = Number(params.get("page") ?? "1");
  const size = Number(params.get("page_size") ?? "12");

  let matching = brands.filter(
    (b) => !industry || b.industries.some((i) => i.slug === industry),
  );
  if (ordering.endsWith("review_count")) {
    matching = [...matching].sort((a, b) => a.review_count - b.review_count);
    if (ordering.startsWith("-")) matching.reverse();
  }
  const pages = Math.max(1, Math.ceil(matching.length / size));
  if (page > pages)
    return json({ errors: { page: ["Page out of range."] } }, 404);

  const link = (n: number) => {
    const next = new URL(url);
    next.searchParams.set("page", String(n));
    return next.toString();
  };
  const body: BrandPage = {
    count: matching.length,
    next: page < pages ? link(page + 1) : null,
    previous: page > 1 ? link(page - 1) : null,
    results: matching.slice((page - 1) * size, page * size),
  };
  return json(body);
}

type Handler = (url: URL, signal?: AbortSignal) => Response | Promise<Response>;

let brandHandler: Handler;
let industryHandler: Handler;
const fetchMock = vi.fn(
  async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://testserver");
    const signal = init?.signal ?? undefined;
    if (url.pathname === "/api/industries/")
      return industryHandler(url, signal);
    if (url.pathname === "/api/brands/") return brandHandler(url, signal);
    throw new Error(`Unexpected request: ${url}`);
  },
);

function brandRequests(): URL[] {
  return fetchMock.mock.calls
    .map(([input]) => new URL(String(input), "http://testserver"))
    .filter((url) => url.pathname === "/api/brands/");
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

function startAt(path: string) {
  window.history.replaceState(null, "", path);
}

function setup(path = "/brand/") {
  startAt(path);
  const user = userEvent.setup();
  render(<BrandList />);
  return user;
}

const cardTitles = () =>
  screen
    .queryAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent);

const industrySelect = () => screen.getByLabelText("Industry");
const sortSelect = () => screen.getByLabelText("Sort by");

/** The polite live region that announces "N brands" after each load. */
const announcer = () =>
  document.querySelector<HTMLElement>('[aria-live="polite"]')!;

async function loaded() {
  await screen.findByRole("heading", { level: 3, name: "Brand 01" });
}

beforeEach(() => {
  brandHandler = (url) => brandPage(url);
  industryHandler = () => json(INDUSTRIES);
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  startAt("/brand/");
});

// --- Loading and rendering -----------------------------------------------------

describe("loading and rendering", () => {
  it("shows a loading message until the first results arrive", async () => {
    const response = deferred<Response>();
    brandHandler = () => response.promise;
    setup();

    expect(screen.getByRole("status")).toHaveTextContent("Loading brands…");
    expect(cardTitles()).toEqual([]);

    await act(async () =>
      response.resolve(brandPage(new URL("http://t/api/brands/"))),
    );

    await loaded();
    expect(screen.queryByText("Loading brands…")).not.toBeInTheDocument();
  });

  it("renders each brand from the API as a card", async () => {
    const brand = makeBrand(1, [TELECOM, INDUSTRIES[0]!], {
      name: "Acme <Insurance>",
      average_rating: 3.92,
      review_count: 12,
      short_description: "Hartford-based <b>insurer</b>.",
      top_review: {
        slug: "great-claim",
        title: "Great claim",
        rating: 4,
        reviewer_name: "Sarah K.",
        snippet: "Fast & friendly.",
      },
    });
    const unreviewed = makeBrand(2, [], {
      average_rating: null,
      review_count: 0,
    });
    brandHandler = (url) => brandPage(url, [brand, unreviewed]);
    setup();

    const card = (
      await screen.findByRole("heading", { name: "Acme <Insurance>" })
    ).closest("article")!;
    const scope = within(card);
    expect(
      scope.getByRole("link", { name: "Acme <Insurance>" }),
    ).toHaveAttribute("href", "/brand/brand-01/");
    expect(
      scope.getAllByRole("listitem").map((item) => item.textContent),
    ).toEqual(["Finance", "Telecom"]);
    expect(
      scope.getByRole("img", { name: "Rated 3.9 out of 5" }),
    ).toBeInTheDocument();
    expect(scope.getByText("(12 reviews)")).toBeInTheDocument();
    expect(
      scope.getByText("Hartford-based <b>insurer</b>."),
    ).toBeInTheDocument();
    expect(scope.getByRole("link", { name: "Great claim" })).toHaveAttribute(
      "href",
      "/review/great-claim/",
    );
    expect(scope.getByText("Fast & friendly.")).toBeInTheDocument();
    expect(scope.getByText("Sarah K., rated 4 out of 5")).toBeInTheDocument();

    const other = screen
      .getByRole("heading", { name: "Brand 02" })
      .closest("article")!;
    expect(within(other).getByText("No reviews yet")).toBeInTheDocument();
    expect(within(other).queryByText(/Top review/)).not.toBeInTheDocument();
  });

  it("offers every industry from the industries API", async () => {
    industryHandler = () =>
      json([
        { slug: "space-tourism", name: "Space Tourism" },
        { slug: "zoos", name: "Zoos" },
      ]);
    setup();

    await waitFor(() => expect(industrySelect()).toBeEnabled());
    expect(
      within(industrySelect())
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["All industries", "Space Tourism", "Zoos"]);
  });

  it("requests industries once, not on every brand change", async () => {
    const user = setup();
    await loaded();

    await user.selectOptions(sortSelect(), "Most reviews");
    await user.selectOptions(industrySelect(), "Insurance");
    await waitFor(() => expect(brandRequests()).toHaveLength(3));

    const industryCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).startsWith("/api/industries/"),
    );
    expect(industryCalls).toHaveLength(1);
  });
});

// --- Filtering, sorting and the URL ----------------------------------------------

describe("filtering, sorting and the URL", () => {
  it("filters by industry and puts it in the URL", async () => {
    const user = setup();
    await loaded();

    await user.selectOptions(industrySelect(), "Telecom");

    await waitFor(() => expect(cardTitles()).toEqual(["Brand 14", "Brand 15"]));
    expect(window.location.search).toBe("?industry=telecom");
    expect(brandRequests().at(-1)!.searchParams.get("industry")).toBe(
      "telecom",
    );
  });

  it("sorts and puts the ordering in the URL", async () => {
    const user = setup();
    await loaded();

    await user.selectOptions(sortSelect(), "Most reviews");

    await waitFor(() => expect(cardTitles()[0]).toBe("Brand 15"));
    expect(window.location.search).toBe("?ordering=-review_count");
    expect(brandRequests().at(-1)!.searchParams.get("ordering")).toBe(
      "-review_count",
    );
  });

  it("omits defaults from the URL", async () => {
    const user = setup("/brand/?ordering=review_count");
    await screen.findByRole("heading", { level: 3, name: "Brand 01" });

    await user.selectOptions(sortSelect(), "Highest rated");

    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it.each([
    [
      "industry",
      async (user: ReturnType<typeof userEvent.setup>) =>
        user.selectOptions(industrySelect(), "Insurance"),
    ],
    [
      "sort",
      async (user: ReturnType<typeof userEvent.setup>) =>
        user.selectOptions(sortSelect(), "Fewest reviews"),
    ],
  ])("changing the %s resets to page 1", async (_, act) => {
    const user = setup("/brand/?page=2");
    await screen.findByText("Page 2 of 2");

    await act(user);

    await screen.findByText("Page 1 of 2");
    expect(new URLSearchParams(window.location.search).has("page")).toBe(false);
    expect(brandRequests().at(-1)!.searchParams.has("page")).toBe(false);
  });

  it("reproduces the view from a deep link", async () => {
    setup("/brand/?industry=insurance&ordering=review_count&page=2");

    await screen.findByText("Page 2 of 2");
    expect(industrySelect()).toHaveValue("insurance");
    expect(sortSelect()).toHaveValue("review_count");
    expect(cardTitles()).toEqual(["Brand 13"]);
    const request = brandRequests().at(-1)!.searchParams;
    expect(Object.fromEntries(request)).toEqual({
      industry: "insurance",
      ordering: "review_count",
      page: "2",
      page_size: "12",
    });
  });

  it("falls back to defaults for invalid URL values without calling the API with them", async () => {
    setup("/brand/?industry=nope&ordering=bogus&page=-3");

    await loaded();
    expect(industrySelect()).toHaveValue("");
    expect(sortSelect()).toHaveValue("-average_rating");
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    for (const url of brandRequests()) {
      expect(url.searchParams.has("industry")).toBe(false);
      expect(url.searchParams.has("ordering")).toBe(false);
      expect(url.searchParams.has("page")).toBe(false);
    }
    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("falls back to page 1 when a deep-linked page no longer exists", async () => {
    setup("/brand/?page=9");

    await screen.findByText("Page 1 of 2");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("restores earlier views with browser Back", async () => {
    const user = setup();
    await loaded();

    await user.selectOptions(industrySelect(), "Insurance");
    await waitFor(() =>
      expect(window.location.search).toBe("?industry=insurance"),
    );
    await user.selectOptions(sortSelect(), "Fewest reviews");
    await waitFor(() =>
      expect(window.location.search).toBe(
        "?industry=insurance&ordering=review_count",
      ),
    );
    await user.click(await screen.findByRole("button", { name: "Next" }));
    await screen.findByText("Page 2 of 2");
    expect(window.location.search).toBe(
      "?industry=insurance&ordering=review_count&page=2",
    );

    act(() => window.history.back());
    await screen.findByText("Page 1 of 2");
    expect(window.location.search).toBe(
      "?industry=insurance&ordering=review_count",
    );
    expect(sortSelect()).toHaveValue("review_count");

    act(() => window.history.back());
    await waitFor(() => expect(sortSelect()).toHaveValue("-average_rating"));
    expect(window.location.search).toBe("?industry=insurance");
    expect(industrySelect()).toHaveValue("insurance");

    act(() => window.history.back());
    await waitFor(() => expect(industrySelect()).toHaveValue(""));
    expect(window.location.search).toBe("");
    await waitFor(() => expect(announcer()).toHaveTextContent(/^15 brands$/));
    expect(brandRequests().at(-1)!.searchParams.has("industry")).toBe(false);

    act(() => window.history.forward());
    await waitFor(() => expect(industrySelect()).toHaveValue("insurance"));
    await waitFor(() => expect(announcer()).toHaveTextContent(/^13 brands$/));
  });
});

// --- Loading, empty and error states ----------------------------------------------

describe("loading, empty and error states", () => {
  it("keeps previous results visible and busy while new ones load", async () => {
    const user = setup();
    await loaded();
    const results = screen.getByRole("list", { name: "" }).parentElement!;
    expect(results).toHaveAttribute("aria-busy", "false");

    const response = deferred<Response>();
    brandHandler = () => response.promise;
    await user.selectOptions(sortSelect(), "Most reviews");

    expect(
      screen.getByRole("heading", { level: 3, name: "Brand 01" }),
    ).toBeInTheDocument();
    expect(results).toHaveAttribute("aria-busy", "true");
    expect(results).toHaveClass("brand-list__results--busy");
    expect(screen.queryByText("Loading brands…")).not.toBeInTheDocument();

    await act(async () =>
      response.resolve(
        brandPage(new URL("http://t/api/brands/?ordering=-review_count")),
      ),
    );
    await waitFor(() => expect(cardTitles()[0]).toBe("Brand 15"));
    expect(results).toHaveAttribute("aria-busy", "false");
  });

  it("announces the number of brands after each load", async () => {
    const user = setup();
    await loaded();
    expect(announcer()).toHaveTextContent(/^15 brands$/);

    await user.selectOptions(industrySelect(), "Telecom");

    await waitFor(() => expect(announcer()).toHaveTextContent(/^2 brands$/));
  });

  it("announces again after a load that keeps the same count", async () => {
    const user = setup();
    await loaded();
    expect(announcer()).toHaveTextContent(/^15 brands$/);

    const response = deferred<Response>();
    brandHandler = () => response.promise;
    await user.selectOptions(sortSelect(), "Most reviews");

    // Emptied while loading, so the same text is announced again afterwards.
    expect(announcer()).toHaveTextContent("");
    await act(async () =>
      response.resolve(
        brandPage(new URL("http://t/api/brands/?ordering=-review_count")),
      ),
    );
    await waitFor(() => expect(announcer()).toHaveTextContent(/^15 brands$/));
  });

  it("shows an empty state with a way to clear the filter", async () => {
    brandHandler = (url) =>
      url.searchParams.get("industry") === "finance"
        ? brandPage(url, [])
        : brandPage(url);
    const user = setup();
    await loaded();

    await user.selectOptions(industrySelect(), "Finance");

    expect(
      await screen.findByText("No brands match this industry."),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Show all industries" }),
    );

    await loaded();
    expect(window.location.search).toBe("");
    expect(industrySelect()).toHaveValue("");
  });

  it("does not offer to clear a filter when none is applied", async () => {
    brandHandler = (url) => brandPage(url, []);
    setup();

    expect(await screen.findByText("No brands match.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Show all industries" }),
    ).not.toBeInTheDocument();
  });

  it("shows an error with a Retry that repeats the request", async () => {
    let fail = true;
    brandHandler = (url) => (fail ? json({}, 500) : brandPage(url));
    const user = setup("/brand/?ordering=review_count");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The brands could not be loaded.");
    expect(sortSelect()).toBeEnabled();
    expect(industrySelect()).toBeEnabled();

    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await screen.findByRole("heading", { level: 3, name: "Brand 01" });
    const [first, second] = brandRequests().slice(-2);
    expect(second!.toString()).toBe(first!.toString());
    expect(window.location.search).toBe("?ordering=review_count");
  });

  it("never lets an older response replace newer results", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const pending = [first, second];
    brandHandler = () => pending.shift()!.promise;
    const user = setup();
    await waitFor(() => expect(industrySelect()).toBeEnabled());

    await user.selectOptions(industrySelect(), "Telecom");
    await waitFor(() => expect(brandRequests()).toHaveLength(2));

    await act(async () =>
      second.resolve(
        brandPage(new URL("http://t/api/brands/?industry=telecom")),
      ),
    );
    await waitFor(() => expect(cardTitles()).toEqual(["Brand 14", "Brand 15"]));

    // The stale, unfiltered response arrives last (the fake ignores abort).
    await act(async () =>
      first.resolve(brandPage(new URL("http://t/api/brands/"))),
    );

    expect(cardTitles()).toEqual(["Brand 14", "Brand 15"]);
    expect(announcer()).toHaveTextContent(/^2 brands$/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores a failure from an older request that arrives after newer results", async () => {
    const first = deferred<Response>();
    let calls = 0;
    brandHandler = (url) => (calls++ === 0 ? first.promise : brandPage(url));
    const user = setup();
    await waitFor(() => expect(industrySelect()).toBeEnabled());

    await user.selectOptions(industrySelect(), "Telecom");
    await waitFor(() => expect(cardTitles()).toEqual(["Brand 14", "Brand 15"]));

    // The stale request fails last (the fake ignores abort).
    await act(async () => first.resolve(json({}, 500)));

    expect(cardTitles()).toEqual(["Brand 14", "Brand 15"]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByRole("list", { name: "" }).parentElement,
    ).toHaveAttribute("aria-busy", "false");
  });

  it("aborts the in-flight request when the parameters change", async () => {
    const signals: AbortSignal[] = [];
    brandHandler = (url, signal) => {
      signals.push(signal!);
      return signals.length === 1
        ? new Promise<Response>(() => {})
        : brandPage(url);
    };
    const user = setup();
    await waitFor(() => expect(industrySelect()).toBeEnabled());
    expect(signals[0]!.aborted).toBe(false);

    await user.selectOptions(industrySelect(), "Telecom");

    await waitFor(() => expect(cardTitles()).toEqual(["Brand 14", "Brand 15"]));
    expect(signals[0]!.aborted).toBe(true);
    expect(signals.at(-1)!.aborted).toBe(false);
  });

  it("does not show an error for a request it aborted", async () => {
    // Like a browser: an aborted fetch rejects with an AbortError.
    let first = true;
    brandHandler = (url, signal) => {
      if (!first) return brandPage(url);
      first = false;
      return new Promise((_, reject) =>
        signal!.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError")),
        ),
      );
    };
    const user = setup();
    await waitFor(() => expect(industrySelect()).toBeEnabled());

    await user.selectOptions(industrySelect(), "Telecom");

    await waitFor(() => expect(cardTitles()).toEqual(["Brand 14", "Brand 15"]));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps an unvalidated URL industry visible when industries fail to load", async () => {
    industryHandler = () => json({}, 500);
    setup("/brand/?industry=telecom");

    await waitFor(() => expect(cardTitles()).toEqual(["Brand 14", "Brand 15"]));
    expect(industrySelect()).toHaveValue("telecom");
    expect(brandRequests().at(-1)!.searchParams.get("industry")).toBe(
      "telecom",
    );
  });

  it("falls back to all industries when an unvalidated URL industry is rejected", async () => {
    industryHandler = () => json({}, 500);
    brandHandler = (url) =>
      url.searchParams.get("industry") === "nope"
        ? json({ errors: { industry: ["Unknown industry: 'nope'."] } }, 400)
        : brandPage(url);
    const historyLength = window.history.length;
    setup("/brand/?industry=nope");

    await loaded();
    expect(
      brandRequests().some(
        (url) => url.searchParams.get("industry") === "nope",
      ),
    ).toBe(true);
    expect(window.location.search).toBe("");
    expect(window.history.length).toBe(historyLength); // replaced, not pushed
    expect(industrySelect()).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an industries error without blocking the brand list", async () => {
    industryHandler = () => json({}, 500);
    setup();

    await loaded();
    expect(
      screen.getByText("Industries could not be loaded."),
    ).toBeInTheDocument();

    industryHandler = () => json(INDUSTRIES);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Retry industries" }));
    await waitFor(() =>
      expect(within(industrySelect()).getAllByRole("option")).toHaveLength(4),
    );
  });
});

// --- Pagination ---------------------------------------------------------------------

describe("pagination", () => {
  it("keeps unavailable buttons visible but disabled", async () => {
    const user = setup();
    await loaded();

    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByText("Page 2 of 2");
    expect(cardTitles()).toEqual(["Brand 13", "Brand 14", "Brand 15"]);
    expect(window.location.search).toBe("?page=2");
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  it("can be paged with the keyboard alone", async () => {
    const user = setup();
    await loaded();
    const next = screen.getByRole("button", { name: "Next" });

    for (let i = 0; i < 40 && document.activeElement !== next; i++) {
      await user.tab();
    }
    expect(next).toHaveFocus();
    await user.keyboard("{Enter}");

    await screen.findByText("Page 2 of 2");
  });

  it("moves focus to the results heading after a page change, and only then", async () => {
    const user = setup();
    await loaded();
    const heading = screen.getByRole("heading", { level: 2, name: "Results" });
    expect(heading).not.toHaveFocus();

    await user.selectOptions(industrySelect(), "Insurance");
    await waitFor(() => expect(announcer()).toHaveTextContent(/^13 brands$/));
    expect(heading).not.toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 2 of 2");
    await waitFor(() => expect(heading).toHaveFocus());
  });
});
