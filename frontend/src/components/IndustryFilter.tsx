import type { Industry } from "../api";
import type { IndustriesStatus } from "../hooks/useIndustries";

export function IndustryFilter({
  value,
  industries,
  status,
  onChange,
  onRetry,
}: {
  value: string | null;
  industries: Industry[];
  status: IndustriesStatus;
  onChange: (industry: string | null) => void;
  onRetry: () => void;
}) {
  return (
    <div className="brand-list__field">
      <label className="brand-list__label" htmlFor="brand-list-industry">
        Industry
      </label>
      <select
        id="brand-list-industry"
        className="brand-list__select"
        value={value ?? ""}
        disabled={status === "loading"}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">All industries</option>
        {industries.map((industry) => (
          <option key={industry.slug} value={industry.slug}>
            {industry.name}
          </option>
        ))}
      </select>
      {status === "error" && (
        <p className="brand-list__hint">
          Industries could not be loaded.{" "}
          <button type="button" className="button" onClick={onRetry}>
            Retry industries
          </button>
        </p>
      )}
    </div>
  );
}
