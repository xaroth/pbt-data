#!/usr/bin/env python3
"""Checks built datasets and tree art, publishes them to the bucket and verifies what it serves.

A build directory holds one folder per league:

    <league>/manifest.json, the files it lists
    <league>/art/manifest.json, the files it lists

The bucket is addressed by content:

    blobs/<sha256>          every dataset and art file
    manifests/<id>.json     a dataset manifest, by its dataset id
    manifests/<sha256>.json an art manifest, by its own SHA-256
    index.json              per game and league: version, dataset id, art manifest

Commands:

    check DIR      every file each manifest lists is in DIR with its size and SHA-256
    publish DIR    check, then upload what the bucket lacks: blobs, then manifests, then
                   index.json. Never overwrites a blob or manifest. Needs R2_ACCOUNT_ID,
                   R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_BUCKET; boto3.
    verify URL [DIR]
                   download every file the index at URL names and check each against its
                   SHA-256; with DIR, the index must name DIR's leagues as built, and only
                   those are checked
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

INDEX = "index.json"
IMMUTABLE = "public, max-age=31536000, immutable"
CONTENT_TYPES = {".png": "image/png", ".webp": "image/webp", ".json": "application/json"}


class Invalid(Exception):
    pass


@dataclass
class Object:
    key: str
    path: Path
    content_type: str


@dataclass
class League:
    game: str
    name: str
    version: str
    dataset: str
    art: str
    blobs: list[Object]
    manifests: list[Object]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_type(name: str) -> str:
    return CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream")


def blobs(manifest: Path) -> list[Object]:
    """The files manifest lists, each checked against its size and SHA-256."""
    out = []
    for f in json.loads(manifest.read_bytes())["files"]:
        path = manifest.parent / f["name"]
        if not path.is_file():
            raise Invalid(f"{path}: listed in {manifest.name} but missing")
        if path.stat().st_size != f["size"]:
            raise Invalid(f"{path}: {path.stat().st_size} bytes, manifest says {f['size']}")
        if sha256(path) != f["sha256"]:
            raise Invalid(f"{path}: SHA-256 differs from {manifest}")
        out.append(Object(f"blobs/{f['sha256']}", path, content_type(f["name"])))
    return out


def league(dir: Path) -> League:
    dataset_manifest = dir / "manifest.json"
    art_manifest = dir / "art" / "manifest.json"
    for m in (dataset_manifest, art_manifest):
        if not m.is_file():
            raise Invalid(f"{m}: missing")
    m = json.loads(dataset_manifest.read_bytes())
    art = sha256(art_manifest)
    return League(
        game=m["game"],
        name=dir.name,
        version=m["version"],
        dataset=m["id"],
        art=art,
        blobs=blobs(dataset_manifest) + blobs(art_manifest),
        manifests=[
            Object(f"manifests/{m['id']}.json", dataset_manifest, "application/json"),
            Object(f"manifests/{art}.json", art_manifest, "application/json"),
        ],
    )


def leagues(build: Path) -> list[League]:
    dirs = sorted(d for d in build.iterdir() if d.is_dir())
    if not dirs:
        raise Invalid(f"{build}: no leagues")
    return [league(d) for d in dirs]


def index_bytes(index: dict) -> bytes:
    return (json.dumps(index, indent=2, sort_keys=True) + "\n").encode()


def updated_index(current: bytes | None, built: list[League]) -> bytes:
    """current with each built league's entry replaced; other leagues are kept."""
    index = json.loads(current) if current else {}
    for lg in built:
        index.setdefault(lg.game, {})[lg.name] = {"version": lg.version, "dataset": lg.dataset, "art": lg.art}
    return index_bytes(index)


class Bucket(Protocol):
    def keys(self, prefix: str) -> set[str]: ...
    def get(self, key: str) -> bytes | None: ...
    # create=True must fail rather than replace an existing object.
    def put(self, key: str, body: bytes, content_type: str, cache_control: str | None, create: bool) -> None: ...


@dataclass
class Result:
    uploaded: list[str] = field(default_factory=list)
    index_changed: bool = False


