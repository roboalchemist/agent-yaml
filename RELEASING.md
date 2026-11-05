# Releasing

Releases are cut from tags. A tag push runs `.github/workflows/release.yml`, which builds the sdist
and wheel, checks the metadata, verifies the tag matches `pyproject.toml`, publishes to PyPI, and
creates a GitHub release.

## One-time PyPI setup

The publish step authenticates with the `PYPI_API_TOKEN` repository secret. The value is the upload
token stored in the 1Password item **PyPi** in the **Agents** vault (field `Upload Token`), set with:

```bash
op read "op://Agents/iqgk2lpkje23sl57givoy7a2jy/l3d67zx6gij7mtgh3ndkyyvwia" --no-newline \
  | gh secret set PYPI_API_TOKEN
```

The `pypi` environment exists and is attached to the publish job. Adding required reviewers there is
optional and recommended.

### Moving to trusted publishing

Trusted publishing removes the stored token. On PyPI, add a pending publisher for the project:

- PyPI project name: `agent-yaml`
- Owner: `roboalchemist`
- Repository: `agent-yaml`
- Workflow name: `release.yml`
- Environment name: `pypi`

Then delete the `password:` line from the publish step and remove the `PYPI_API_TOKEN` secret. The
job already carries `id-token: write`, so OIDC works without further changes.

## Cutting a release

1. Bump `version` in `pyproject.toml` and move the changelog entries out of `Unreleased`.
2. Commit and push `main`.
3. Tag and push the tag:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. Watch the run at **Actions, Release**. The publish job fails if the tag and the package version
   disagree, so a typo stops before anything reaches PyPI.

## Checking the build without publishing

Run the Release workflow manually from **Actions, Release, Run workflow**. On a manual run the build
job runs and the publish and release jobs are skipped, which catches packaging errors without
touching PyPI.

The same checks locally:

```bash
pip install build twine
python -m build
python -m twine check dist/*
```
