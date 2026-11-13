import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import detect

# steamcmd +app_info_print 238960, trimmed; the login lines before the app are kept.
APP_INFO = """Redirecting stderr to '/home/runner/Steam/logs/stderr.txt'
Logging in user 'builder' to Steam Public...OK
Waiting for user info...OK
AppID : 238960, change number : 31234567/0, last change : Tue Nov 10 09:12:03 2026
"238960"
{
\t"common"
\t{
\t\t"name"\t\t"Path of Exile"
\t\t"oslist"\t\t"windows,macos"
\t}
\t"depots"
\t{
\t\t"238961"
\t\t{
\t\t\t"name"\t\t"Path of Exile Content \\"main\\""
\t\t\t"manifests"
\t\t\t{
\t\t\t\t"public"
\t\t\t\t{
\t\t\t\t\t"gid"\t\t"2467965126630699088"
\t\t\t\t\t"size"\t\t"71368266997"
\t\t\t\t\t"download"\t\t"70385046416"
\t\t\t\t}
\t\t\t\t"local"
\t\t\t\t{
\t\t\t\t\t"gid"\t\t"5835722125312717334"
\t\t\t\t}
\t\t\t}
\t\t}
\t\t"branches"
\t\t{
\t\t\t"public"
\t\t\t{
\t\t\t\t"buildid"\t\t"26530219"
\t\t\t}
\t\t}
\t}
}
"""

R329 = {"version": "3.29.3.5", "steamManifest": "2467965126630699088", "datSchemaCommit": "717d788", "treeExportCommit": "8bd138b"}
R328 = {"version": "3.28.0.16", "steamManifest": "7392830184361287422", "datSchemaCommit": "717d788", "treeExportCommit": "648e492"}
TAGS = [("3.29.1", "8bd138b"), ("3.29.0", "1cc7492"), ("3.28.0", "648e492"), ("3.27.0", "326858d"), ("3.27.0g", "765dda3"), ("latest", "fff")]


def state(**kw) -> detect.State:
    base = dict(version="3.29.3.5", manifest="2467965126630699088", recipes={"3.28": R328, "3.29": R329},
                pr=None, dat_schema="717d788", tree_tags=TAGS)
    return detect.State(**{**base, **kw})


class TestParse(unittest.TestCase):
    def test_public_manifest(self):
        self.assertEqual(detect.public_manifest(APP_INFO), "2467965126630699088")

    def test_public_manifest_old_format(self):
        old = APP_INFO.replace('"public"\n\t\t\t\t{\n\t\t\t\t\t"gid"\t\t"2467965126630699088"', '"public"\t\t"2467965126630699088"\n\t\t\t\t"x"\n\t\t\t\t{')
        self.assertEqual(detect.public_manifest(old), "2467965126630699088")

    def test_public_manifest_errors(self):
        for text in ["", "AppID : 238960\n", APP_INFO[: APP_INFO.index('"depots"')], APP_INFO.replace('"238961"', '"1"')]:
            with self.subTest(text=text[-40:]), self.assertRaises(ValueError):
                detect.public_manifest(text)

    def test_newest_tree_tag(self):
        self.assertEqual(detect.newest_tree_tag(TAGS, "3.29"), ("3.29.1", "8bd138b"))
        self.assertEqual(detect.newest_tree_tag(TAGS, "3.27"), ("3.27.0g", "765dda3"))
        self.assertEqual(detect.newest_tree_tag([("3.30.0", "a"), ("3.30.0g", "b")], "3.30"), ("3.30.0g", "b"))
        self.assertIsNone(detect.newest_tree_tag(TAGS, "3.30"))


