# pbt-data

Path of Exile game data for [pbt-engine](https://github.com/xaroth/pbt-engine), built from the game files by [pbt-extract](https://github.com/xaroth/pbt-extract).

## Layout

```
index.json              per game and league: the latest patch and the SHA-256 of its manifest.json
<game>/<league>/
  source.json           what the league's dataset is built from (see below)
  manifest.json, *.fb   the dataset of the latest patch
```

One dataset per league, the latest patch. Earlier patches are in git history.

`source.json` is the build recipe; CI reads it to fetch and prepare pbt-extract's input:

| Field | Pins |
|---|---|
| `version` | The game version (patch) |
| `steamManifest` | The game files: the manifest of Steam depot 238961 (app 238960) for that patch |
| `datSchemaCommit` | The table layout: a [dat-schema](https://github.com/poe-tool-dev/dat-schema) commit |
| `datSchemaNote` | Optional: why `datSchemaCommit` is not the newest commit that decodes the tables |
| `treeExportCommit` | The passive tree export: a [skilltree-export](https://github.com/grindinggear/skilltree-export) commit |

## Build

The `build` workflow builds datasets from `source.json`:

- On a pull request it builds every league whose `source.json` changed, or every league when the workflow or `scripts/` changed (such as a new `PBT_EXTRACT`, the pbt-extract commit it runs), and pushes the datasets and `index.json` onto the pull request. Merging publishes recipe and data together. A rebuild that changes nothing pushes nothing.
- Run by hand (`gh workflow run build.yml -f league=3.29`) it builds one league and opens a pull request when the dataset changed.

Per league it downloads the bundles a build reads from Steam (depot manifest `steamManifest`, with the build account's secrets), builds `schema.json` at `datSchemaCommit`, fetches the tree export at `treeExportCommit` and runs pbt-extract.

## Use

Read `index.json`. When a league's manifest hash differs from your copy, download its `manifest.json`, check it against that hash, then download the files whose SHA-256 differs from yours. `pbt data pull` in pbt-engine does this.

Raw URLs: `https://raw.githubusercontent.com/xaroth/pbt-data/<ref>/`, `main` for the latest data or a commit for a fixed snapshot.

## Status

Pre-release. The format and layout may change, and datasets are rebuilt when they do.

## Notice

See [NOTICE](NOTICE). This product isn't affiliated with or endorsed by Grinding Gear Games in any way.
