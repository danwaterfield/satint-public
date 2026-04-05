# Deployment

## GitHub Pages

This repo's public site is deployed by **GitHub Pages legacy branch publishing**.

Verified on **2026-04-05** via:

```bash
gh api repos/danwaterfield/satint-public/pages
```

The live configuration returned:

- `build_type`: `legacy`
- `source.branch`: `main`
- `source.path`: `/docs`
- `html_url`: `https://danwaterfield.github.io/satint-public/`

### What this means

- There is **no deployment workflow** to run in GitHub Actions.
- There is **no `gh-pages` branch**.
- GitHub Pages publishes whatever is committed under [`/docs`](/Users/danielwaterfield/Documents/iran_satellite/docs) on the `main` branch.
- A normal push to `main` triggers Pages to rebuild the public site from that directory.

The old CI workflow was removed in commit `56fcf7b`:

> `chore: remove export-data workflow — Pages deploys from local push`

That workflow was failing because static export depends on the local database and live data, not an empty CI environment.

## Local To Public Chain

The deployment path is:

1. Local refresh populates the database.
2. [`refresh_intelligence`](/Users/danielwaterfield/Documents/iran_satellite/pipeline/management/commands/refresh_intelligence.py) runs [`export_static`](/Users/danielwaterfield/Documents/iran_satellite/pipeline/management/commands/export_static.py) unless `--skip-export` is used.
3. [`export_static`](/Users/danielwaterfield/Documents/iran_satellite/pipeline/management/commands/export_static.py) writes the publishable JSON payloads into [`docs/data/`](/Users/danielwaterfield/Documents/iran_satellite/docs/data).
4. [`docs/index.html`](/Users/danielwaterfield/Documents/iran_satellite/docs/index.html) fetches those relative `data/*.json` files at runtime.
5. GitHub Pages serves the committed [`docs/`](/Users/danielwaterfield/Documents/iran_satellite/docs) tree from `main`.

This is why the public dashboard updates only when the generated files under [`docs/`](/Users/danielwaterfield/Documents/iran_satellite/docs) are committed and pushed.

## Deployment Steps

### Standard refresh + deploy

1. Refresh the local intelligence data and exports.

```bash
./satint/bin/python manage.py refresh_intelligence
```

For a quicker operator pass that skips the slowest sources:

```bash
./satint/bin/python manage.py refresh_intelligence --fast
```

2. Verify the export stamp in [`docs/data/meta.json`](/Users/danielwaterfield/Documents/iran_satellite/docs/data/meta.json).

```bash
python3 - <<'PY'
import json
from pathlib import Path
meta = json.loads(Path("docs/data/meta.json").read_text())
print(meta["generated_at"])
print(meta["freshness"])
PY
```

3. Commit the updated `docs/` artifacts.

```bash
git add docs/
git commit -m "data: refresh GitHub Pages export for YYYY-MM-DD"
```

4. Push to `main`.

```bash
git push origin main
```

5. Wait for GitHub Pages to rebuild and then verify the public metadata:

```bash
curl https://danwaterfield.github.io/satint-public/data/meta.json
```

For a tighter local-vs-public check:

```bash
python3 - <<'PY'
import json
from pathlib import Path
print("local ", json.loads(Path("docs/data/meta.json").read_text())["generated_at"])
PY
curl -s https://danwaterfield.github.io/satint-public/data/meta.json | python3 -c 'import json,sys; print("public", json.load(sys.stdin)["generated_at"])'
```

## Important Notes

- [`docs/.nojekyll`](/Users/danielwaterfield/Documents/iran_satellite/docs/.nojekyll) should remain present so Pages serves the static directory without Jekyll processing.
- The public site can be stale even when local exports are current if the refreshed `docs/` tree has not been pushed.
- Updating database-backed exports locally is the critical step; **pushing source code alone does not update the site** unless the generated files in `docs/` changed and were committed.
- Running [`refresh_intelligence`](/Users/danielwaterfield/Documents/iran_satellite/pipeline/management/commands/refresh_intelligence.py) with `--skip-export` refreshes the database but does not produce new GitHub Pages artifacts.
- Running [`export_static`](/Users/danielwaterfield/Documents/iran_satellite/pipeline/management/commands/export_static.py) locally without a subsequent commit and push also leaves the public site unchanged.
- War-risk premium data is currently curated locally and synced with:

```bash
./satint/bin/python manage.py ingest_war_risk
```

- If you need to confirm the current Pages source again in future:

```bash
gh api repos/danwaterfield/satint-public/pages
```
