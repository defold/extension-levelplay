#!/usr/bin/env python3

"""Shared deterministic catalog and manifest updater helpers."""

from __future__ import annotations

import difflib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


UPDATER_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = UPDATER_DIR.parent
CATALOG_PATH = UPDATER_DIR / "networks.json"
DEFAULT_EXTENSION_DIR = REPOSITORY_ROOT / "extension-levelplay"
MAVEN_CENTRAL = "https://repo1.maven.org/maven2"
GOOGLE_MAVEN = "https://dl.google.com/dl/android/maven2"
COCOAPODS_TRUNK = "https://trunk.cocoapods.org/api/v1/pods"
USER_AGENT = "extension-levelplay-updater/2.0"

ANDROID_KEYS = (
    "applovin",
    "aps",
    "bidmachine",
    "bigo",
    "chartboost",
    "dt_exchange",
    "admob",
    "hyprmx",
    "inmobi",
    "liftoff",
    "line",
    "meta",
    "mintegral",
    "mobilefuse",
    "moloco",
    "ogury",
    "pangle",
    "pubmatic",
    "smaato",
    "superawesome",
    "unity_ads",
    "verve",
    "vk",
    "yandex",
    "yso",
)

IOS_KEYS = ANDROID_KEYS


class UpdaterError(RuntimeError):
    """A concise user-facing updater failure."""


def load_catalog() -> dict[str, Any]:
    with CATALOG_PATH.open(encoding="utf-8") as catalog_file:
        catalog = json.load(catalog_file)

    if catalog.get("schema_version") != 1:
        raise UpdaterError(
            f"Unsupported catalog schema in {CATALOG_PATH}: "
            f"{catalog.get('schema_version')!r}"
        )

    networks = catalog.get("networks")
    if not isinstance(networks, dict):
        raise UpdaterError(f"{CATALOG_PATH} must contain a networks object")

    expected = set(IOS_KEYS)
    actual = set(networks)
    if actual != expected:
        missing = ", ".join(sorted(expected - actual)) or "none"
        extra = ", ".join(sorted(actual - expected)) or "none"
        raise UpdaterError(
            f"Catalog network keys do not match the supported set "
            f"(missing: {missing}; extra: {extra})"
        )

    levelplay_android = catalog.get("levelplay", {}).get("android", {})
    parse_coordinate(levelplay_android.get("coordinate", ""))
    for coordinate in levelplay_android.get("dependencies", []):
        parse_coordinate(coordinate)

    for key in ANDROID_KEYS:
        android = networks[key].get("android")
        if not isinstance(android, dict):
            raise UpdaterError(f"Catalog network {key!r} has no Android data")
        parse_coordinate(android.get("adapter", ""))
        dependencies = android.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise UpdaterError(f"Catalog network {key!r} dependencies must be a list")
        for coordinate in dependencies:
            parse_coordinate(coordinate)

    for key in IOS_KEYS:
        ios = networks[key].get("ios")
        if not isinstance(ios, dict):
            raise UpdaterError(f"Catalog network {key!r} has no iOS data")
        if not ios.get("adapter_version"):
            raise UpdaterError(f"Catalog network {key!r} has no iOS adapter version")

    return catalog


def parse_coordinate(coordinate: str) -> tuple[str, str, str]:
    parts = coordinate.split(":")
    if len(parts) != 3 or not all(parts):
        raise UpdaterError(f"Invalid Maven coordinate: {coordinate!r}")
    return parts[0], parts[1], parts[2]


def write_or_check(path: Path, content: str, check: bool) -> bool:
    """Write generated content, or return False and print a diff in check mode."""

    if not content.endswith("\n"):
        content += "\n"

    if check:
        if not path.exists():
            print(f"missing generated file: {path}", file=sys.stderr)
            return False
        current = path.read_text(encoding="utf-8")
        if current == content:
            print(f"up to date: {path}")
            return True
        diff = difflib.unified_diff(
            current.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=str(path),
            tofile=f"{path} (generated)",
        )
        sys.stderr.writelines(diff)
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"generated: {path}")
    return True


def fetch_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (OSError, urllib.error.URLError) as error:
        raise UpdaterError(f"Unable to fetch {url}: {error}") from error


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    try:
        value = json.loads(fetch_text(url, timeout))
    except json.JSONDecodeError as error:
        raise UpdaterError(f"Invalid JSON from {url}: {error}") from error
    if not isinstance(value, dict):
        raise UpdaterError(f"Expected a JSON object from {url}")
    return value


def maven_metadata_url(coordinate: str, repository: str = MAVEN_CENTRAL) -> str:
    group, artifact, _ = parse_coordinate(coordinate)
    path = "/".join((group.replace(".", "/"), artifact, "maven-metadata.xml"))
    return f"{repository.rstrip('/')}/{path}"


def maven_versions(
    coordinate: str, repository: str, timeout: float
) -> tuple[str | None, set[str]]:
    url = maven_metadata_url(coordinate, repository)
    try:
        root = ET.fromstring(fetch_text(url, timeout))
    except ET.ParseError as error:
        raise UpdaterError(f"Invalid Maven metadata XML from {url}: {error}") from error
    release_node = root.find("./versioning/release")
    release = release_node.text if release_node is not None else None
    versions = {
        node.text
        for node in root.findall("./versioning/versions/version")
        if node.text
    }
    return release, versions


def dependency_repository(
    coordinate: str, configured_repositories: Iterable[str]
) -> str:
    group, _, _ = parse_coordinate(coordinate)
    repositories = tuple(configured_repositories)
    if group.startswith(("com.google.", "com.android.", "androidx.")) and "google" in repositories:
        return GOOGLE_MAVEN
    custom = tuple(value for value in repositories if value != "google")
    return custom[0] if custom else MAVEN_CENTRAL


def cocoa_latest_spec(pod: str, timeout: float) -> dict[str, Any]:
    encoded_pod = urllib.parse.quote(pod, safe="")
    return fetch_json(f"{COCOAPODS_TRUNK}/{encoded_pod}/specs/latest", timeout)
