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

Run the `build` workflow with a league (`gh workflow run build.yml -f league=3.29`). It reads `poe1/<league>/source.json`, downloads the bundles the build reads from Steam (depot manifest `steamManifest`, with the build account's secrets), builds `schema.json` at `datSchemaCommit`, fetches the tree export at `treeExportCommit`, runs pbt-extract at the commit pinned in the workflow (`PBT_EXTRACT`), and opens a pull request when the dataset changed. Merging it publishes.

To rebuild with a newer extractor, bump `PBT_EXTRACT` and run the workflow per league.

## Use

Read `index.json`. When a league's manifest hash differs from your copy, download its `manifest.json`, check it against that hash, then download the files whose SHA-256 differs from yours. `pbt data pull` in pbt-engine does this.

Raw URLs: `https://raw.githubusercontent.com/xaroth/pbt-data/<ref>/`, `main` for the latest data or a commit for a fixed snapshot.

## Status

Pre-release. The format and layout may change, and datasets are rebuilt when they do.

## Notice

See [NOTICE](NOTICE). This product isn't affiliated with or endorsed by Grinding Gear Games in any way.
