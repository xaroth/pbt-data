"""Decides whether a new game patch needs a new or updated source.json.

Reads the latest game version (poe-tool-dev/latest-patch-version), the public Steam manifest
(steamcmd app_info_print output in --app-info), the recipes on main (poe1/*/source.json), the
league's open detect pull request, the newest dat-schema commit and the skilltree-export tags.
When a recipe should change it writes it to --out and reports, as GitHub outputs:

    action   none, new (first recipe of a league), update (new patch), retry (newer dat-schema
             for a failed build) or rerun (rerun a failed build once, its recipe unchanged)
    league   the league, such as 3.29
    branch   detect/poe1-<league>
    pr       the open pull request's number, empty when none
    run      the build run to rerun, for rerun
    title    a commit and pull request title

Every run logs why it did what it did. Failures to read a source exit non-zero.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

APP = "238960"
DEPOT = "238961"
GAME = "poe1"
LATEST_URL = "https://raw.githubusercontent.com/poe-tool-dev/latest-patch-version/main/latest.txt"
API = "https://api.github.com"
DAT_SCHEMA = "poe-tool-dev/dat-schema"
TREE_EXPORT = "grindinggear/skilltree-export"
BUILD_WORKFLOW = "build.yml"

VERSION = re.compile(r"\d+\.\d+\.\d+(\.\d+)*")
TREE_TAG = re.compile(r"(\d+)\.(\d+)\.(\d+)([a-z]*)")

Get = Callable[[str], bytes]


@dataclass(frozen=True)
class PR:
    number: int
    recipe: dict
    # Conclusion of the branch's latest build run: success, failure, pending, other or none.
    build: str
    run: int = 0
    attempt: int = 0


@dataclass(frozen=True)
class State:
    version: str
    manifest: str
    recipes: dict  # league -> source.json on main
    pr: PR | None  # the open detect pull request of the version's league
    dat_schema: str  # newest dat-schema commit
    tree_tags: list  # (name, commit) of skilltree-export


@dataclass(frozen=True)
class Decision:
    action: str
    league: str
    reason: str
    recipe: dict | None = None
    title: str = ""
    run: int = 0


def version_key(v: str) -> tuple:
    return tuple(int(p) for p in v.split("."))


def league_of(version: str) -> str:
    return ".".join(version.split(".")[:2])


def newest_tree_tag(tags: list, league: str) -> str | None:
    """The commit of league's newest skilltree-export tag; 3.27.0g is newer than 3.27.0."""
    best = None
    for name, commit in tags:
        m = TREE_TAG.fullmatch(name)
        if not m or f"{m[1]}.{m[2]}" != league:
            continue
        key = (int(m[3]), m[4])
        if best is None or key > best[0]:
            best = (key, commit)
    return best[1] if best else None


def decide(s: State) -> Decision:
    league = league_of(s.version)
    newest_league = max(s.recipes, key=version_key, default=None)
    if newest_league and version_key(league) < version_key(newest_league):
        return Decision("none", league, f"patch server reports {s.version}, older than league {newest_league}")
    current = s.pr.recipe if s.pr else s.recipes.get(league)
    known = {r["steamManifest"] for r in s.recipes.values()}
    if s.pr:
        known.add(s.pr.recipe["steamManifest"])

    if current and version_key(s.version) < version_key(current["version"]):
        return Decision("none", league, f"patch server reports {s.version}, older than {current['version']}")
    if current and s.version == current["version"]:
        reason = f"{s.version} is current"
        if s.manifest not in known:
            reason += f"; Steam manifest {s.manifest} is new without a new version, ignored"
        if not s.pr or s.pr.build != "failure":
            return Decision("none", league, reason)
        if s.dat_schema == current["datSchemaCommit"]:
            # A failure need not be the schema (Steam, network, runner): rerun once before waiting.
            if s.pr.attempt < 2:
                return Decision("rerun", league, f"build of #{s.pr.number} failed on the newest dat-schema; rerunning it once", run=s.pr.run)
            return Decision("none", league, f"build of #{s.pr.number} failed again; waiting for a dat-schema commit after {s.dat_schema[:7]}")
        recipe = {**current, "datSchemaCommit": s.dat_schema}
        recipe.pop("datSchemaNote", None)
        return Decision("retry", league, f"build of #{s.pr.number} failed; retrying with dat-schema {s.dat_schema[:7]}",
                        recipe, f"{GAME} {league}: {s.version}, dat-schema {s.dat_schema[:7]}")

    if s.manifest in known:
        return Decision("none", league, f"patch server reports {s.version}, Steam manifest {s.manifest} not updated yet; waiting")
    tree = newest_tree_tag(s.tree_tags, league)
    if tree is None:
        return Decision("none", league, f"no skilltree-export tag for {league} yet; waiting")
    recipe = {"version": s.version, "steamManifest": s.manifest, "datSchemaCommit": s.dat_schema, "treeExportCommit": tree}
    if current:
        return Decision("update", league, f"{current['version']} -> {s.version}", recipe, f"{GAME} {league}: {s.version}")
    return Decision("new", league, f"new league {league} at {s.version}", recipe, f"{GAME} {league}: {s.version}")


