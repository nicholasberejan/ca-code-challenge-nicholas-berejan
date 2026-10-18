// Client for the public brand API (docs/decisions.md §4). The backend owns all
// business rules (filtering, ordering, averages, top review); this module only
// builds requests and types the responses.

export type Ordering =
  "-average_rating" | "average_rating" | "-review_count" | "review_count";

export const ORDERINGS: readonly Ordering[] = [
  "-average_rating",
  "average_rating",
  "-review_count",
  "review_count",
];

// The API's default ordering; omitted from URLs.
export const DEFAULT_ORDERING: Ordering = "-average_rating";

// Sent explicitly so the page count shown can never drift from the API.
export const PAGE_SIZE = 12;

export interface Industry {
  slug: string;
  name: string;
}

export interface TopReview {
  slug: string;
  title: string;
  rating: number;
  reviewer_name: string;
  snippet: string;
}

export interface Brand {
  name: string;
  slug: string;
  industries: Industry[];
  average_rating: number | null;
  review_count: number;
  short_description: string;
  top_review: TopReview | null;
}

export interface BrandPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: Brand[];
}

export interface BrandQuery {
  industry: string | null;
  ordering: Ordering;
  page: number;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function brandsUrl(query: BrandQuery): string {
  const params = new URLSearchParams();
  if (query.industry) params.set("industry", query.industry);
  if (query.ordering !== DEFAULT_ORDERING)
    params.set("ordering", query.ordering);
  if (query.page > 1) params.set("page", String(query.page));
  params.set("page_size", String(PAGE_SIZE));
  return `/api/brands/?${params.toString()}`;
}

async function getJson<T>(url: string, signal: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new ApiError(0, "The network request failed.");
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      `The request failed (${response.status}).`,
    );
  }
  return (await response.json()) as T;
}

export function fetchBrandPage(
  url: string,
  signal: AbortSignal,
): Promise<BrandPage> {
  return getJson<BrandPage>(url, signal);
}

export function fetchIndustries(signal: AbortSignal): Promise<Industry[]> {
  return getJson<Industry[]>("/api/industries/", signal);
}
