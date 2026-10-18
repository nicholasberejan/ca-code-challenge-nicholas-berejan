import { PAGE_SIZE, type BrandPage } from "../api";
import { BrandCard } from "./BrandCard";
import { Pagination } from "./Pagination";

/**
 * A loaded page of brands: the cards and pagination, or the empty state.
 * Presentational: BrandList decides what to show and owns every action.
 */
export function BrandResults({
  data,
  pageNumber,
  busy,
  canClearFilter,
  onClearFilter,
  onPageChange,
}: {
  data: BrandPage;
  pageNumber: number;
  /** A newer request is in flight; these results are about to be replaced. */
  busy: boolean;
  canClearFilter: boolean;
  onClearFilter: () => void;
  onPageChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(data.count / PAGE_SIZE));

  return (
    <div
      className={`brand-list__results${busy ? " brand-list__results--busy" : ""}`}
      aria-busy={busy}
    >
      {data.results.length === 0 ? (
        <div className="brand-list__message">
          <p>No brands match{canClearFilter ? " this industry" : ""}.</p>
          {canClearFilter && (
            <button type="button" className="button" onClick={onClearFilter}>
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
            page={pageNumber}
            totalPages={totalPages}
            hasPrevious={data.previous !== null}
            hasNext={data.next !== null}
            onPrevious={() => onPageChange(pageNumber - 1)}
            onNext={() => onPageChange(pageNumber + 1)}
          />
        </>
      )}
    </div>
  );
}
