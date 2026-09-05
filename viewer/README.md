# PureLab viewer

PureLab is the browser app for exploring the solver's output: the ranked builds and knockout kits for one combat level, with filters, a column picker, a detail panel and a glossary. It is a React 19 app built with [vinext](https://www.npmjs.com/package/vinext) (Next.js-style routing on Vite) and runs entirely on your machine. Nothing is hosted anywhere. [docs/viewer.md](../docs/viewer.md) is a tour of the screen and the columns.

## Run it locally

Needs Node 22.13+ and Python 3.11+. Rust and the pipeline are not required; the datasets are downloaded from a GitHub release.

```bash
cd viewer
npm ci
python scripts/fetch_data.py        # ~56 MB of gzipped datasets into public/data/
npm run dev                         # http://localhost:3000
```

The dev server serves the datasets straight from `public/data`. `fetch_data.py --level 40` downloads one level only, `--tag` picks a different dataset release, and `GITHUB_TOKEN` (or `GH_TOKEN`) is optional: set it to avoid the unauthenticated GitHub API rate limit.

## Regenerate the datasets

After a pipeline run (see [docs/pipeline.md](../docs/pipeline.md)), export the ranked CSVs into the compact dictionary-encoded JSON the viewer loads:

```bash
python scripts/export_build_data.py 40          # writes public/data/builds-40.json(.gz) and kits-40.json(.gz)
python scripts/export_build_data.py 30 0        # cap 0 = every kit (the default cap is 250,000)
```

The viewer reads the `.json` files; the `.gz` copies are what gets attached to a release. `public/data/` is git-ignored. To publish a new snapshot, attach the four `*.json.gz` files to a GitHub release and bump `DEFAULT_TAG` in `scripts/fetch_data.py`.

## Checks and build

```bash
npx oxlint            # lint
npx tsc --noEmit      # type check
npm test              # unit tests for the pure helpers under lib/
npm run build         # production build into dist/
npm start             # serve the production build locally
```

CI runs the first four.

## Layout

```text
viewer/
├── app/            layout, page and global styles
├── components/     tables, filters, detail panel, glossary, KO-switch panel, UI primitives
├── hooks/          dataset loading
├── lib/            dataset decoding, filtering, helpers
├── public/         favicon, Open Graph image, git-ignored data/
└── scripts/        fetch_data.py, export_build_data.py
```
