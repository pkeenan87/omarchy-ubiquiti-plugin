"""Checks the plugin against the published Omarchy plugin contract.

`omarchy plugin validate` needs an Omarchy install, which CI runners do not
have. This encodes the same rules from https://plugins.omarchy.org/develop.html
so drift is caught on every push, and adds the cross-checks that guidance
implies but no tool enforces.
"""

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
README = (ROOT / "README.md").read_text()

VALID_KINDS = {"bar-widget", "panel", "overlay", "menu", "service", "bar"}
ENTRY_KEY_FOR_KIND = {
    "bar-widget": "barWidget", "panel": "panel", "overlay": "overlay",
    "menu": "menu", "service": "service", "bar": "bar",
}


class TestRequiredFields(unittest.TestCase):
    def test_present_and_typed(self):
        expected = {
            "schemaVersion": int, "id": str, "name": str, "version": str,
            "author": str, "license": str, "description": str,
            "kinds": list, "entryPoints": dict,
        }
        for field, kind in expected.items():
            self.assertIn(field, MANIFEST, f"{field} missing from manifest")
            self.assertIsInstance(MANIFEST[field], kind, f"{field} has the wrong type")
            if kind is str:
                self.assertTrue(MANIFEST[field].strip(), f"{field} is empty")

    def test_schema_version(self):
        self.assertEqual(MANIFEST["schemaVersion"], 1)


class TestPluginId(unittest.TestCase):
    def test_not_reserved_for_first_party(self):
        self.assertFalse(MANIFEST["id"].startswith("omarchy."),
                         "the omarchy.* prefix is reserved for first-party plugins")

    def test_reverse_domain_notation(self):
        # develop.html asks for reverse-domain notation.
        self.assertRegex(MANIFEST["id"], r"^[a-z0-9]+(\.[a-z0-9][a-z0-9-]*){2,}$")

    def test_matches_install_scripts(self):
        # The id is the directory name, so the scripts must agree with it or
        # install and uninstall act on different paths.
        for script in ("install.sh", "uninstall.sh"):
            text = (ROOT / script).read_text()
            self.assertIn(f'plugin_id="{MANIFEST["id"]}"', text,
                          f"{script} does not use the manifest id")

    def test_matches_systemd_unit(self):
        unit = (ROOT / "systemd" / "omarchy-unifi.service").read_text()
        for line in unit.splitlines():
            if "plugins/" in line:
                self.assertIn(MANIFEST["id"], line,
                              f"stale plugin id in the unit: {line.strip()}")

    def test_matches_qml_module_names(self):
        for name in ("BarWidget.qml", "Panel.qml"):
            text = (ROOT / name).read_text()
            self.assertIn(f'moduleName: "{MANIFEST["id"]}"', text,
                          f"{name} declares a different moduleName")


class TestVersion(unittest.TestCase):
    def test_semver(self):
        self.assertRegex(MANIFEST["version"], r"^\d+\.\d+\.\d+")

    def test_within_marketplace_limit(self):
        # publish.html caps version at 64 characters.
        self.assertLessEqual(len(MANIFEST["version"]), 64)


class TestKindsAndEntryPoints(unittest.TestCase):
    def test_kinds_are_known(self):
        self.assertTrue(MANIFEST["kinds"])
        for kind in MANIFEST["kinds"]:
            self.assertIn(kind, VALID_KINDS)

    def test_no_separate_panel_kind(self):
        # A popup loaded by a bar widget stays one kind; declaring `panel`
        # alongside `bar-widget` registers it twice.
        if "bar-widget" in MANIFEST["kinds"]:
            self.assertNotIn("panel", MANIFEST["kinds"])

    def test_entry_points_match_kinds(self):
        for kind in MANIFEST["kinds"]:
            self.assertIn(ENTRY_KEY_FOR_KIND[kind], MANIFEST["entryPoints"])

    def test_entry_point_files_exist(self):
        for key, rel in MANIFEST["entryPoints"].items():
            self.assertFalse(rel.startswith("/"), f"{key} must be a relative path")
            self.assertNotIn("..", rel, f"{key} must stay inside the plugin")
            self.assertTrue((ROOT / rel).is_file(), f"{key} points at a missing file: {rel}")


class TestBarWidgetContract(unittest.TestCase):
    """develop.html requires these on the bar-widget entry point."""

    BAR = (ROOT / "BarWidget.qml").read_text()

    def test_functions(self):
        for fn in ("open", "close", "toggle", "closeForPopoutSwitch"):
            # Anchored per line so a same-named function inside IpcHandler
            # does not satisfy a contract that is about the root object.
            found = re.search(rf"^  function {fn}\(", self.BAR, re.MULTILINE)
            self.assertTrue(found, f"{fn}() is not exposed on the BarWidget root")

    def test_properties(self):
        for prop in ("opened", "popoutSwitchClosing"):
            found = re.search(rf"^  readonly property bool {prop}\b", self.BAR, re.MULTILINE)
            self.assertTrue(found, f"{prop} is not exposed on the BarWidget root")


class TestSettingsSchema(unittest.TestCase):
    WIDGET = MANIFEST.get("barWidget", {})

    def test_widget_metadata(self):
        for field in ("displayName", "description", "category"):
            self.assertIn(field, self.WIDGET)

    def test_every_schema_key_has_a_default(self):
        defaults = self.WIDGET.get("defaults", {})
        for entry in self.WIDGET.get("schema", []):
            self.assertIn(entry["key"], defaults,
                          f"{entry['key']} is in the schema but has no default")

    def test_schema_default_matches_defaults_block(self):
        defaults = self.WIDGET.get("defaults", {})
        for entry in self.WIDGET.get("schema", []):
            if "defaultValue" in entry:
                self.assertEqual(entry["defaultValue"], defaults[entry["key"]],
                                 f"{entry['key']}: schema and defaults disagree")

    def test_integer_ranges_contain_their_default(self):
        for entry in self.WIDGET.get("schema", []):
            if entry.get("type") == "integer":
                self.assertLessEqual(entry["min"], entry["defaultValue"])
                self.assertGreaterEqual(entry["max"], entry["defaultValue"])


class TestDocumentation(unittest.TestCase):
    def test_readme_documents_every_default(self):
        # These drifted once already: maxClients changed and the table did not.
        for key, value in MANIFEST.get("barWidget", {}).get("defaults", {}).items():
            row = re.search(rf"\| `{re.escape(key)}` \| `([^`]+)` \|", README)
            self.assertIsNotNone(row, f"{key} is not in the README settings table")
            expected = str(value).lower() if isinstance(value, bool) else str(value)
            self.assertEqual(row.group(1), expected,
                             f"{key}: README says {row.group(1)}, manifest says {expected}")

    def test_community_files_exist(self):
        for name in ("README.md", "LICENSE", "CONTRIBUTING.md",
                     "CODE_OF_CONDUCT.md", "SECURITY.md", "preview.png"):
            self.assertTrue((ROOT / name).is_file(), f"{name} is missing")

    def test_repo_urls_are_not_placeholders(self):
        for name in ("README.md", "systemd/omarchy-unifi.service"):
            text = (ROOT / name).read_text()
            for url in re.findall(r"https://github\.com/[\w.-]+/[\w.-]+", text):
                self.assertTrue(url.startswith("https://github.com/pkeenan87/"),
                                f"{name} points at {url}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