def parse_vdf(text: str, key: str) -> dict:
    """The object named key in Valve's text format, as steamcmd's app_info_print prints it."""
    m = re.search(rf'^\s*"{re.escape(key)}"\s*$', text, re.M)
    if not m:
        raise ValueError(f'no "{key}" in app info')
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text[m.end():])
    pos = 0

    def obj() -> dict:
        nonlocal pos
        if tokens[pos][1] != "{":
            raise ValueError("app info: expected {")
        pos += 1
        out = {}
        while tokens[pos][1] != "}":
            name = tokens[pos][0]
            pos += 1
            if tokens[pos][1] == "{":
                out[name] = obj()
            else:
                out[name] = tokens[pos][0]
                pos += 1
        pos += 1
        return out

    try:
        return obj()
    except IndexError:
        raise ValueError("app info ends early") from None


def public_manifest(app_info: str) -> str:
    """The public branch's manifest of the game depot."""
    try:
        public = parse_vdf(app_info, APP)["depots"][DEPOT]["manifests"]["public"]
    except KeyError as e:
        raise ValueError(f"app info has no public manifest of depot {DEPOT}: missing {e}") from None
    gid = public["gid"] if isinstance(public, dict) else public
    if not gid.isdigit():
        raise ValueError(f"app info: manifest {gid!r} is not a number")
    return gid


def http_get(url: str) -> bytes:
    headers = {"User-Agent": "pbt-data-detect"}
    if url.startswith(API):
        headers["Accept"] = "application/vnd.github.raw+json" if "/contents/" in url else "application/vnd.github+json"
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read()


def get_json(get: Get, url: str):
    return json.loads(get(url))


def read_state(get: Get, root: Path, repo: str, app_info: str) -> State:
    version = get(LATEST_URL).decode().strip()
    if not VERSION.fullmatch(version):
        raise ValueError(f"latest.txt: {version!r} is not a version")
    recipes = {p.parent.name: json.loads(p.read_text()) for p in sorted(root.glob(f"{GAME}/*/source.json"))}
    branch = f"detect/{GAME}-{league_of(version)}"
    pr = None
    pulls = get_json(get, f"{API}/repos/{repo}/pulls?state=open&head={repo.split('/')[0]}:{branch}")
    if pulls:
        number = pulls[0]["number"]
        path = f"{GAME}/{league_of(version)}/source.json"
        recipe = get_json(get, f"{API}/repos/{repo}/contents/{path}?ref={branch}")
        runs = get_json(get, f"{API}/repos/{repo}/actions/workflows/{BUILD_WORKFLOW}/runs?branch={branch}&per_page=1")["workflow_runs"]
        pr = PR(number, recipe, build_state(runs[0]), runs[0]["id"], runs[0]["run_attempt"]) if runs else PR(number, recipe, "none")
    dat_schema = get_json(get, f"{API}/repos/{DAT_SCHEMA}/commits?per_page=1")[0]["sha"]
    tags = []
    for page in range(1, 20):
        batch = get_json(get, f"{API}/repos/{TREE_EXPORT}/tags?per_page=100&page={page}")
        tags += [(t["name"], t["commit"]["sha"]) for t in batch]
        if len(batch) < 100:
            break
    return State(version, public_manifest(app_info), recipes, pr, dat_schema, tags)


def build_state(run: dict) -> str:
    if run["status"] != "completed":
        return "pending"
    return run["conclusion"] if run["conclusion"] in ("success", "failure") else "other"


def main(argv: list, get: Get = http_get) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--app-info", required=True, type=Path, help="steamcmd +app_info_print output")
    p.add_argument("--out", required=True, type=Path, help="where to write the new source.json")
    p.add_argument("--root", default=Path("."), type=Path, help="pbt-data checkout")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "xaroth/pbt-data"))
    args = p.parse_args(argv)

    state = read_state(get, args.root, args.repo, args.app_info.read_text())
    d = decide(state)
    print(f"{GAME} {d.league}: {d.action}: {d.reason}", file=sys.stderr)
    if d.recipe:
        args.out.write_text(json.dumps(d.recipe, indent=2) + "\n")
    outputs = {
        "action": d.action,
        "league": d.league,
        "branch": f"detect/{GAME}-{d.league}",
        "pr": str(state.pr.number) if state.pr else "",
        "title": d.title,
        "run": str(d.run or ""),
    }
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a") as f:
            f.writelines(f"{k}={v}\n" for k, v in outputs.items())
    else:
        print(json.dumps(outputs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
