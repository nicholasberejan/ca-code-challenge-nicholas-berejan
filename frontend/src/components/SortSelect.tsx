import type { Ordering } from "../api";

const OPTIONS: { value: Ordering; label: string }[] = [
  { value: "-average_rating", label: "Highest rated" },
  { value: "average_rating", label: "Lowest rated" },
  { value: "-review_count", label: "Most reviews" },
  { value: "review_count", label: "Fewest reviews" },
];

export function SortSelect({
  value,
  onChange,
}: {
  value: Ordering;
  onChange: (ordering: Ordering) => void;
}) {
  return (
    <div className="brand-list__field">
      <label className="brand-list__label" htmlFor="brand-list-sort">
        Sort by
      </label>
      <select
        id="brand-list-sort"
        className="brand-list__select"
        value={value}
        onChange={(event) => onChange(event.target.value as Ordering)}
      >
        {OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
