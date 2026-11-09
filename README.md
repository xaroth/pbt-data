# pbt-data

Path of Exile game data for [pbt-engine](https://github.com/xaroth/pbt-engine), built from the game files by [pbt-extract](https://github.com/xaroth/pbt-extract).

## Layout

```
index.json                          per game and league: the latest patch and the SHA-256 of its manifest.json
<game>/<league>/                    the latest patch's dataset: manifest.json and the files it lists
sources/<game>/<version>/           the recipe of every patch built: source.json (pbt-extract's input:
                                    Steam depot manifest, dat-schema commit, tree export commit and hashes)
                                    and schema.json (that dat-schema build)
scripts/add-version.sh              writes a recipe: add-version.sh <game> <version> <steam-manifest> <dat-schema-commit> <tree-export-tag>
```

`sources/*/*/schema.json` are builds of [dat-schema](https://github.com/poe-tool-dev/dat-schema), MIT licence, see [sources/LICENSE-dat-schema](sources/LICENSE-dat-schema).

One dataset per league, the latest patch. Earlier patches are in git history.

## Use

Read `index.json`. When a league's manifest hash differs from your copy, download its `manifest.json`, check it against that hash, then download the files whose SHA-256 differs from yours. `pbt data pull` in pbt-engine does this.

Raw URLs: `https://raw.githubusercontent.com/xaroth/pbt-data/<ref>/`, `main` for the latest data or a commit for a fixed snapshot.

## Status

Pre-release. The format and layout may change, and datasets are rebuilt when they do.

## Notice

See [NOTICE](NOTICE). This product isn't affiliated with or endorsed by Grinding Gear Games in any way.
