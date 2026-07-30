# Third-party notices

This package is MIT licensed. It pulls in the dependencies below at runtime, each under its
own licence. Nothing here is vendored: pip fetches them, and each ships its own licence
text.

## Direct

| Package | Licence | Why |
|---|---|---|
| [httpx](https://github.com/encode/httpx) | BSD-3-Clause | The HTTP client. Chosen because one library covers both the sync and async transports. |

## Optional, via the `live` extra

| Package | Licence | Why |
|---|---|---|
| [websockets](https://github.com/python-websockets/websockets) | BSD-3-Clause | The live match feed. Only installed with `pip install "goal-api[live]"`. |

## Transitive, pulled in by httpx

| Package | Licence |
|---|---|
| httpcore | BSD-3-Clause |
| h11 | MIT |
| anyio | MIT |
| sniffio | MIT / Apache-2.0 |
| idna | BSD-3-Clause |
| **certifi** | **MPL-2.0** |

> `certifi` is Mozilla Public License 2.0, which is weak copyleft rather than permissive
> like everything else here. It carries the CA bundle and is unmodified, so using it
> imposes no obligation on your own code. Flagged because some licence policies treat MPL
> as review-worthy, and it arrives indirectly rather than from anything this SDK asks for.

## Development only

Not installed for consumers, and not part of any published artifact: `pytest` (MIT),
`pytest-asyncio` (Apache-2.0), `build` (MIT), `twine` (Apache-2.0).

## Checking this yourself

```bash
pip install pip-licenses && pip-licenses --from=mixed --with-urls
```

Versions move, so treat the table above as the shape rather than the current truth.
