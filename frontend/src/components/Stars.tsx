/** One decimal place, rounding half up from the API's two-decimal value
 * (the same rule the server-rendered pages use). Works in integer hundredths
 * so binary floating point cannot round 1.15 down to 1.1. */
export function formatRating(value: number): string {
  const hundredths = Math.round(value * 100);
  return (Math.floor((hundredths + 5) / 10) / 10).toFixed(1);
}

/** Star rating, matching the server-rendered partials/stars.html. */
export function Stars({
  rating,
  showValue = true,
}: {
  rating: number;
  showValue?: boolean;
}) {
  const value = Math.max(0, Math.min(5, rating));
  const full = Math.floor(value);
  const label = formatRating(value);
  return (
    <span className="stars" role="img" aria-label={`Rated ${label} out of 5`}>
      {Array.from({ length: full }, (_, i) => (
        <span
          key={`full-${i}`}
          className="stars__star stars__star--full"
          aria-hidden="true"
        >
          ★
        </span>
      ))}
      {Array.from({ length: 5 - full }, (_, i) => (
        <span
          key={`empty-${i}`}
          className="stars__star stars__star--empty"
          aria-hidden="true"
        >
          ☆
        </span>
      ))}
      {showValue && (
        <span className="stars__value" aria-hidden="true">
          {label}
        </span>
      )}
    </span>
  );
}
