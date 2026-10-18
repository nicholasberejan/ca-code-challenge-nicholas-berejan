import type { Brand } from "../api";
import { Stars } from "./Stars";

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** One brand from the API. All values are rendered as text. */
export function BrandCard({ brand }: { brand: Brand }) {
  const industries = [...brand.industries].sort((a, b) =>
    a.name.localeCompare(b.name),
  );
  const top = brand.top_review;

  return (
    <article className="card">
      {industries.length > 0 && (
        <ul className="badge-list" aria-label="Industries">
          {industries.map((industry) => (
            <li key={industry.slug} className="badge">
              {industry.name}
            </li>
          ))}
        </ul>
      )}
      <h3 className="card__title">
        <a className="card__title-link" href={`/brand/${brand.slug}/`}>
          {brand.name}
        </a>
      </h3>
      {brand.average_rating === null ? (
        <p className="card__meta">No reviews yet</p>
      ) : (
        <p className="card__meta">
          <Stars rating={brand.average_rating} />
          <span className="stars__count">
            ({plural(brand.review_count, "review")})
          </span>
        </p>
      )}
      <p className="card__excerpt">{brand.short_description}</p>
      {top && (
        <div className="card__quote">
          <p className="card__quote-title">
            Top review: <a href={`/review/${top.slug}/`}>{top.title}</a>
          </p>
          <p className="card__excerpt">{top.snippet}</p>
          <p className="card__meta">
            {top.reviewer_name}, rated {top.rating} out of 5
          </p>
        </div>
      )}
    </article>
  );
}
