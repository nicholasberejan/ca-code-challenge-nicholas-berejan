# Architecture Decisions

## 1. Schema Modeling

- Reviewer location: I initially thought the seed data suggested a design flaw wherein the review owned the location, as opposed to the reviewer, however after looking closer I see one brand (SwiftStream, an ISP) being reviewed indicates regional service, so it does make sense that the review would be for that area where it was used, not the Reviewer's current location. I have decided to keep the location on the Review model as a result.
- Reviewer's also have a display_name field, while in the WordPress data the Review also has a reviewer_name field. I believe the intention here is that a review can be created with a reviewer name that might differ from the author `display_name` of the post (like if another user is entering a review on behalf of someone else). However, in the seed data there are no reviews with reviewer_name that differs from their author's display_name. I am going to have the Reviewer's display_name show on all reviews for consistency and forgo the Review's "reviewer_name" field, since the name can be accessed by the Foreign Key to the Reviewer (we will use `select_related` to efficiently include the FK relation when querying reviews.) We could always add a byline to the Review model in the future if we want users to be able to submit reviews on behalf of others.
- WordPress allows a brand to have more than one industry, although the seed data has no examples where any brand has more than one industry. I have decided the django app will also support more than one industry for a brand so that this functionality can be included in future updates. We wil make a M2M relation to the Industry model for Brands.

## 2. WordPress Postmeta Strategy

TBD

## 3. Migration Strategy

- administrator becomes editor, subscriber becomes reader

## 4. Brand API Contract

- Top Comment: Claude recommended a simple "highest rated review" as the top comment (because it is simple, deterministic, and easy to document), but this bias towards the brand seems inappropriate for a platform servicing both brands and consumers. I have decided to use the most representative review, determined by the review closest to the brand's mean rating, with tie breaking using "The Price Is Right" rules (closet to mean without going over, so err on the lower rating), then to most recent, then to WordPress ID.

## 5. React Component and State

TBD

## 6. SCSS Architecture

TBD

## 7. Authentication Service Boundary

- Auth service is responsible for user accounts (login names, active status), credentials, roles/permissions, processing login (checking credentials and active status), token refresh/revocation, and user import. The main app verifies the token through the shared library, never seeing passwords or refresh tokens.
- local token verification vs. calls to auth service: given the scope of the app (traffic is small, reads are public, only one protected endpoint for PATCHing the brand's short description) I have decided on a short-lived access token, refreshed with a longer lived refresh token (this will prevent users from having to log in every ~five minutes)
- to account for any nefarious editing done by recently demoted editors, I am including a simple audit log that traces who made the edit and what was changed, so such actions can be undone.
- passwords will carry over from WordPress, and a hasher built and included in the auth service. We can test this against known seed data hashes because we know the plain text values of the passwords. Users will not have to change/reset their passwords and log in should be seamless from WordPress. Once logged in, Django will re-hashes the password with it's own algorithm.

## 8. Shared Library

- Contains core code (claims, permissions, verify) as plain python plus PyJWT, no Django
- DRF classes in a submodule, offered as an optional install. The auth service installs only the core since it does not utilize DRF, the main app installs the core plus the DRF classes it will use.

## 9. Additional Considerations

- Claude requested clarification as to where the filter options are obtained, giving options such as "hard code in to the front end select component" and "derive from the GET response" but as it correctly pointed out, the former makes updates tedious while the latter does not guarantee all five current extant induestries are present in the first page of the paginated response. I decided instead to add a simple GET endpoint to serve the Industry objects from the django database and use the response to populate the select options.