"""Unit tests for system dependency checks."""

import unittest
from unittest.mock import patch
import sys
from pathlib import Path

# Add plugin root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.system_deps import check_system_dependencies, ensure_system_dependencies
from core.exceptions import SystemDependencyMissingError


class TestSystemDeps(unittest.TestCase):
    def test_check_system_dependencies(self):
        ok, missing = check_system_dependencies()
        if sys.platform == "linux":
            # On Linux with installed packages, it should be True
            self.assertTrue(ok)
            self.assertEqual(missing, [])
        else:
            self.assertTrue(ok)
            self.assertEqual(missing, [])

    @patch("ctypes.util.find_library", return_value=None)
    @patch("sys.platform", "linux")
    def test_missing_dependencies_raises(self, mock_find):
        with patch("core.system_deps.attempt_install_dependencies", return_value=(False, "permission denied")):
            with self.assertRaises(SystemDependencyMissingError) as ctx:
                ensure_system_dependencies()
            self.assertIn("Automatic installation failed", str(ctx.exception))
            self.assertIn("docker exec", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
