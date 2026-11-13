import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import bucket


class FakeBucket:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []

    def keys(self, prefix):
        return {k for k in self.objects if k.startswith(prefix)}

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, body, content_type, cache_control, create):
        if create and key in self.objects:
            raise AssertionError(f"{key} overwritten")
        self.objects[key] = body
        self.puts.append(key)


def write_manifest(dir: Path, files: dict[str, bytes], **extra) -> None:
    dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, body in files.items():
        (dir / name).write_bytes(body)
        entries.append({"name": name, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    (dir / "manifest.json").write_text(json.dumps({**extra, "files": entries}))


def build_league(root: Path, name: str, data: bytes) -> None:
    d = root / name
    write_manifest(d, {"stats.fb": data, "shared.fb": b"shared"}, game="poe1", version=f"{name}.0.1", format=1, id=f"id-{name}")
    write_manifest(d / "art", {"frame-0.png": b"png-" + data}, sprites={})


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        build_league(self.tmp, "3.28", b"a")
        build_league(self.tmp, "3.29", b"b")
        self.built = bucket.leagues(self.tmp)

    def publish(self, b, built=None):
        return bucket.publish(b, built or self.built, log=lambda *_: None)

    def test_uploads_blobs_then_manifests_then_index(self):
        b = FakeBucket()
        result = self.publish(b)
        kinds = [k.split("/")[0] for k in b.puts]
        self.assertEqual(kinds, sorted(kinds, key=["blobs", "manifests", "index.json"].index))
        self.assertEqual(kinds.count("blobs"), 5)  # shared.fb once
        self.assertEqual(kinds.count("manifests"), 4)
        self.assertTrue(result.index_changed)
        index = json.loads(b.objects["index.json"])
        art = hashlib.sha256((self.tmp / "3.29/art/manifest.json").read_bytes()).hexdigest()
        self.assertEqual(index["poe1"]["3.29"], {"version": "3.29.0.1", "format": 1, "dataset": "id-3.29", "art": art})
        self.assertEqual(b.objects[f"manifests/{art}.json"], (self.tmp / "3.29/art/manifest.json").read_bytes())

    def test_second_run_uploads_nothing(self):
        b = FakeBucket()
        self.publish(b)
        index = b.objects["index.json"]
        b.puts.clear()
        result = self.publish(b)
        self.assertEqual(b.puts, [])
        self.assertEqual(result.uploaded, [])
        self.assertFalse(result.index_changed)
        self.assertEqual(b.objects["index.json"], index)

    def test_keeps_leagues_not_built(self):
        b = FakeBucket()
        self.publish(b)
        build_league(self.tmp, "3.29", b"c")
        result = self.publish(b, [bucket.league(self.tmp / "3.29")])
        self.assertTrue(result.index_changed)
        index = json.loads(b.objects["index.json"])
        self.assertEqual(set(index["poe1"]), {"3.28", "3.29"})
        self.assertEqual(index["poe1"]["3.28"]["dataset"], "id-3.28")


class VerifyTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        build_league(tmp, "3.29", b"b")
        self.bucket = FakeBucket()
        bucket.publish(self.bucket, bucket.leagues(tmp), log=lambda *_: None)
        self.fetch = bucket.fetch
        bucket.fetch = lambda url: self.bucket.objects[url.removeprefix("https://x/")]

    def tearDown(self):
        bucket.fetch = self.fetch

    def verify(self):
        return bucket.verify("https://x", [], log=lambda *_: None)

    def test_passes_on_what_publish_wrote(self):
        self.assertEqual(self.verify(), 3)

    def test_refuses_an_entry_without_the_manifests_format(self):
        index = json.loads(self.bucket.objects["index.json"])
        del index["poe1"]["3.29"]["format"]
        self.bucket.objects["index.json"] = json.dumps(index).encode()
        with self.assertRaisesRegex(bucket.Invalid, "format"):
            self.verify()


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        build_league(self.tmp, "3.29", b"b")

    def test_refuses_a_file_that_differs_from_its_manifest(self):
        (self.tmp / "3.29/art/frame-0.png").write_bytes(b"png-x")
        with self.assertRaisesRegex(bucket.Invalid, "SHA-256"):
            bucket.leagues(self.tmp)

    def test_refuses_a_missing_file(self):
        (self.tmp / "3.29/stats.fb").unlink()
        with self.assertRaisesRegex(bucket.Invalid, "missing"):
            bucket.leagues(self.tmp)

    def test_refuses_a_league_without_art(self):
        (self.tmp / "3.29/art/manifest.json").unlink()
        with self.assertRaisesRegex(bucket.Invalid, "missing"):
            bucket.leagues(self.tmp)


if __name__ == "__main__":
    unittest.main()
