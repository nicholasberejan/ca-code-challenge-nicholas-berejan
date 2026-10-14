# Architecture Decisions

## 1. Schema Modeling

TBD

## 2. WordPress Postmeta Strategy

TBD

## 3. Migration Strategy

TBD

## 4. Brand API Contract

- Top Comment: Claude recommended a simple "highest rated review" as the top comment (because it is simple, deterministic, and easy to document), but this bias towards the brand seems inappropriate for a platform servicing both brands and consumers. I have decided to use the most representative review, determined by the review closest to the brand's mean rating, with tie breaking using "The Price Is Right" rules (closet to mean without going over, so err on the lower rating), then to most recent, then to WordPress ID.

## 5. React Component and State

TBD

## 6. SCSS Architecture

TBD

## 7. Authentication Service Boundary

TBD

## 8. Shared Library

TBD