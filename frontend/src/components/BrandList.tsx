import { useEffect, useRef } from "react";

import { brandsUrl, PAGE_SIZE, type BrandQuery } from "../api";
import { useBrands } from "../hooks/useBrands";
import { useIndustries } from "../hooks/useIndustries";
import { useUrlParams } from "../hooks/useUrlParams";
import { toSearch } from "../urlState";
import { BrandCard } from "./BrandCard";
import { IndustryFilter } from "./IndustryFilter";
import { Pagination } from "./Pagination";
import { SortSelect } from "./SortSelect";

/**
 * The brand listing on /brand/. The URL owns filter, sort and page; this
 * component derives everything else from it and from the API.
 */
export function BrandList() {
  const { state: url, navigate } = useUrlParams();
  const industries = useIndustries();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusResultsOnLoad = useRef(false);

  // An industry from the URL is only used once it is known to exist; while
  // the options load, no brand request is made with it. If the options fail
  // to load, the API validates it instead.
  const industryKnown = industries.industries.some(
    (i) => i.slug === url.industry,
  );
  const industry =
    url.industry && industries.status === "loaded" && !industryKnown
      ? null
      : url.industry;
  const ready = url.industry === null || industries.status !== "loading";
  const query: BrandQuery = {
    industry,
    ordering: url.ordering,
    page: url.page,
  };
  const brands = useBrands(ready ? brandsUrl(query) : null);
  const canonicalSearch = toSearch(query);

  // Replace invalid or unknown URL values with what is actually shown,
  // without adding a history entry.
  useEffect(() => {
    if (ready && canonicalSearch !== window.location.search) {
      navigate(query, { replace: true });
    }
  });

  // A page past the end (e.g. a stale deep link) falls back to page 1.
  const outOfRange = brands.error?.status === 404 && query.page > 1;
  useEffect(() => {
    if (outOfRange) navigate({ ...query, page: 1 }, { replace: true });
  });

  // An industry that could not be checked (options failed to load) and that
  // the API rejects falls back to all industries.
  const rejectedIndustry =
    brands.error?.status === 400 &&
    industry !== null &&
    industries.status === "error";
  useEffect(() => {
    if (rejectedIndustry)
      navigate({ ...query, industry: null, page: 1 }, { replace: true });
  });

  // After a page change, move focus to the new results once they load.
  useEffect(() => {
    if (!focusResultsOnLoad.current) return;
    if (brands.status === "loaded") {
      focusResultsOnLoad.current = false;
      headingRef.current?.focus();
    } else if (brands.status === "error") {
      focusResultsOnLoad.current = false;
    }
  }, [brands.status, brands.data]);

  const change = (next: Partial<BrandQuery>) =>
    navigate({ ...query, page: 1, ...next });
  const goToPage = (page: number) => {
    focusResultsOnLoad.current = true;
    navigate({ ...query, page });
  };

  const data = brands.data;
  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1;
  const countText = data
    ? `${data.count} brand${data.count === 1 ? "" : "s"}`
    : "";
  // The live region is emptied while a request is in flight and refilled
  // when it completes, so every completed load is announced, even when the
  // count is unchanged (e.g. after a sort or page change).
  const announcement = brands.status === "loaded" ? countText : "";

  return (
    <div className="brand-list">
      <div className="brand-list__controls">
        <IndustryFilter
          value={industry}
          industries={
            // Unvalidated (the options failed to load): still show what the
            // URL asked for, so the control matches the request.
            industry && industries.status === "error"
              ? [{ slug: industry, name: industry }]
              : industries.industries
          }
          status={industries.status}
          onChange={(value) => change({ industry: value })}
          onRetry={industries.retry}
        />
        <SortSelect
          value={query.ordering}
          onChange={(ordering) => change({ ordering })}
        />
      </div>

      <h2 ref={headingRef} tabIndex={-1} className="brand-list__heading">
        Results
      </h2>
      {(brands.status === "loaded" || brands.status === "refreshing") && (
        <p className="brand-list__count">{countText}</p>
      )}
      <p className="visually-hidden" aria-live="polite">
        {announcement}
      </p>

      {(brands.status === "loading" || brands.status === "idle") && (
        <p className="brand-list__message" role="status">
          Loading brands…
        </p>
      )}

      {brands.status === "error" && !outOfRange && !rejectedIndustry && (
        <div className="brand-list__message" role="alert">
          <p>The brands could not be loaded.</p>
          <button type="button" className="button" onClick={brands.retry}>
            Retry
          </button>
        </div>
      )}

      {data && brands.status !== "error" && brands.status !== "loading" && (
        <div
          className={`brand-list__results${
            brands.status === "refreshing" ? " brand-list__results--busy" : ""
          }`}
          aria-busy={brands.status === "refreshing"}
        >
          {data.results.length === 0 ? (
            <div className="brand-list__message">
              <p>No brands match{industry ? " this industry" : ""}.</p>
              {industry && (
                <button
                  type="button"
                  className="button"
                  onClick={() => change({ industry: null })}
                >
                  Show all industries
                </button>
              )}
            </div>
          ) : (
            <>
              <ul className="grid">
                {data.results.map((brand) => (
                  <li key={brand.slug}>
                    <BrandCard brand={brand} />
                  </li>
                ))}
              </ul>
              <Pagination
                page={query.page}
                totalPages={totalPages}
                hasPrevious={data.previous !== null}
                hasNext={data.next !== null}
                onPrevious={() => goToPage(query.page - 1)}
                onNext={() => goToPage(query.page + 1)}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}