class TestDecide(unittest.TestCase):
    def check(self, s, action, recipe=None, reason=""):
        d = detect.decide(s)
        self.assertEqual(d.action, action, d.reason)
        if recipe is not None or action == "none":
            self.assertEqual(d.recipe, recipe)
        self.assertIn(reason, d.reason)
        return d

    def test_current(self):
        self.check(state(), "none", reason="3.29.3.5 is current")

    def test_new_patch(self):
        d = self.check(state(version="3.29.3.6", manifest="111", dat_schema="aaaaaaa"), "update",
                       {"version": "3.29.3.6", "steamManifest": "111", "datSchemaCommit": "aaaaaaa", "treeExportCommit": "8bd138b"})
        self.assertEqual(d.title, "poe1 3.29: 3.29.3.6")

    def test_new_patch_drops_note(self):
        noted = {**R329, "datSchemaNote": "hand-picked"}
        d = self.check(state(version="3.29.3.6", manifest="111", recipes={"3.29": noted}), "update")
        self.assertNotIn("datSchemaNote", d.recipe)

    def test_new_league(self):
        tags = [("3.30.0", "ccccccc"), *TAGS]
        self.check(state(version="3.30.0.1", manifest="111", tree_tags=tags), "new",
                   {"version": "3.30.0.1", "steamManifest": "111", "datSchemaCommit": "717d788", "treeExportCommit": "ccccccc"})

    def test_new_league_without_tree(self):
        self.check(state(version="3.30.0.1", manifest="111"), "none", reason="no skilltree-export tag for 3.30")

    def test_newer_tree_tag(self):
        tags = [("3.29.1b", "9999999"), *TAGS]
        d = self.check(state(tree_tags=tags), "update", {**R329, "treeExportCommit": "9999999"}, "skilltree-export 3.29.1b")
        self.assertEqual(d.title, "poe1 3.29: 3.29.3.5, tree 3.29.1b")
        pr = detect.PR(7, {**R329, "treeExportCommit": "9999999"}, "pending")
        self.check(state(tree_tags=tags, pr=pr), "none", reason="3.29.3.5 is current")

    def test_steam_not_updated(self):
        self.check(state(version="3.29.3.6"), "none", reason="not updated yet")
        self.check(state(version="3.30.0.1", tree_tags=[("3.30.0", "c")]), "none", reason="not updated yet")

    def test_steam_moved_alone(self):
        self.check(state(manifest="111"), "none", reason="new without a new version, ignored")

    def test_older_version(self):
        self.check(state(version="3.29.3.4"), "none", reason="older than 3.29.3.5")
        self.check(state(version="3.28.0.17", manifest="111"), "none", reason="older than league 3.29")

    def test_open_pr_newer_patch(self):
        pr = detect.PR(7, {**R329, "version": "3.29.3.6", "steamManifest": "111"}, "success")
        self.check(state(version="3.29.3.7", manifest="222", pr=pr), "update",
                   {"version": "3.29.3.7", "steamManifest": "222", "datSchemaCommit": "717d788", "treeExportCommit": "8bd138b"})
        self.check(state(version="3.29.3.7", manifest="111", pr=pr), "none", reason="not updated yet")

    def test_retry(self):
        pr_recipe = {**R329, "version": "3.29.3.6", "steamManifest": "111"}
        failed = detect.PR(7, pr_recipe, "failure")
        d = self.check(state(version="3.29.3.6", manifest="111", pr=failed, dat_schema="bbbbbbbbb"), "retry",
                       {**pr_recipe, "datSchemaCommit": "bbbbbbbbb"})
        self.assertEqual(d.title, "poe1 3.29: 3.29.3.6, dat-schema bbbbbbb")
        d = self.check(state(version="3.29.3.6", manifest="111", pr=failed), "rerun", reason="rerunning it once")
        self.assertEqual(d.run, 0)
        rerun = detect.PR(7, pr_recipe, "failure", run=99, attempt=1)
        self.assertEqual(detect.decide(state(version="3.29.3.6", manifest="111", pr=rerun)).run, 99)
        again = detect.PR(7, pr_recipe, "failure", run=99, attempt=2)
        self.check(state(version="3.29.3.6", manifest="111", pr=again), "none", reason="failed again; waiting for a dat-schema commit after 717d788")
        self.check(state(version="3.29.3.6", manifest="111", pr=again, dat_schema="bbbbbbb"), "retry")
        for build in ("success", "pending", "other", "none"):
            with self.subTest(build=build):
                self.check(state(version="3.29.3.6", manifest="111", pr=detect.PR(7, pr_recipe, build), dat_schema="bbbbbbb"), "none")


