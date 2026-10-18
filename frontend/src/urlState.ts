// The URL's query string is the single source of truth for the user's
// choices. Parameter names match the API; defaults are omitted.
import { DEFAULT_ORDERING, ORDERINGS, type Ordering } from "./api";

export interface UrlState {
  industry: string | null;
  ordering: Ordering;
  page: number;
}

export const DEFAULT_STATE: UrlState = {
  industry: null,
  ordering: DEFAULT_ORDERING,
  page: 1,
};

function isOrdering(value: string | null): value is Ordering {
  return ORDERINGS.includes(value as Ordering);
}

/** Invalid values fall back to defaults. The industry is checked against the
 * loaded industries separately, once they are known. */
export function parseSearch(search: string): UrlState {
  const params = new URLSearchParams(search);
  const ordering = params.get("ordering");
  const page = params.get("page") ?? "";
  return {
    industry: params.get("industry") || null,
    ordering: isOrdering(ordering) ? ordering : DEFAULT_ORDERING,
    page: /^[1-9][0-9]*$/.test(page) ? Number(page) : 1,
  };
}

export function toSearch(state: UrlState): string {
  const params = new URLSearchParams();
  if (state.industry) params.set("industry", state.industry);
  if (state.ordering !== DEFAULT_ORDERING)
    params.set("ordering", state.ordering);
  if (state.page > 1) params.set("page", String(state.page));
  const query = params.toString();
  return query ? `?${query}` : "";
}
