export function Pagination({
  page,
  totalPages,
  hasPrevious,
  hasNext,
  onPrevious,
  onNext,
}: {
  page: number;
  totalPages: number;
  hasPrevious: boolean;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <nav className="pagination" aria-label="Pagination">
      <button
        type="button"
        className="button"
        disabled={!hasPrevious}
        onClick={onPrevious}
      >
        Previous
      </button>
      <p className="pagination__status">
        Page {page} of {totalPages}
      </p>
      <button
        type="button"
        className="button"
        disabled={!hasNext}
        onClick={onNext}
      >
        Next
      </button>
    </nav>
  );
}
