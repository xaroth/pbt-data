#!/usr/bin/env bash
# Adds sources/<game>/<version>/: source.json (the pbt-extract input recipe) and the dat-schema build.
# usage: scripts/add-version.sh <game> <version> <steam-manifest> <dat-schema-commit> <tree-export-tag>
# Needs git, node, npm and curl.
set -euo pipefail

if [[ $# -ne 5 ]]; then
	echo "usage: $0 <game> <version> <steam-manifest> <dat-schema-commit> <tree-export-tag>" >&2
	exit 2
fi
game=$1 version=$2 manifest=$3 commit=$4 tree=$5
case $game in
poe1) valid_for=1 ;;
poe2) valid_for=2 ;;
*) echo "unknown game $game" >&2; exit 2 ;;
esac

out=$(cd "$(dirname "$0")/.." && pwd)/sources/$game/$version
if [[ -e $out ]]; then
	echo "$out exists" >&2
	exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git clone -q --filter=blob:none https://github.com/poe-tool-dev/dat-schema.git "$work/dat-schema"
cd "$work/dat-schema"
git -c advice.detachedHead=false checkout -q "$commit"
full=$(git rev-parse HEAD)
npm ci --ignore-scripts --no-audit --no-fund --loglevel=error
npm exec --no -- tsc
node dist/cli.js >/dev/null

mkdir -p "$out"
# Older dat-schema commits write only the combined schema.min.json, so filter by game here.
node -e '
const fs = require("fs");
const [src, dst, bit] = process.argv.slice(1);
const s = JSON.parse(fs.readFileSync(src, "utf8"));
const keep = (e) => (e.validFor & Number(bit)) !== 0;
fs.writeFileSync(dst, JSON.stringify({ ...s, tables: s.tables.filter(keep), enumerations: s.enumerations.filter(keep) }));
' schema.min.json "$out/schema.json" "$valid_for"
export_repo=https://github.com/grindinggear/skilltree-export
tree_commit=$(git ls-remote "$export_repo" "refs/tags/$tree^{}" "refs/tags/$tree" | head -1 | cut -f1)
if [[ -z $tree_commit ]]; then
	echo "no tag $tree in $export_repo" >&2
	exit 1
fi
node -e '
const fs = require("fs");
const [out, game, version, manifest, schema, tag, treeCommit, ...sums] = process.argv.slice(1);
const source = {steamManifest: manifest, datSchemaCommit: schema, treeExport: tag, treeExportCommit: treeCommit};
const files = ["alternate.json", "data.json", "ruthless.json"];
files.forEach((f, i) => { source["treeExport/" + f] = sums[i]; });
fs.writeFileSync(out + "/source.json", JSON.stringify({game, version, source}, null, 2) + "\n");
' "$out" "$game" "$version" "$manifest" "$full" "$tree" "$tree_commit" \
	$(for f in alternate.json data.json ruthless.json; do
		curl -fsSL "https://raw.githubusercontent.com/grindinggear/skilltree-export/$tree_commit/$f" | sha256sum | cut -c1-64
	done)
echo "wrote $out"
