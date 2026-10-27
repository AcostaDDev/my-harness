"""Offline npm cache check for the real Node/npm tests; synthetic lock and cache, no npm process."""

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from npm_cache import missing_npm_packages


URL = "https://registry.example.invalid/synthetic/-/synthetic-1.0.0.tgz"
TARBALL = b"synthetic tarball"


class NpmCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.lock = self.root / "package-lock.json"
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(TARBALL).digest()).decode()
        self.lock.write_text(json.dumps({"lockfileVersion": 3, "packages": {
            "": {"name": "synthetic-root"},
            "node_modules/synthetic": {"version": "1.0.0", "resolved": URL, "integrity": integrity},
        }}))
        self.cache = self.root / "npm-cache"
        key = hashlib.sha256(f"make-fetch-happen:request-cache:{URL}".encode()).hexdigest()
        content = hashlib.sha512(TARBALL).hexdigest()
        self.index = self.cache / "_cacache/index-v5" / key[:2] / key[2:4] / key[4:]
        self.content = self.cache / "_cacache/content-v2/sha512" / content[:2] / content[2:4] / content[4:]

    def store(self, *paths):
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(TARBALL)

    def test_empty_cache_names_each_locked_package(self):
        self.assertEqual(missing_npm_packages(self.lock, self.cache), ["synthetic@1.0.0"])

    def test_index_and_content_are_both_required(self):
        self.store(self.index)
        self.assertEqual(missing_npm_packages(self.lock, self.cache), ["synthetic@1.0.0"])
        self.index.unlink()
        self.store(self.content)
        self.assertEqual(missing_npm_packages(self.lock, self.cache), ["synthetic@1.0.0"])
        self.store(self.index)
        self.assertEqual(missing_npm_packages(self.lock, self.cache), [])


if __name__ == "__main__":
    unittest.main()
