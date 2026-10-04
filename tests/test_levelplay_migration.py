"""Repository-level checks for the breaking Unity LevelPlay migration.

Run with:

    python3 -m unittest discover -s tests -v

The checks intentionally inspect the working tree as well as tracked files so
they are useful before a migration commit is staged.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension-levelplay"

ANDROID_SDK_VERSION = "9.6.1"
IOS_SDK_VERSION = "9.6.1.0"

OLD_NAME_RE = re.compile(r"iron[\s_.-]*source", re.IGNORECASE)

# These are the only remaining vendor-owned iOS identifiers accepted in files
# controlled by this repository. The current Ad Quality pod is pinned
# explicitly so CocoaPods' upstream version range cannot make builds drift.
IOS_VENDOR_IDENTIFIER_RE = re.compile(
    r"\b(?:IronSourceSDK|IronSourceAdQualitySDK|IronSource[A-Za-z0-9]+Adapter)\b"
)
IOS_HEADER_IMPORT_RE = re.compile(
    r'^#import\s+(?:<IronSource/IronSource\.h>|"IronSource/IronSource\.h")$'
)

EXPECTED_SOURCE_PATHS = (
    "extension-levelplay/ext.manifest",
    "extension-levelplay/ext.properties",
    "extension-levelplay/api/levelplay.script_api",
    "extension-levelplay/manifests/android/build.gradle",
    "extension-levelplay/manifests/ios/Podfile",
    "extension-levelplay/src/levelplay.cpp",
    "extension-levelplay/src/levelplay_android.cpp",
    "extension-levelplay/src/levelplay_ios.mm",
    "extension-levelplay/src/levelplay_private.h",
    "extension-levelplay/src/levelplay_callback.cpp",
    "extension-levelplay/src/levelplay_callback_private.h",
    "extension-levelplay/src/com_defold_levelplay_LevelPlayJNI.h",
    "extension-levelplay/src/java/com/defold/levelplay/LevelPlayJNI.java",
)

EXPECTED_LUA_FUNCTIONS = {
    "set_callback",
    "init",
    "get_sdk_version",
    "set_gdpr_consent",
    "set_ccpa",
    "set_coppa",
    "set_metadata",
    "set_meta_limited_data_use",
    "set_meta_advertiser_tracking",
    "set_dynamic_user_id",
    "set_adapters_debug",
    "validate_integration",
    "launch_test_suite",
    "request_tracking_authorization",
    "get_tracking_authorization_status",
    "create_interstitial_ad",
    "destroy_interstitial_ad",
    "load_interstitial_ad",
    "is_interstitial_ad_ready",
    "show_interstitial_ad",
    "is_interstitial_placement_capped",
    "create_rewarded_ad",
    "destroy_rewarded_ad",
    "load_rewarded_ad",
    "is_rewarded_ad_ready",
    "show_rewarded_ad",
    "is_rewarded_placement_capped",
    "get_reward",
    "create_banner_ad",
    "load_banner_ad",
    "show_banner_ad",
    "hide_banner_ad",
    "pause_banner_auto_refresh",
    "resume_banner_auto_refresh",
    "destroy_banner_ad",
}

EXPECTED_LUA_CONSTANTS = {
    "MSG_INIT",
    "MSG_INTERSTITIAL",
    "MSG_REWARDED",
    "MSG_BANNER",
    "MSG_TRACKING",
    "EVENT_INIT_SUCCEEDED",
    "EVENT_INIT_FAILED",
    "EVENT_AD_LOADED",
    "EVENT_AD_LOAD_FAILED",
    "EVENT_AD_INFO_CHANGED",
    "EVENT_AD_DISPLAYED",
    "EVENT_AD_DISPLAY_FAILED",
    "EVENT_AD_CLICKED",
    "EVENT_AD_CLOSED",
    "EVENT_AD_REWARDED",
    "EVENT_AD_EXPANDED",
    "EVENT_AD_COLLAPSED",
    "EVENT_AD_LEFT_APPLICATION",
    "EVENT_JSON_ERROR",
    "TRACKING_STATUS_NOT_DETERMINED",
    "TRACKING_STATUS_RESTRICTED",
    "TRACKING_STATUS_DENIED",
    "TRACKING_STATUS_AUTHORIZED",
    "BANNER_SIZE_BANNER",
    "BANNER_SIZE_LARGE",
    "BANNER_SIZE_MEDIUM_RECTANGLE",
    "BANNER_SIZE_LEADERBOARD",
    "BANNER_SIZE_ADAPTIVE",
    "BANNER_POSITION_TOP",
    "BANNER_POSITION_BOTTOM",
}

# Android does not emit the iOS-only tracking message, so compare the common
# callback ABI rather than requiring every C++ constant to exist in Java.
EXPECTED_CROSS_PLATFORM_CALLBACK_CONSTANTS = {
    "MSG_INIT",
    "MSG_INTERSTITIAL",
    "MSG_REWARDED",
    "MSG_BANNER",
    "EVENT_INIT_SUCCEEDED",
    "EVENT_INIT_FAILED",
    "EVENT_AD_LOADED",
    "EVENT_AD_LOAD_FAILED",
    "EVENT_AD_INFO_CHANGED",
    "EVENT_AD_DISPLAYED",
    "EVENT_AD_DISPLAY_FAILED",
    "EVENT_AD_CLICKED",
    "EVENT_AD_CLOSED",
    "EVENT_AD_REWARDED",
    "EVENT_AD_EXPANDED",
    "EVENT_AD_COLLAPSED",
    "EVENT_AD_LEFT_APPLICATION",
    "EVENT_JSON_ERROR",
}

LEGACY_PATTERNS = {
    "legacy Android mediation SDK": re.compile(
        r"com\.ironsource\.sdk\s*:\s*mediationsdk", re.IGNORECASE
    ),
    "legacy Android adapter group": re.compile(
        r"com\.ironsource\.adapters\s*:", re.IGNORECASE
    ),
    "legacy Ad Quality SDK": re.compile(
        r"(?:IronSourceAdQualitySDK[^\n]*['\"]7\.|"
        r"com\.ironsource\s*:\s*adqualitysdk)",
        re.IGNORECASE,
    ),
    "obsolete Android SDK repository": re.compile(
        r"(?:https?://)?android-sdk\.is\.com", re.IGNORECASE
    ),
    "obsolete updater documentation domain": re.compile(
        r"(?:https?://)?developers\.is\.com", re.IGNORECASE
    ),
    "old Lua module": re.compile(
        r"""(?x)
        \brequire\s*\(?\s*["']iron[\s_.-]*source["']
        | \biron[\s_.-]*source\s*[\.\[]
        | MODULE_NAME\s+["']iron[\s_.-]*source["']
        """
    ),
    "old project/config namespace": re.compile(
        r"""(?x)
        \[\s*iron_source\s*\]
        | \{\{[#/^]?\s*iron_source\.
        | \biron_source\.[A-Za-z0-9_]
        """
    ),
    "old Java/JNI namespace": re.compile(
        r"(?:com[./_]defold[./_]ironsource|IronSourceJNI)"
    ),
    "old C++ namespace": re.compile(
        r"(?:\bdmIronSource\b|EXTENSION_NAME\s+IronSourceExt)"
    ),
    "legacy consent API": re.compile(
        r"(?:\bset_consent\b|consent_view)", re.IGNORECASE
    ),
    "legacy network-state tracking API": re.compile(
        r"\bshould_track_network_state\b", re.IGNORECASE
    ),
    "legacy rewarded-video API": re.compile(r"rewarded_video", re.IGNORECASE),
    "legacy IDFA API name": re.compile(
        r"\b(?:request_idfa|get_idfa_status)\b", re.IGNORECASE
    ),
    "legacy singleton interstitial Lua API": re.compile(
        r"""(?x)
        \blevelplay\s*\.\s*
            (?:load_interstitial|is_interstitial_ready|show_interstitial)\s*\(
        | \{\s*["']
            (?:load_interstitial|is_interstitial_ready|show_interstitial)["']
            \s*,\s*Lua_
        | ^\s*-\s+name:\s*
            (?:load_interstitial|is_interstitial_ready|show_interstitial)\s*$
        """,
        re.IGNORECASE,
    ),
    "legacy placement-info API": re.compile(
        r"\b(?:get_interstitial_placement_info|get_rewarded_video_placement_info)\b",
        re.IGNORECASE,
    ),
    "legacy callback identifiers": re.compile(
        r"\b(?:MSG_CONSENT|MSG_IDFA|EVENT_INIT_COMPLETE|EVENT_CONSENT_[A-Z_]+)\b"
    ),
}


def _repository_files() -> list[Path]:
    """Return existing tracked and non-ignored untracked files."""

    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Unable to enumerate repository files:\n"
            + result.stderr.decode("utf-8", errors="replace")
        )

    files: list[Path] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(os.fsdecode(raw_path))
        path = ROOT / relative
        # A deleted-but-not-yet-staged path remains in the index and must not
        # make a clean working-tree migration fail.
        if path.is_file():
            files.append(path)
    return files


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _read_text_if_applicable(path: Path) -> str | None:
    """Read likely text without relying on filename extensions."""

    try:
        data = path.read_bytes()
    except OSError as error:
        raise AssertionError(f"Unable to read {_relative(path)}: {error}") from error
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _remove_allowed_vendor_identifiers(line: str) -> str:
    return IOS_VENDOR_IDENTIFIER_RE.sub("", line)


def _remove_allowed_documentation_code_spans(line: str) -> str:
    """Remove only code spans that name an unavoidable iOS artifact."""

    allowed_code = re.compile(
        r"""(?x)
        (?:
            IronSourceSDK
            | IronSourceAdQualitySDK
            | IronSource[A-Za-z0-9]+Adapter
            | IronSource/IronSource\.h
            | \#import\s+(?:<IronSource/IronSource\.h>|"IronSource/IronSource\.h")
            | pod\s+['"](?:IronSourceSDK|IronSourceAdQualitySDK|IronSource[A-Za-z0-9]+Adapter)['"]
        )
        """
    )

    def replace_if_allowed(match: re.Match[str]) -> str:
        contents = match.group(1)
        return "" if allowed_code.fullmatch(contents) else match.group(0)

    return re.sub(r"`([^`\n]+)`", replace_if_allowed, line)


def _old_name_allowed(relative: str, line: str) -> bool:
    if relative == "extension-levelplay/manifests/ios/Podfile":
        return OLD_NAME_RE.search(_remove_allowed_vendor_identifiers(line)) is None

    if relative in {
        "updater/ios.py",
        "updater/ios_networks.json",
        "updater/networks.json",
    }:
        return OLD_NAME_RE.search(_remove_allowed_vendor_identifiers(line)) is None

    if (
        relative == "extension-levelplay/src/levelplay_ios.mm"
        and IOS_HEADER_IMPORT_RE.fullmatch(line.strip())
    ):
        return True

    if relative in {"README.md", "docs/index.md"}:
        remaining = _remove_allowed_documentation_code_spans(line)
        return OLD_NAME_RE.search(remaining) is None

    return False


def _format_findings(findings: list[str], heading: str) -> str:
    if not findings:
        return ""
    limit = 40
    rendered = "\n".join(f"  - {finding}" for finding in findings[:limit])
    if len(findings) > limit:
        rendered += f"\n  - ... and {len(findings) - limit} more"
    return f"{heading}\n{rendered}"


def _parse_cpp_integer_constants(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for name, raw_value in re.findall(
        r"^\s*([A-Z][A-Z0-9_]+)\s*=\s*(-?\d+)\s*,?\s*$",
        text,
        re.MULTILINE,
    ):
        value = int(raw_value)
        if name in values and values[name] != value:
            raise AssertionError(
                f"C++ constant {name} has conflicting values "
                f"{values[name]} and {value}"
            )
        values[name] = value
    return values


def _parse_java_integer_constants(text: str) -> dict[str, int]:
    return {
        name: int(raw_value)
        for name, raw_value in re.findall(
            r"\b(?:private|public|protected)?\s*static\s+final\s+int\s+"
            r"([A-Z][A-Z0-9_]+)\s*=\s*(-?\d+)\s*;",
            text,
        )
    }


def _parse_script_api_members(text: str) -> list[tuple[str, str]]:
    return re.findall(
        r"(?m)^  - name:\s*([A-Za-z][A-Za-z0-9_]*)\s*\n"
        r"    type:\s*([A-Za-z][A-Za-z0-9_]*)\s*$",
        text,
    )


def _script_declares_check_option(path: Path) -> bool:
    """Detect --check statically; importing an updater could perform I/O."""

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == "--check"
        for node in ast.walk(tree)
    )


class LevelPlayMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository_files = _repository_files()

    def _read_required(self, path: Path) -> str:
        self.assertTrue(
            path.is_file(),
            f"Missing prerequisite file: {_relative(path)}. "
            "Complete the final extension-levelplay layout first.",
        )
        return path.read_text(encoding="utf-8")

    def test_expected_levelplay_layout_exists(self) -> None:
        missing = [
            relative
            for relative in EXPECTED_SOURCE_PATHS
            if not (ROOT / relative).is_file()
        ]
        self.assertFalse(
            missing,
            "The final LevelPlay source layout is incomplete:\n"
            + "\n".join(f"  - missing {path}" for path in missing),
        )

    def test_no_repository_path_uses_old_name(self) -> None:
        bad_paths = sorted(
            _relative(path)
            for path in self.repository_files
            if not _relative(path).startswith("tests/")
            and OLD_NAME_RE.search(_relative(path))
        )
        self.assertFalse(
            bad_paths,
            "Repository paths still use the old product name:\n"
            + "\n".join(f"  - {path}" for path in bad_paths),
        )

    def test_no_legacy_content_remains(self) -> None:
        findings: list[str] = []
        for path in self.repository_files:
            relative = _relative(path)
            if relative.startswith("tests/"):
                continue
            text = _read_text_if_applicable(path)
            if text is None:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                for description, pattern in LEGACY_PATTERNS.items():
                    if pattern.search(line):
                        findings.append(
                            f"{relative}:{line_number}: {description}: "
                            f"{line.strip()[:180]}"
                        )

                if OLD_NAME_RE.search(line) and not _old_name_allowed(relative, line):
                    findings.append(
                        f"{relative}:{line_number}: old product name outside the "
                        f"narrow iOS vendor allowlist: {line.strip()[:180]}"
                    )

        self.assertFalse(
            findings,
            _format_findings(
                findings,
                "Legacy dependencies, APIs, domains, or names remain:",
            ),
        )

    def test_core_sdk_versions_are_current(self) -> None:
        android_gradle = self._read_required(
            EXTENSION / "manifests/android/build.gradle"
        )
        android_versions = re.findall(
            r"com\.unity3d\.ads-mediation:mediation-sdk:([^'\"\s]+)",
            android_gradle,
        )
        self.assertEqual(
            [ANDROID_SDK_VERSION],
            android_versions,
            "Android must declare exactly "
            f"com.unity3d.ads-mediation:mediation-sdk:{ANDROID_SDK_VERSION}",
        )

        podfile = self._read_required(EXTENSION / "manifests/ios/Podfile")
        ios_versions = re.findall(
            r"""pod\s+['"]IronSourceSDK['"]\s*,\s*['"]([^'"]+)['"]""",
            podfile,
        )
        self.assertEqual(
            [IOS_SDK_VERSION],
            ios_versions,
            f"iOS must declare exactly pod 'IronSourceSDK','{IOS_SDK_VERSION}'",
        )

    def test_module_and_project_identity_is_levelplay(self) -> None:
        ext_manifest = self._read_required(EXTENSION / "ext.manifest")
        self.assertRegex(
            ext_manifest,
            r'(?m)^name:\s*["\']?LevelPlayExt["\']?\s*$',
            "ext.manifest must identify the extension as LevelPlayExt",
        )

        ext_properties = self._read_required(EXTENSION / "ext.properties")
        self.assertRegex(
            ext_properties,
            r"(?m)^\[levelplay\]\s*$",
            "ext.properties must expose the [levelplay] configuration group",
        )

        script_api = self._read_required(EXTENSION / "api/levelplay.script_api")
        self.assertRegex(
            script_api,
            r"(?m)^-\s+name:\s+levelplay\s*$",
            "The documented Lua module must be named levelplay",
        )

        native_module = self._read_required(EXTENSION / "src/levelplay.cpp")
        self.assertRegex(native_module, r'#define\s+LIB_NAME\s+"LevelPlay"')
        self.assertRegex(native_module, r'#define\s+MODULE_NAME\s+"levelplay"')
        self.assertRegex(
            native_module,
            r"#define\s+EXTENSION_NAME\s+LevelPlayExt",
        )

        java_bridge = self._read_required(
            EXTENSION / "src/java/com/defold/levelplay/LevelPlayJNI.java"
        )
        self.assertRegex(
            java_bridge,
            r"(?m)^package\s+com\.defold\.levelplay;\s*$",
        )
        self.assertIn("public final class LevelPlayJNI", java_bridge)

        game_project = self._read_required(ROOT / "game.project")
        self.assertRegex(
            game_project,
            r"(?m)^include_dirs\s*=\s*extension-levelplay\s*$",
        )
        self.assertRegex(game_project, r"(?m)^\[levelplay\]\s*$")
        self.assertRegex(
            game_project,
            r"(?m)^package\s*=\s*com\.defold\.levelplay\s*$",
        )
        self.assertRegex(
            game_project,
            r"(?m)^bundle_identifier\s*=\s*com\.defold\.levelplay\s*$",
        )

    def test_lua_api_and_native_registration_are_exact(self) -> None:
        api_text = self._read_required(EXTENSION / "api/levelplay.script_api")
        api_declarations = _parse_script_api_members(api_text)
        api_member_names = [name for name, _ in api_declarations]
        self.assertEqual(
            len(api_member_names),
            len(set(api_member_names)),
            "The LevelPlay script API contains duplicate top-level members",
        )
        api_functions = {
            name for name, member_type in api_declarations if member_type == "function"
        }
        api_constants = {
            name for name, member_type in api_declarations if member_type == "number"
        }
        unexpected_types = sorted(
            (name, member_type)
            for name, member_type in api_declarations
            if member_type not in {"function", "number"}
        )
        self.assertFalse(
            unexpected_types,
            "Unexpected top-level LevelPlay API member types: "
            + ", ".join(f"{name}={kind}" for name, kind in unexpected_types),
        )
        self.assertSetEqual(
            EXPECTED_LUA_FUNCTIONS,
            api_functions,
            "The documented LevelPlay function surface changed; update the "
            "contract intentionally rather than silently adding/removing APIs",
        )
        self.assertSetEqual(
            EXPECTED_LUA_CONSTANTS,
            api_constants,
            "The documented LevelPlay constant surface changed; update the "
            "contract intentionally rather than silently adding/removing constants",
        )

        native_text = self._read_required(EXTENSION / "src/levelplay.cpp")
        methods_match = re.search(
            r"static\s+const\s+luaL_reg\s+ModuleMethods\[\]\s*=\s*\{"
            r"(?P<body>.*?)^\};",
            native_text,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(
            methods_match,
            "Unable to parse the native LevelPlay ModuleMethods table",
        )
        registered_list = re.findall(
            r'\{\s*"([a-z][a-z0-9_]*)"\s*,',
            methods_match.group("body"),
        )
        self.assertEqual(
            len(registered_list),
            len(set(registered_list)),
            "The native LevelPlay method table contains duplicate Lua names",
        )
        registered_functions = set(registered_list)

        exported_list = re.findall(
            r"\bSET_CONSTANT\(([A-Z][A-Z0-9_]*)\)", native_text
        )
        self.assertEqual(
            len(exported_list),
            len(set(exported_list)),
            "A LevelPlay constant is exported more than once",
        )
        exported_constants = set(exported_list)

        self.assertSetEqual(
            api_functions,
            registered_functions,
            "Documented and natively registered LevelPlay functions differ",
        )
        self.assertSetEqual(
            api_constants,
            exported_constants,
            "Documented and natively exported LevelPlay constants differ",
        )

    def test_catalog_and_extension_switches_match_exactly(self) -> None:
        catalog_path = ROOT / "updater/networks.json"
        catalog = json.loads(self._read_required(catalog_path))
        networks = catalog.get("networks")
        self.assertIsInstance(
            networks,
            dict,
            "updater/networks.json must contain a networks object",
        )

        expected_android = {
            f"{name}_android"
            for name, network in networks.items()
            if isinstance(network, dict) and isinstance(network.get("android"), dict)
        }
        expected_ios = {
            f"{name}_ios"
            for name, network in networks.items()
            if isinstance(network, dict) and isinstance(network.get("ios"), dict)
        }

        properties_text = self._read_required(EXTENSION / "ext.properties")
        property_rows = re.findall(
            r"(?m)^([a-z][a-z0-9_]+)\.(private|type|default|label)\s*=\s*(.*)$",
            properties_text,
        )
        definitions: dict[str, dict[str, str]] = {}
        for key, attribute, value in property_rows:
            definitions.setdefault(key, {})[attribute] = value.strip()

        actual_android = {
            key
            for key, attributes in definitions.items()
            if key.endswith("_android") and attributes.get("type") == "bool"
        }
        actual_ios = {
            key
            for key, attributes in definitions.items()
            if key.endswith("_ios") and attributes.get("type") == "bool"
        }

        self.assertSetEqual(
            expected_android,
            actual_android,
            "Android adapter switches in ext.properties and networks.json differ",
        )
        self.assertSetEqual(
            expected_ios,
            actual_ios,
            "iOS adapter switches in ext.properties and networks.json differ",
        )

        for key in sorted(expected_android | expected_ios):
            with self.subTest(switch=key):
                attributes = definitions[key]
                self.assertEqual("1", attributes.get("private"))
                self.assertEqual("bool", attributes.get("type"))
                self.assertEqual("0", attributes.get("default"))
                self.assertTrue(
                    attributes.get("label"),
                    f"{key} must have a non-empty editor label",
                )

    def test_example_uses_only_public_levelplay_members(self) -> None:
        api_text = self._read_required(EXTENSION / "api/levelplay.script_api")
        public_members = {
            name for name, _ in _parse_script_api_members(api_text)
        }

        used_members: dict[str, set[str]] = {}
        for path in sorted((ROOT / "example").rglob("*")):
            if not path.is_file() or path.suffix not in {
                ".lua",
                ".gui_script",
                ".script",
            }:
                continue
            names = set(
                re.findall(
                    r"\blevelplay\s*\.\s*([A-Za-z][A-Za-z0-9_]*)",
                    path.read_text(encoding="utf-8"),
                )
            )
            if names:
                used_members[_relative(path)] = names

        self.assertTrue(
            used_members,
            "The example does not exercise any LevelPlay public API members",
        )
        invalid = [
            f"{path}: {name}"
            for path, names in used_members.items()
            for name in sorted(names - public_members)
        ]
        self.assertFalse(
            invalid,
            "The example references undocumented or unregistered LevelPlay members:\n"
            + "\n".join(f"  - {item}" for item in invalid),
        )

    def test_example_uses_dirty_larry_test_ui(self) -> None:
        gui_script = self._read_required(ROOT / "example/main.gui_script")
        gui_scene = self._read_required(ROOT / "example/main.gui")
        ui_helper = self._read_required(ROOT / "example/ui.lua")

        self.assertIn('require("example.ui")', gui_script)
        self.assertIn('require("dirtylarry.dirtylarry")', gui_script)
        self.assertIn("self.ui = ui.fill_tree(DATA, actions)", gui_script)
        self.assertIn("dirtylarry:button(el.name, action_id, action", gui_script)
        self.assertIn("function M.fill_tree(data, actions)", ui_helper)
        self.assertIn('template: "/dirtylarry/button.gui"', gui_scene)

        self.assertNotIn(
            "gui.new_box_node",
            gui_script,
            "The test example must use Dirty Larry button templates, not a "
            "replacement runtime UI",
        )
        self.assertNotIn("gui.new_text_node", gui_script)

        expected_buttons = {
            "main",
            "interstitial",
            "rewarded",
            "banner",
            "initialize",
            "sdk_version",
            "validate",
            "test_suite",
            "tracking_status",
            "request_tracking",
            "dynamic_user_id",
            "create_interstitial",
            "load_interstitial",
            "interstitial_ready",
            "interstitial_capped",
            "show_interstitial",
            "destroy_interstitial",
            "create_rewarded",
            "load_rewarded",
            "rewarded_ready",
            "rewarded_capped",
            "get_reward",
            "show_rewarded",
            "destroy_rewarded",
            "create_banner",
            "load_banner",
            "show_banner",
            "hide_banner",
            "pause_banner",
            "resume_banner",
            "destroy_banner",
        }
        template_ids = set()
        for node_block in re.split(r"(?m)^nodes \{\s*$", gui_scene)[1:]:
            if 'template: "/dirtylarry/button.gui"' not in node_block:
                continue
            node_id = re.search(r'(?m)^\s*id: "([^"]+)"\s*$', node_block)
            self.assertIsNotNone(node_id, "Dirty Larry template node has no ID")
            template_ids.add(node_id.group(1))
        self.assertSetEqual(
            expected_buttons,
            template_ids,
            "Dirty Larry controls and the LevelPlay test surface differ",
        )

    def test_docs_explain_reusable_ad_object_lifecycle(self) -> None:
        manual = self._read_required(ROOT / "docs/index.md")
        api = self._read_required(EXTENSION / "api/levelplay.script_api")

        self.assertIn("### Ad objects, ad units, and placements", manual)
        self.assertIn("Create an ad object once", manual)
        self.assertIn("A **placement** is not an object", manual)
        self.assertRegex(
            manual,
            r"One\s+successful load provides one fullscreen impression",
        )
        self.assertIn("load the same handle again", manual)
        self.assertIn("Do not recreate the object for every impression", manual)
        self.assertIn("Creation parameters are not per load or show", manual)
        self.assertIn("`bid_floor` is the minimum eCPM in USD", manual)
        self.assertIn("destroy the handle and create a new object", manual)
        self.assertIn("Selected separately for each impression", manual)
        self.assertRegex(
            manual,
            r"The repository example\s+automatically creates",
        )
        self.assertIn("**Create**", manual)
        self.assertIn("**Destroy**", manual)

        self.assertIn(
            "multiple load/show cycles with the same ad-unit ID",
            api,
        )
        self.assertIn("Optional minimum eCPM in USD", api)
        self.assertIn("fixed for the object's lifetime", api)
        self.assertIn("selected separately on every show", api)
        self.assertIn(
            "call this again on the same handle instead of creating another object",
            api,
        )
        self.assertIn(
            "placement is a dashboard presentation point, not an ad object",
            api,
        )

    def test_att_order_banner_visibility_and_ios_lifetime_guards(self) -> None:
        example = self._read_required(ROOT / "example/main.gui_script")
        self.assertIn(
            "status == levelplay.TRACKING_STATUS_NOT_DETERMINED",
            example,
        )
        self.assertIn("self.tracking_for_init = true", example)
        self.assertIn("levelplay.request_tracking_authorization()", example)
        self.assertRegex(
            example,
            r"(?s)message_id\s*==\s*levelplay\.MSG_TRACKING"
            r".*?set_meta_advertiser_tracking"
            r".*?continue_initialization\(self\)",
            "The example must apply the terminal ATT result before LevelPlay init",
        )

        android = self._read_required(
            EXTENSION / "src/java/com/defold/levelplay/LevelPlayJNI.java"
        )
        self.assertIn("adView.setVisibility(View.VISIBLE)", android)
        self.assertNotIn("adView.setVisibility(View.GONE);\n                    record.adView", android)
        self.assertIn("record.windowManager.addView", android)
        self.assertIn("record.windowManager.removeView", android)
        self.assertIn("if (record.attached && record.layout.isAttachedToWindow())", android)
        self.assertIn("record.layout.setVisibility(View.GONE)", android)
        self.assertIn("record.layout.setVisibility(View.VISIBLE)", android)
        self.assertNotIn("activity.addContentView(adView", android)
        self.assertNotIn("setOnApplyWindowInsetsListener", android)

        ios = self._read_required(EXTENSION / "src/levelplay_ios.mm")
        self.assertIn("ad.hidden = NO;", ios)
        self.assertIn("generation != s_LifetimeGeneration", ios)
        self.assertRegex(
            ios,
            r"(?s)void\s+SetCOPPA\([^)]*\)\s*\{"
            r".*?s_Initializing\s*\|\|\s*s_Initialized"
            r".*?setCOPPA",
            "iOS must reject post-init COPPA mutations",
        )

    def test_automation_bridge_dependency_is_preserved(self) -> None:
        game_project = self._read_required(ROOT / "game.project")
        project_section_match = re.search(
            r"(?ms)^\[project\]\s*$\n(?P<body>.*?)(?=^\[[^\]]+\]\s*$|\Z)",
            game_project,
        )
        self.assertIsNotNone(
            project_section_match,
            "game.project does not contain a parseable [project] section",
        )
        dependencies = re.findall(
            r"(?m)^dependencies#\d+\s*=\s*(\S+)\s*$",
            project_section_match.group("body"),
        )
        expected = (
            "https://github.com/defold/extension-automation-bridge/"
            "archive/refs/tags/2.0.1.zip"
        )
        self.assertIn(
            expected,
            dependencies,
            "The existing pinned automation bridge dependency was removed from "
            "game.project",
        )

    def test_android_and_cpp_callback_constants_match(self) -> None:
        cpp_sources = []
        for suffix in ("*.h", "*.cpp"):
            for path in (EXTENSION / "src").glob(suffix):
                cpp_sources.append(path.read_text(encoding="utf-8"))
        cpp_constants = _parse_cpp_integer_constants("\n".join(cpp_sources))

        java_path = EXTENSION / "src/java/com/defold/levelplay/LevelPlayJNI.java"
        java_constants = _parse_java_integer_constants(
            self._read_required(java_path)
        )

        missing_cpp = sorted(
            EXPECTED_CROSS_PLATFORM_CALLBACK_CONSTANTS - cpp_constants.keys()
        )
        missing_java = sorted(
            EXPECTED_CROSS_PLATFORM_CALLBACK_CONSTANTS - java_constants.keys()
        )
        self.assertFalse(
            missing_cpp or missing_java,
            "Callback constants could not be compared:"
            + (
                "\n  absent from C++: " + ", ".join(missing_cpp)
                if missing_cpp
                else ""
            )
            + (
                "\n  absent from Java: " + ", ".join(missing_java)
                if missing_java
                else ""
            ),
        )

        mismatches = [
            f"{name}: C++={cpp_constants[name]}, Java={java_constants[name]}"
            for name in sorted(EXPECTED_CROSS_PLATFORM_CALLBACK_CONSTANTS)
            if cpp_constants[name] != java_constants[name]
        ]
        self.assertFalse(
            mismatches,
            "The Android callback ABI has drifted from C++:\n"
            + "\n".join(f"  - {item}" for item in mismatches),
        )

    def test_callback_replacement_is_deferred_until_teardown(self) -> None:
        callback_source = self._read_required(
            EXTENSION / "src/levelplay_callback.cpp"
        )

        self.assertRegex(
            callback_source,
            r"static\s+uint32_t\s+g_CallbackInvocationDepth\s*=\s*0\s*;",
        )
        self.assertRegex(
            callback_source,
            r"static\s+dmArray<dmScript::LuaCallbackInfo\*>\s+"
            r"g_DeferredCallbacks\s*;",
        )

        retire_match = re.search(
            r"static\s+void\s+RetireCallback\s*\([^)]*\)\s*\{"
            r"(?P<body>.*?)^\}",
            callback_source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(retire_match, "Unable to parse RetireCallback")
        retire_body = retire_match.group("body")
        self.assertIn("g_CallbackInvocationDepth == 0", retire_body)
        self.assertIn("g_DeferredCallbacks.Push(callback)", retire_body)

        invoke_match = re.search(
            r"static\s+void\s+InvokeCallback\s*\([^)]*\)\s*\{"
            r"(?P<body>.*?)^\}",
            callback_source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(invoke_match, "Unable to parse InvokeCallback")
        invoke_body = invoke_match.group("body")
        self.assertIn(
            "dmScript::LuaCallbackInfo* callback = g_LuaCallback",
            invoke_body,
        )

        increment = invoke_body.index("++g_CallbackInvocationDepth")
        call = invoke_body.index("dmScript::PCall")
        teardown = invoke_body.index("dmScript::TeardownCallback(callback)")
        decrement = invoke_body.index("--g_CallbackInvocationDepth")
        flush = invoke_body.index("FlushDeferredCallbacks()")
        self.assertLess(increment, call)
        self.assertLess(call, teardown)
        self.assertLess(teardown, decrement)
        self.assertLess(decrement, flush)

        set_match = re.search(
            r"void\s+SetLuaCallback\s*\([^)]*\)\s*\{"
            r"(?P<body>.*?)^\}",
            callback_source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(set_match, "Unable to parse SetLuaCallback")
        set_body = set_match.group("body")
        replace = set_body.index("g_LuaCallback = replacement")
        retire = set_body.index("RetireCallback(previous)")
        self.assertLess(replace, retire)
        self.assertNotIn("DestroyCallback()", set_body)

        finalize_match = re.search(
            r"void\s+FinalizeCallback\s*\(\s*\)\s*\{"
            r"(?P<body>.*?)^\}",
            callback_source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(finalize_match, "Unable to parse FinalizeCallback")
        finalize_body = finalize_match.group("body")
        self.assertIn("DestroyCallback()", finalize_body)
        self.assertIn("FlushDeferredCallbacks()", finalize_body)

    def _assert_updater_check(self, updater_name: str) -> None:
        path = ROOT / "updater" / updater_name
        self.assertTrue(path.is_file(), f"Missing updater script: {path}")
        if not _script_declares_check_option(path):
            self.skipTest(f"{updater_name} does not implement a --check option")

        try:
            result = subprocess.run(
                [sys.executable, str(path), "--check"],
                cwd=ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except subprocess.TimeoutExpired as error:
            output = error.stdout or ""
            self.fail(
                f"{updater_name} --check exceeded 180 seconds.\n"
                f"Output before timeout:\n{output}"
            )

        self.assertEqual(
            0,
            result.returncode,
            f"{updater_name} --check failed with exit code "
            f"{result.returncode}:\n{result.stdout}",
        )

    def test_android_updater_check(self) -> None:
        self._assert_updater_check("android.py")

    def test_ios_updater_check(self) -> None:
        self._assert_updater_check("ios.py")


if __name__ == "__main__":
    unittest.main()
