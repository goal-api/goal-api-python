# Releasing

All five GOAL API SDKs share one version number, so `1.4.0` means the same surface in
every language. Bump this repo in step with the others.

```bash
# 1. Bump the version in `pyproject.toml`.
# 2. Add the CHANGELOG.md entry, then commit.
git commit -am "release 1.1.0"
git push

# 3. Tag it. The publish workflow refuses to run if the tag and the
#    committed version disagree.
git tag v1.1.0
git push --tags
```

To rehearse, run the `publish` workflow manually with `dry_run: true`: it builds,
validates and packs, then stops before uploading.

## One-time setup

### PyPI trusted publishing

On pypi.org go to Your projects, then this project, then Publishing (or "Pending
publisher" if the name is not claimed yet), and add:

- Owner: `goal-api`, repository: `goal-api-python`
- Workflow: `publish.yml`
- Environment: `pypi`

After that there is no `PYPI_API_TOKEN` to store or rotate.

## Build tooling

`pyproject.toml` uses PEP 639 licence metadata: `license = "MIT"` as an SPDX expression plus
`license-files`, which emits `Metadata-Version: 2.4` and bundles LICENSE into the wheel's
`dist-info/licenses/`.

That needs a recent toolchain, which the publish workflow installs fresh each run:

| Tool | Minimum |
|---|---|
| `hatchling` | 1.27 |
| `build` | 1.2 |
| `twine` | 6.1 |

The deprecated `License :: OSI Approved :: MIT License` classifier is deliberately absent:
PyPI rejects a package that declares both an SPDX expression and a licence classifier.

## Package name

> The registry name in this repo is a placeholder pending confirmation. Check you own the
> namespace before the first publish; renaming after release is disruptive.

## Secrets

| Name | Environment | Needed for |
|---|---|---|
| `GOAL_API_KEY` | `live-api` | The live tests. They skip without it. |

No other secrets: PyPI uses OIDC.
