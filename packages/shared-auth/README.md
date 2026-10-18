# shared-auth

Code shared by the `web` and `auth` Django services: the token contract and
the token-verification / permission-check code the main app uses to protect
its write endpoint. See `docs/decisions.md` §8 for what belongs here.

## Modules, and why each is shared

| Module | Used by | Why it is here |
|---|---|---|
| `contract.py` | auth (issues) and web (verifies) | The algorithm, claim names, roles and permissions both sides must agree on, defined once so issuer and verifier cannot drift apart. |
| `tokens.py` (`verify_token`) | web | CHALLENGE.md requires the token-verification code in the shared library. Verification is pinned to RS256, issuer, audience and expiry. |
| `principal.py` (`Principal`) | web | The authenticated caller built from a verified token; the main app stores no users. |
| `drf.py` (optional, `shared-auth[drf]`) | web | The DRF authentication class and editor permission CHALLENGE.md asks for. It ships in every wheel but is only importable with Django and DRF installed; the core never imports it, and the `[drf]` extra declares those dependencies for consumers that use it (web). |

Not here: token signing and the private key (auth service only), and
anything about users, passwords or the database.

The core (`contract`, `tokens`, `principal`) is plain Python plus PyJWT, with
no Django dependency; install `shared-auth[drf]` for `drf.py`.

## Development

All commands run in Docker from the repository root:

```bash
make verify-fast   # includes this package's ruff, mypy (strict) and tests
make lib-release   # build the current version's wheel into wheels/
```

## Releasing

1. Bump `version` in `pyproject.toml`.
2. Run `make lib-release`. It builds `wheels/shared_auth-<version>-py3-none-any.whl`
   and refuses to overwrite a version that has already been released.
3. Each service upgrades on its own schedule by changing its pin
   (`shared-auth==<version>`) and running `make lock`.

A breaking change to the token contract ships expand-then-contract, verifier
(web) before issuer (auth): see "Shared library" in the repository README.
