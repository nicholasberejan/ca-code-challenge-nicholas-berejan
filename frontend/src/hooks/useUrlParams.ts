import { useCallback, useMemo, useSyncExternalStore } from "react";

import { parseSearch, toSearch, type UrlState } from "../urlState";

// pushState/replaceState fire no event, so changes made here announce
// themselves; popstate covers Back/Forward.
const URL_CHANGE = "brand-list:url-change";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(URL_CHANGE, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(URL_CHANGE, onChange);
  };
}

function currentSearch(): string {
  return window.location.search;
}

/** URL-owned state (industry, ordering, page) and a way to change it. */
export function useUrlParams(): {
  state: UrlState;
  navigate: (next: UrlState, options?: { replace?: boolean }) => void;
} {
  const search = useSyncExternalStore(subscribe, currentSearch);
  const state = useMemo(() => parseSearch(search), [search]);

  const navigate = useCallback(
    (next: UrlState, { replace = false }: { replace?: boolean } = {}) => {
      const nextSearch = toSearch(next);
      if (nextSearch === window.location.search) return;
      const url = `${window.location.pathname}${nextSearch}`;
      if (replace) {
        window.history.replaceState(null, "", url);
      } else {
        window.history.pushState(null, "", url);
      }
      window.dispatchEvent(new Event(URL_CHANGE));
    },
    [],
  );

  return { state, navigate };
}
