#!/usr/bin/env python3

"""Generate and validate the Defold iOS LevelPlay manifests."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from common import (
    DEFAULT_EXTENSION_DIR,
    IOS_KEYS,
    UpdaterError,
    load_catalog,
    write_or_check,
)


DEFAULT_SWIFT_PACKAGES = DEFAULT_EXTENSION_DIR / "manifests/ios/SwiftPackages.json"
DEFAULT_INFO_PLIST = DEFAULT_EXTENSION_DIR / "manifests/ios/Info.plist"

# These are the current official Swift package repositories and products.
# Their repository and product identifiers cannot be replaced by the public
# LevelPlay product name.
PACKAGE_URL = "https://github.com/ironsource-mobile/{repo}"
LEVELPLAY_SDK_PACKAGE = ("LevelPlay-Swift-Package", "UnityMediationSDK")
AD_QUALITY_PACKAGE = ("Unity-Ad-Quality-Swift-Package", "AdQuality")
ADAPTER_PACKAGES = {
    "applovin": ("LevelPlay-AppLovin-Adapter-Swift-Package", "AppLovinAdapter"),
    "aps": ("LevelPlay-APS-Adapter-Swift-Package", "APSAdapter"),
    "bidmachine": ("LevelPlay-BidMachine-Adapter-Swift-Package", "BidMachineAdapter"),
    "bigo": ("LevelPlay-Bigo-Adapter-Swift-Package", "BigoAdapter"),
    "chartboost": ("LevelPlay-Chartboost-Adapter-Swift-Package", "ChartboostAdapter"),
    "dt_exchange": ("LevelPlay-Fyber-Adapter-Swift-Package", "FyberAdapter"),
    "admob": ("LevelPlay-AdMob-Adapter-Swift-Package", "AdMobAdapter"),
    "hyprmx": ("LevelPlay-HyprMX-Adapter-Swift-Package", "HyprMXAdapter"),
    "inmobi": ("LevelPlay-InMobi-Adapter-Swift-Package", "InMobiAdapter"),
    "liftoff": ("LevelPlay-Vungle-Adapter-Swift-Package", "VungleAdapter"),
    "line": ("LevelPlay-Line-Adapter-Swift-Package", "LineAdapter"),
    "meta": ("LevelPlay-Facebook-Adapter-Swift-Package", "FacebookAdapter"),
    "mintegral": ("LevelPlay-Mintegral-Adapter-Swift-Package", "MintegralAdapter"),
    "mobilefuse": ("LevelPlay-MobileFuse-Adapter-Swift-Package", "MobileFuseAdapter"),
    "moloco": ("LevelPlay-Moloco-Adapter-Swift-Package", "MolocoAdapter"),
    "ogury": ("LevelPlay-Ogury-Adapter-Swift-Package", "OguryAdapter"),
    "pangle": ("LevelPlay-Pangle-Adapter-Swift-Package", "PangleAdapter"),
    "pubmatic": ("LevelPlay-PubMatic-Adapter-Swift-Package", "PubMaticAdapter"),
    "smaato": ("LevelPlay-Smaato-Adapter-Swift-Package", "SmaatoAdapter"),
    "superawesome": ("LevelPlay-SuperAwesome-Adapter-Swift-Package", "SuperAwesomeAdapter"),
    "unity_ads": ("LevelPlay-UnityAds-Adapter-Swift-Package", "UnityAdsAdapter"),
    "verve": ("LevelPlay-Verve-Adapter-Swift-Package", "VerveAdapter"),
    "vk": ("LevelPlay-MyTarget-Adapter-Swift-Package", "MyTargetAdapter"),
    "yandex": ("LevelPlay-Yandex-Adapter-Swift-Package", "YandexAdapter"),
    "yso": ("LevelPlay-YSO-Adapter-Swift-Package", "YSOAdapter"),
}


def condition(key: str) -> str:
    return f"levelplay.{key}_ios"


def package_entry(package: tuple[str, str], version: str) -> str:
    repo, product = package
    return json.dumps(
        {
            "url": PACKAGE_URL.format(repo=repo),
            "version": version,
            "products": [product],
        }
    )


def render_swift_packages(catalog: dict[str, Any]) -> str:
    # Every adapter entry starts with a comma so that the JSON stays valid for
    # any combination of enabled adapters.
    ios = catalog["levelplay"]["ios"]
    lines = [
        "{",
        '  "platform": "ios",',
        f'  "minVersion": "{ios["minimum_version"]}",',
        # The static SPM wrapper receives the LevelPlay SDK's binary libraries
        # twice and fails to link; Extender links this graph only as a dylib.
        '  "wrapperType": "dynamic",',
        '  "packages": [',
        f"    {package_entry(LEVELPLAY_SDK_PACKAGE, ios['version'])},",
        f"    {package_entry(AD_QUALITY_PACKAGE, ios['ad_quality_version'])}",
    ]

    for key in IOS_KEYS:
        version = catalog["networks"][key]["ios"]["adapter_version"]
        lines.extend(
            (
                f"{{{{#{condition(key)}}}}}",
                f"    ,{package_entry(ADAPTER_PACKAGES[key], version)}",
                f"{{{{/{condition(key)}}}}}",
            )
        )

    lines.extend(("  ]", "}", ""))
    return "\n".join(lines)


def skadnetwork_lines(catalog: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for identifier in catalog["levelplay"]["ios"]["skadnetwork_ids"]:
        lines.append(
            "            <dict><key>SKAdNetworkIdentifier</key>"
            f"<string>{identifier}</string></dict>"
        )

    for key in IOS_KEYS:
        identifiers = catalog["networks"][key]["ios"].get("skadnetwork_ids", [])
        if not identifiers:
            continue
        lines.append(f"{{{{#{condition(key)}}}}}")
        for identifier in identifiers:
            lines.append(
                "            <dict><key>SKAdNetworkIdentifier</key>"
                f"<string>{identifier}</string></dict>"
            )
        lines.append(f"{{{{/{condition(key)}}}}}")

    return lines


def render_info_plist(catalog: dict[str, Any]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd" '
        '[ <!ATTLIST key merge (keep) #IMPLIED> ]>',
        "<!-- Generated by updater/ios.py from updater/networks.json. -->",
        "<!-- The catalog contains Unity's primary SKAdNetwork IDs. Add the -->",
        "<!-- app/network-specific partner IDs linked from Unity's manual. -->",
        '<plist version="1.0">',
        "    <dict>",
        "        <key merge='keep'>SKAdNetworkItems</key>",
        "        <array>",
        *skadnetwork_lines(catalog),
        "        </array>",
        "",
        "        <key>NSAppTransportSecurity</key>",
        "        <dict>",
        "            <key>NSAllowsArbitraryLoads</key>",
        "            <true/>",
        "        </dict>",
        "",
        "{{#levelplay.admob_ios}}",
        "        <key>GADApplicationIdentifier</key>",
        "        <string>{{levelplay.admob_ios_appid}}</string>",
        "{{/levelplay.admob_ios}}",
        "",
        "        <key>NSUserTrackingUsageDescription</key>",
        "        <string>{{levelplay.ios_tracking_usage_description}}</string>",
        "",
        "        <key>NSAdvertisingAttributionReportEndpoint</key>",
        "        <string>https://postbacks-is.com/</string>",
        "",
        "{{#levelplay.hyprmx_ios}}",
        "        <key>NSCameraUsageDescription</key>",
        "        <string>{{project.title}} requests access to the camera.</string>",
        "        <key>NSPhotoLibraryAddUsageDescription</key>",
        "        <string>{{project.title}} requests permission to save photos.</string>",
        "{{/levelplay.hyprmx_ios}}",
        "    </dict>",
        "</plist>",
        "",
    ]
    return "\n".join(lines)


def generate_or_check(args: argparse.Namespace, check: bool) -> int:
    catalog = load_catalog()
    results = (
        write_or_check(args.swift_packages, render_swift_packages(catalog), check),
        write_or_check(args.info_plist, render_info_plist(catalog), check),
    )
    return 0 if all(results) else 1


def package_tags(repo: str, timeout: float) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", PACKAGE_URL.format(repo=repo)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise UpdaterError(f"Cannot list tags of {repo}: {error}") from error
    tags = [line.rsplit("refs/tags/", 1)[-1] for line in result.stdout.splitlines()]
    return [tag for tag in tags if re.fullmatch(r"\d+(?:\.\d+)*", tag)]


def validate_package(
    package: tuple[str, str], pinned_version: str, timeout: float
) -> bool:
    repo = package[0]
    tags = package_tags(repo, timeout)
    latest_version = max(
        tags, key=lambda tag: tuple(int(part) for part in tag.split(".")), default=""
    )
    if pinned_version not in tags:
        print(f"missing: {repo} has no tag {pinned_version}", file=sys.stderr)
        return False
    if latest_version != pinned_version:
        print(
            f"outdated: {repo} {pinned_version} "
            f"(latest tag is {latest_version or 'unknown'})",
            file=sys.stderr,
        )
        return False
    print(f"verified: {repo}@{pinned_version}")
    return True


def refresh(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    source = catalog["sources"]["ios_mediation_matrix"]
    print(f"Unity compatibility matrix: {source}")

    ok = validate_package(
        LEVELPLAY_SDK_PACKAGE,
        catalog["levelplay"]["ios"]["version"],
        args.timeout,
    )
    ok = validate_package(
        AD_QUALITY_PACKAGE,
        catalog["levelplay"]["ios"]["ad_quality_version"],
        args.timeout,
    ) and ok
    for key in IOS_KEYS:
        version = catalog["networks"][key]["ios"]["adapter_version"]
        ok = validate_package(ADAPTER_PACKAGES[key], version, args.timeout) and ok

    if ok:
        print("iOS catalog metadata is valid.")
        return 0
    print(
        "iOS catalog validation failed. Reconcile versions with the Unity "
        "compatibility matrix before editing updater/networks.json.",
        file=sys.stderr,
    )
    return 1


def add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--swift-packages",
        type=Path,
        default=DEFAULT_SWIFT_PACKAGES,
        help=f"SwiftPackages.json output (default: {DEFAULT_SWIFT_PACKAGES})",
    )
    parser.add_argument(
        "--info-plist",
        type=Path,
        default=DEFAULT_INFO_PLIST,
        help=f"Info.plist output (default: {DEFAULT_INFO_PLIST})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Compatibility aliases: --generate, --check, and --refresh map to "
            "the corresponding commands."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    generate_parser = commands.add_parser(
        "generate", help="generate deterministic iOS manifests"
    )
    add_output_arguments(generate_parser)

    check_parser = commands.add_parser(
        "check", help="diff checked-in iOS manifests against generated output"
    )
    add_output_arguments(check_parser)

    refresh_parser = commands.add_parser(
        "refresh",
        help="validate pinned SDK and adapters against live Swift package tags",
    )
    refresh_parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="per-request network timeout in seconds (default: 20)",
    )
    return parser


def normalize_compatibility_aliases(argv: Sequence[str]) -> list[str]:
    values = list(argv)
    aliases = {
        "--generate": "generate",
        "--check": "check",
        "--refresh": "refresh",
    }
    if values and values[0] in aliases:
        values[0] = aliases[values[0]]
    return values


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    values = normalize_compatibility_aliases(
        sys.argv[1:] if argv is None else argv
    )
    args = parser.parse_args(values)
    try:
        if args.command == "generate":
            return generate_or_check(args, False)
        if args.command == "check":
            return generate_or_check(args, True)
        return refresh(args)
    except UpdaterError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
