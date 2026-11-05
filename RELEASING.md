# Releasing

Releases are cut from tags. A tag push runs `.github/workflows/release.yml`, which builds the sdist
and wheel, checks the metadata, verifies the tag matches `pyproject.toml`, publishes to PyPI, and
creates a GitHub release.

## One-time PyPI setup

The workflow publishes with PyPI trusted publishing, so there is no API token in the repository.

1. Sign in to PyPI and open **Publishing**, then add a pending publisher for a new project:
   - PyPI project name: `agent-yaml`
   - Owner: `roboalchemist`
   - Repository: `agent-yaml`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. In the GitHub repository, create the `pypi` environment under **Settings, Environments**. Adding
   required reviewers is optional and recommended.

After the first successful publish the pending publisher becomes a normal publisher, and later tags
publish without changes.

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
