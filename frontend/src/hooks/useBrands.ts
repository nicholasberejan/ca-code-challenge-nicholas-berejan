import { useEffect, useState } from "react";

import { ApiError, fetchBrandPage, type BrandPage } from "../api";

export type BrandsStatus =
  | "idle" // nothing requested yet (waiting for inputs)
  | "loading" // first load: nothing to show yet
  | "refreshing" // new request in flight; previous results still shown
  | "loaded"
  | "error";

interface Settled {
  key: string;
  data: BrandPage | null; // last successful page, kept across requests
  error: ApiError | null;
}

/**
 * Fetches a brand page whenever `url` changes (or on retry). The previous
 * request is aborted, and a response that arrives for anything but the
 * latest request is ignored, so an older response can never replace newer
 * results. An aborted request is never reported as an error.
 */
export function useBrands(url: string | null): {
  status: BrandsStatus;
  data: BrandPage | null;
  error: ApiError | null;
  retry: () => void;
} {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled | null>(null);
  const key = url === null ? null : `${url}#${attempt}`;

  useEffect(() => {
    if (url === null || key === null) return;
    const controller = new AbortController();
    fetchBrandPage(url, controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ key, data, error: null });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setSettled((previous) => ({
          key,
          data: previous?.data ?? null,
          error:
            error instanceof ApiError
              ? error
              : new ApiError(0, "The request failed."),
        }));
      },
    );
    return () => controller.abort();
  }, [url, key]);

  const pending = key !== null && settled?.key !== key;
  const data = settled?.data ?? null;
  const error = pending ? null : (settled?.error ?? null);

  let status: BrandsStatus;
  if (key === null) status = "idle";
  else if (error) status = "error";
  else if (pending) status = data ? "refreshing" : "loading";
  else status = "loaded";

  return { status, data, error, retry: () => setAttempt((n) => n + 1) };
}
