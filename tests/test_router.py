import os
import sys
import time
import shutil
import tempfile
import unittest
import logging

# Ensure router and handlers are in path
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from handlers.move import move_verified, get_unique_dest_path
from handlers.cleanup import cleanup_retention
from router import run_router

class TestFileRouter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="filerouter_test_")
        self.source_dir = os.path.join(self.temp_dir, "source")
        self.target_dir = os.path.join(self.temp_dir, "target")
        os.makedirs(self.source_dir, exist_ok=True)
        os.makedirs(self.target_dir, exist_ok=True)
        self.logger = logging.getLogger("TestRouter")
        self.logger.setLevel(logging.CRITICAL)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_move_verified_direct(self):
        src_file = os.path.join(self.source_dir, "app.dmg")
        with open(src_file, "wb") as f:
            f.write(b"SAMPLE DMG DATA" * 100)

        # File just created, with min_age 0 should move
        res = move_verified(src_file, self.target_dir, min_age_sec=0, dry_run=False, logger=self.logger)
        self.assertTrue(res)
        self.assertFalse(os.path.exists(src_file))
        dest_file = os.path.join(self.target_dir, "app.dmg")
        self.assertTrue(os.path.exists(dest_file))
        self.assertEqual(os.path.getsize(dest_file), len(b"SAMPLE DMG DATA" * 100))

    def test_move_verified_age_check(self):
        src_file = os.path.join(self.source_dir, "app.dmg")
        with open(src_file, "wb") as f:
            f.write(b"DATA")

        # min_age_sec 100 should skip
        res = move_verified(src_file, self.target_dir, min_age_sec=100, dry_run=False, logger=self.logger)
        self.assertFalse(res)
        self.assertTrue(os.path.exists(src_file))

    def test_recursive_routing_and_cleanup(self):
        # Create nested package folder: source/App Package [v1.0]/app.dmg
        package_dir = os.path.join(self.source_dir, "App Package [v1.0]")
        os.makedirs(package_dir, exist_ok=True)
        src_file = os.path.join(package_dir, "app.dmg")
        with open(src_file, "wb") as f:
            f.write(b"NESTED DMG CONTENT")

        # Config testing recursive move and empty dir cleanup
        config = {
            "settings": {
                "log_file": os.path.join(self.temp_dir, "test.log"),
                "default_min_age_seconds": 0
            },
            "rules": [
                {
                    "name": "Extract DMGs",
                    "enabled": True,
                    "source": self.source_dir,
                    "target": self.target_dir,
                    "patterns": ["*.dmg"],
                    "action": "move_verified",
                    "recursive": True,
                    "cleanup_empty_dirs": True,
                    "min_age_seconds": 0
                }
            ]
        }

        processed = run_router(config, dry_run=False, verbose=False)
        self.assertEqual(processed, 1)

        # File moved to target root
        dest_file = os.path.join(self.target_dir, "app.dmg")
        self.assertTrue(os.path.exists(dest_file))

        # Enclosing folder was cleaned up because it became empty
        self.assertFalse(os.path.exists(package_dir))

if __name__ == "__main__":
    unittest.main()
