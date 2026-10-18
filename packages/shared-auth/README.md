# shared-auth

Code shared by the `web` and `auth` Django services: the token contract and
the token-verification / permission-check code the main app uses to protect
its write endpoint. See `docs/decisions.md` §8 for what belongs here.

The core is plain Python with no Django dependency. DRF integration will be
an optional part of the package.

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