def publish(bucket: Bucket, built: list[League], log=print) -> Result:
    """Uploads blobs, then manifests, then index.json, so a reader never sees a manifest
    whose files are missing or an index whose manifest is missing."""
    result = Result()
    for prefix, objects in (("blobs/", [b for lg in built for b in lg.blobs]), ("manifests/", [m for lg in built for m in lg.manifests])):
        have = bucket.keys(prefix)
        for o in objects:
            if o.key in have:
                continue
            bucket.put(o.key, o.path.read_bytes(), o.content_type, IMMUTABLE, create=True)
            have.add(o.key)
            result.uploaded.append(o.key)
            log(f"uploaded {o.key} ({o.path})")
    current = bucket.get(INDEX)
    index = updated_index(current, built)
    if index != current:
        # No Cache-Control: the zone's cache rule sets index.json's lifetimes.
        bucket.put(INDEX, index, "application/json", None, create=False)
        result.index_changed = True
    log(f"{len(result.uploaded)} objects uploaded; index.json {'updated' if result.index_changed else 'unchanged'}")
    return result


class R2:
    def __init__(self, account: str, key_id: str, secret: str, bucket: str):
        import boto3
        from botocore.config import Config

        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("R2_ENDPOINT") or f"https://{account}.r2.cloudflarestorage.com",
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name="auto",
            config=Config(retries={"max_attempts": 5, "mode": "standard"}),
        )
        self.bucket = bucket

    def keys(self, prefix: str) -> set[str]:
        out = set()
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            out.update(o["Key"] for o in page.get("Contents", []))
        return out

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def put(self, key: str, body: bytes, content_type: str, cache_control: str | None, create: bool) -> None:
        args = {"Bucket": self.bucket, "Key": key, "Body": body, "ContentType": content_type}
        if cache_control:
            args["CacheControl"] = cache_control
        if create:
            args["IfNoneMatch"] = "*"
        self.client.put_object(**args)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pbt-data-verify"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.URLError as e:
        raise Invalid(f"{url}: {e}") from None


def served_index(base: str, built: list[League], attempts: int = 6, wait: float = 5) -> dict:
    """The index at base; with built, retried until it names each built league, since a purge
    takes a moment to reach every edge."""
    for attempt in range(attempts):
        index = json.loads(fetch(f"{base}/{INDEX}"))
        stale = [lg.name for lg in built if index.get(lg.game, {}).get(lg.name) != {"version": lg.version, "dataset": lg.dataset, "art": lg.art}]
        if not stale:
            return index
        if attempt < attempts - 1:
            time.sleep(wait)
    raise Invalid(f"{base}/{INDEX} does not name the build of {', '.join(stale)}")


def verify(base: str, built: list[League], log=print) -> int:
    """Downloads every file the published index names, for the built leagues or all of them, and
    returns how many were checked."""
    base = base.rstrip("/")
    index = served_index(base, built)
    names = {lg.name for lg in built}
    checked = 0
    for game, lgs in index.items():
        for name, e in lgs.items():
            if names and name not in names:
                continue
            dataset = fetch(f"{base}/manifests/{e['dataset']}.json")
            if json.loads(dataset)["id"] != e["dataset"]:
                raise Invalid(f"{game} {name}: manifests/{e['dataset']}.json has another id")
            art = fetch(f"{base}/manifests/{e['art']}.json")
            if hashlib.sha256(art).hexdigest() != e["art"]:
                raise Invalid(f"{game} {name}: manifests/{e['art']}.json differs from its SHA-256")
            files = json.loads(dataset)["files"] + json.loads(art)["files"]
            for f in files:
                body = fetch(f"{base}/blobs/{f['sha256']}")
                if hashlib.sha256(body).hexdigest() != f["sha256"] or len(body) != f["size"]:
                    raise Invalid(f"{game} {name}: blobs/{f['sha256']} ({f['name']}) does not match")
            checked += len(files)
            log(f"{game} {name}: {e['version']}, dataset {e['dataset']}, art {e['art']}: {len(files)} files match")
    if not checked:
        raise Invalid(f"{base}/{INDEX} names no leagues")
    return checked


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in ("check", "publish", "verify"):
        print(__doc__, file=sys.stderr)
        return 2
    cmd, arg = argv[1], argv[2]
    try:
        if cmd == "verify":
            verify(arg, leagues(Path(argv[3])) if len(argv) > 3 else [])
            return 0
        built = leagues(Path(arg))
        for lg in built:
            print(f"{lg.game} {lg.name}: {lg.version}, dataset {lg.dataset}, art {lg.art}, {len(lg.blobs)} files")
        if cmd == "publish":
            env = os.environ
            bucket = R2(env["R2_ACCOUNT_ID"], env["R2_ACCESS_KEY_ID"], env["R2_SECRET_ACCESS_KEY"], env["R2_BUCKET"])
            publish(bucket, built)
    except Invalid as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