class TestMain(unittest.TestCase):
    """main against recorded responses, with the 3.29.3.6 patch out and no detect pull request."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir))
        for league, r in {"3.28": R328, "3.29": R329}.items():
            (self.dir / "poe1" / league).mkdir(parents=True)
            (self.dir / "poe1" / league / "source.json").write_text(json.dumps(r))
        (self.dir / "app-info.txt").write_text(APP_INFO.replace("2467965126630699088", "111"))
        api = detect.API
        self.responses = {
            detect.LATEST_URL: b"3.29.3.6",
            f"{api}/repos/xaroth/pbt-data/pulls?state=open&head=xaroth:detect/poe1-3.29": b"[]",
            f"{api}/repos/poe-tool-dev/dat-schema/commits?per_page=1": b'[{"sha": "abcdef0123"}]',
            f"{api}/repos/grindinggear/skilltree-export/tags?per_page=100&page=1": json.dumps(
                [{"name": n, "commit": {"sha": c}} for n, c in TAGS]).encode(),
        }

    def run_main(self):
        out = self.dir / "outputs"
        argv = ["--app-info", str(self.dir / "app-info.txt"), "--out", str(self.dir / "source.json"),
                "--root", str(self.dir), "--repo", "xaroth/pbt-data"]
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}), mock.patch("sys.stderr"):
            self.assertEqual(detect.main(argv, self.responses.__getitem__), 0)
        return dict(line.split("=", 1) for line in out.read_text().splitlines())

    def test_update(self):
        self.assertEqual(self.run_main(), {"action": "update", "league": "3.29", "branch": "detect/poe1-3.29", "pr": "", "title": "poe1 3.29: 3.29.3.6", "run": ""})
        self.assertEqual((self.dir / "source.json").read_text(), json.dumps(
            {"version": "3.29.3.6", "steamManifest": "111", "datSchemaCommit": "abcdef0123", "treeExportCommit": "8bd138b"}, indent=2) + "\n")

    def test_retry_on_open_pr(self):
        api = detect.API
        branch_recipe = {**R329, "version": "3.29.3.6", "steamManifest": "111"}
        self.responses |= {
            f"{api}/repos/xaroth/pbt-data/pulls?state=open&head=xaroth:detect/poe1-3.29": b'[{"number": 12}]',
            f"{api}/repos/xaroth/pbt-data/contents/poe1/3.29/source.json?ref=detect/poe1-3.29": json.dumps(branch_recipe).encode(),
            f"{api}/repos/xaroth/pbt-data/actions/workflows/build.yml/runs?branch=detect/poe1-3.29&per_page=1":
                b'{"workflow_runs": [{"id": 42, "run_attempt": 1, "status": "completed", "conclusion": "failure"}]}',
        }
        got = self.run_main()
        self.assertEqual((got["action"], got["pr"], got["run"]), ("retry", "12", ""))
        self.assertEqual(json.loads((self.dir / "source.json").read_text())["datSchemaCommit"], "abcdef0123")

    def test_rerun_on_open_pr(self):
        api = detect.API
        self.responses |= {
            f"{api}/repos/poe-tool-dev/dat-schema/commits?per_page=1": b'[{"sha": "717d788"}]',
            f"{api}/repos/xaroth/pbt-data/pulls?state=open&head=xaroth:detect/poe1-3.29": b'[{"number": 12}]',
            f"{api}/repos/xaroth/pbt-data/contents/poe1/3.29/source.json?ref=detect/poe1-3.29":
                json.dumps({**R329, "version": "3.29.3.6", "steamManifest": "111"}).encode(),
            f"{api}/repos/xaroth/pbt-data/actions/workflows/build.yml/runs?branch=detect/poe1-3.29&per_page=1":
                b'{"workflow_runs": [{"id": 42, "run_attempt": 1, "status": "completed", "conclusion": "failure"}]}',
        }
        got = self.run_main()
        self.assertEqual((got["action"], got["run"]), ("rerun", "42"))
        self.assertFalse((self.dir / "source.json").exists())

    def test_bad_version(self):
        self.responses[detect.LATEST_URL] = b"<html>"
        with self.assertRaises(ValueError):
            self.run_main()


if __name__ == "__main__":
    unittest.main()
