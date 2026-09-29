import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mensarium.cli import service


class AppBundleTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        patch.object(service.Path, "home", return_value=self.home).start()
        patch.object(service.sys, "platform", "darwin").start()
        self.addCleanup(patch.stopall)

    def bundle(self, name: str, bundle_id: str) -> Path:
        app = self.home / "Applications" / name
        (app / "Contents").mkdir(parents=True)
        (app / "Contents" / "Info.plist").write_text(f"<key>CFBundleIdentifier</key><string>{bundle_id}</string>")
        return app

    def test_safari_web_app_under_the_old_name_is_left_alone(self):
        safari = self.bundle("Mensarium.app", "com.apple.Safari.WebApp.X")
        launcher = service.install_app_bundle()
        self.assertEqual(launcher, self.home / "Applications" / "Mensarium Agent.app" / "Contents" / "MacOS" / "Mensarium")
        self.assertTrue(launcher.exists())
        self.assertIn("Safari", (safari / "Contents" / "Info.plist").read_text())

    def test_foreign_app_under_our_name_disables_the_launcher_and_our_old_bundle_is_removed(self):
        self.bundle("Mensarium Agent.app", "com.example.other")
        legacy = self.bundle("Mensarium.app", service.APP_BUNDLE_ID)
        self.assertIsNone(service.install_app_bundle())
        self.assertFalse(legacy.exists())
        self.assertIn("com.example.other", (self.home / "Applications" / "Mensarium Agent.app" / "Contents" / "Info.plist").read_text())
