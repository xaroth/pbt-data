# pbt-data

Path of Exile game data for [pbt-engine](https://github.com/xaroth/pbt-engine), built from the game files by [pbt-extract](https://github.com/xaroth/pbt-extract). This repository holds the recipes, the scripts and CI; CI publishes what it builds to `https://pbt-data.xaroth.nl/`.

## Bucket

Every dataset and its art (the passive tree's sprite sheets and the class and ascendancy faces), addressed by content:

| Path | Holds | Changes |
|---|---|---|
| `blobs/<sha256>` | Every dataset file and art file, by its SHA-256 | Never |
| `manifests/<id>.json` | A dataset's `manifest.json`, by its dataset id | Never |
| `manifests/<sha256>.json` | An art manifest, by its own SHA-256 | Never |
| `index.json` | Per game and league: the latest `version`, its dataset `format`, its `dataset` id and its `art` manifest | On every publish |

```json
{"poe1": {"3.29": {"version": "3.29.3.6", "format": 1, "dataset": "f9bfe4de…", "art": "e7d429be…"}}}
```

`format` is the `format` of the entry's dataset manifest: the version of the dataset's layout, which also covers the shape of its art manifest. A reader opens the latest of a league only when it reads that format, and otherwise keeps the dataset it pins. The format stays 1 until v1.0 is live, so until then it tells readers nothing: a dataset an older reader cannot read fails when it is opened, and one it reads wrongly is not caught.

A dataset manifest lists each file by name with its size and SHA-256. Its `id` is the SHA-256 of the game, the version, the capabilities and every file's name and hash (pbt-engine's `dataset` package computes it), so a manifest can be checked against the id it was fetched by. Per language a dataset holds `text-<lang>.fb`, with stat description templates and display names, and beside it `names-<lang>.fb`, with only the character, ascendancy and node names, so a reader that shows names fetches the small file alone.

Each tree of a dataset lists the game's node overrides, tattoos and runegrafts, each with its id, kind, the nodes it may replace, its icon and its stats; their names are in both language files. Every tree of a league gets the same list. 3.27's game files do not say which nodes an override may not replace, so its overrides list no excluded nodes. Overrides that are unused or incomplete in the game files are left out, and the build warns about each one.

Each character lists its unarmed damage and attack time. An item mod lists the skills it grants, each as granted effect and level, and the skills it grants in Ruthless where the game gives it others. A node lists the skill it grants; the ruthless tree holds the ruthless grant of each node. A granted skill's levels are in the skills group.

Each tree of a dataset holds the jewel lists, the same in every tree of a league:

- Jewel radii, by name and distance.
- Cluster jewels: the sockets that take one, with size, index, proxy node and parent socket; each size's node layout; the small passive kinds; and the notables and keystones a jewel mod adds, keyed by its stat.
- Timeless jewels: the alternate tree versions, in game row order, each with its replacement passives and added stats. The Abyss versions are left out. Each replacement passive's name is in the language files, keyed by its id.

The art manifest lists each art file the same way, and per sprite kind (such as `normalActive`) one sheet per zoom level with the rectangle of each icon, keyed by the art path the layouts name. A node's icon is on the `keystoneActive`/`keystoneInactive`, `notable…`, `mastery` or `normal…` sheets by its kind; a mastery's other art on `masteryInactive`, `masteryConnected`, `masteryActiveSelected` and `masteryActiveEffect`; group backgrounds on `groupBackground`. The build fails when a layout names art the sheets lack. Class illustrations are not in the export and have no entry. The sheets and their layout are GGG's, from [skilltree-export](https://github.com/grindinggear/skilltree-export).

`classFaces` maps each base class's character id (such as `Metadata/Characters/Str/Str`) to the image of its face plate, cut from the game's UI art. Every character in the league's `Characters` table has one; the build fails otherwise.

`ascendancyFaces` maps each ascendancy id of the standard tree's classes (such as `Raider`, the Warden) to the image of its face plate, `ascendancy-<id>.webp`, from the same UI art. An ascendancy without a face is left out with a warning; with 3.29's game files all 21 have one.

Blobs and manifests are uploaded before the `index.json` that names them, so a reader never sees a dataset in part. CI never overwrites or deletes a blob or manifest; a rebuild that changes nothing uploads nothing and leaves `index.json` as it is. Blobs and manifests are cached forever. `index.json` is cached at the edge, purged on every publish, and revalidated by browsers.

### Use

- The latest of a league: read `index.json`, check its `format`, then fetch `manifests/<dataset>.json` and `manifests/<art>.json`.
- A fixed dataset: pin its id and fetch `manifests/<id>.json`; a published id never changes or goes away through CI. Pin art by its manifest's SHA-256 the same way.
- Then fetch each listed file from `blobs/<sha256>` and check it against that hash. A file you already hold with the same hash needs no download.

`python3 scripts/bucket.py verify https://pbt-data.xaroth.nl` downloads everything `index.json` names and checks every hash.

## Recipes

```
<game>/<league>/source.json   what the league's dataset is built from
```

One dataset per league, the latest patch. Earlier datasets stay in the bucket under their ids.

`source.json` is the build recipe; CI reads it to fetch and prepare pbt-extract's input:

| Field | Pins |
|---|---|
| `version` | The game version (patch) |
| `steamManifest` | The game files: the manifest of Steam depot 238961 (app 238960) for that patch |
| `datSchemaCommit` | The table layout: a [dat-schema](https://github.com/poe-tool-dev/dat-schema) commit |
| `datSchemaNote` | Optional: why `datSchemaCommit` is not the newest commit that decodes the tables |
| `treeExportCommit` | The passive tree export: a [skilltree-export](https://github.com/grindinggear/skilltree-export) commit |

## Build

The `build` workflow builds each league's dataset and art from `source.json`, then checks that every file each manifest lists is there with its size and SHA-256. It builds every league whose `source.json` changed, or every league when the workflow, `scripts/steam-code.py` or `scripts/bucket.py` changed (such as a new `PBT_EXTRACT`, the pbt-extract commit it runs).

- On a pull request it builds and checks, and publishes nothing.
- On `main` it builds the same leagues and publishes them with `scripts/bucket.py publish`: blobs, then manifests, then `index.json`, then one purge of `index.json` from the cache. It then downloads what it published through `https://pbt-data.xaroth.nl/` and checks every hash. Secrets: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `CLOUDFLARE_PURGE_TOKEN`, `CLOUDFLARE_ZONE_ID`.
- Run by hand (`gh workflow run build.yml -f league=3.29`, or without `league` for every league) it builds and checks, and publishes when run on `main`.

Per league it downloads the bundles a build reads: from the CDN (`patch.poecdn.com/<version>/`, no login) when it still serves the version, which it does only for the live patch; otherwise, or when a CDN download fails partway, from Steam (depot manifest `steamManifest`, with the build account's secrets). It then builds `schema.json` at `datSchemaCommit`, fetches the tree export (its JSON and `assets/`) at `treeExportCommit` and runs pbt-extract, which writes the dataset and the art. The bundles it downloads include the game's UI art the class faces are cut from.

Each league's job summary lists pbt-extract's warnings (`scripts/extract_warnings.py`): a table of each kind with its count, where warnings that differ only in the item they name count as one kind, and the full list below it. Content pbt-extract leaves out, such as removed item bases or mods no kept base rolls, shows there with its count before a merge publishes it. A warning does not fail the build.

## Detect

The `detect` workflow runs hourly (and by hand with `gh workflow run detect.yml`). `scripts/detect.py` compares the latest game version ([latest-patch-version](https://github.com/poe-tool-dev/latest-patch-version)) and Steam's public manifest (anonymous app info, no account) with the recipes and the league's open `detect/poe1-<league>` pull request:

- A new patch with a new Steam manifest: writes the league's `source.json` (newest dat-schema commit, newest skilltree-export tag of the league) and pushes it to `detect/poe1-<league>`, opening its pull request when none is open. `build` then checks that it builds; merging publishes it.
- A newer skilltree-export tag of the league (such as `3.29.1` after `3.29.0`) at the same version: moves `treeExportCommit` in the league's `source.json` the same way.
- A new version whose Steam manifest has not changed yet, or a new league without a skilltree-export tag: waits for the next run.
- The pull request's build failed: moves `datSchemaCommit` to a newer dat-schema commit when there is one, which builds again. Otherwise reruns the build once, since the cause may be Steam or the network, then waits for a newer dat-schema commit.

When there is something to push, it mints a token of the `xaroth-actions-helper` App (`APP_ID`, `APP_PRIVATE_KEY`) and pushes with it, so `build` runs on its pushes. Nothing merges automatically. On a pull request that changes detection it runs without pushing.

## Status

Pre-release. The format and layout may change, and datasets are rebuilt when they do.

## Notice

See [NOTICE](NOTICE). This product isn't affiliated with or endorsed by Grinding Gear Games in any way.
