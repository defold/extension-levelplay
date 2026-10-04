# Developing the LevelPlay extension

The extension targets the current Unity LevelPlay SDK 9 API on Android and iOS. Breaking SDK upgrades must be reflected in the native implementation, Lua API, API reference, sample, templates, adapter versions, and this documentation in the same change.

The catalog pins LevelPlay 9.6.1 on both platforms and Ad Quality 9.10.0.
Android adapter POMs do not declare their network SDK dependencies; check
Unity's compatibility matrix and the official adapter changelogs when updating
the explicit pins. iOS adapter podspecs declare their supported SDK versions.

## Authoritative references

- [SDK 9.0 migration](https://docs.unity.com/en-us/grow/levelplay/sdk/unity/migrate-to-9-0-0)
- [Initialization API migration](https://docs.unity.com/en-us/grow/levelplay/sdk/unity/migrate-to-init-api)
- [SDK 9 API changes](https://docs.unity.com/en-us/grow/levelplay/sdk/unity/9-0-0-api-changes)
- [Maven Central migration](https://docs.unity.com/en-us/grow/levelplay/sdk/unity/maven-central-migration-guide)
- [Unity Ads to LevelPlay migration](https://docs.unity.com/en-us/grow/levelplay/sdk/unity/migrate-from-unity-ads-to-levelplay)
- [Unity LevelPlay documentation](https://docs.unity.com/en-us/grow/levelplay)
- [Bob command-line build tool](https://defold.com/manuals/bob/)

Use Unity documentation and the SDK headers/artifacts as the source of truth. A Unity-package wrapper can be useful as a flow example, but it is not the native Android or iOS API contract.

## Updating SDKs and adapters

1. Review the current Android and iOS SDK release notes and migration guides.
2. Validate the pinned catalog against the live registries with
   `python3 -B updater/android.py refresh` and
   `python3 -B updater/ios.py refresh`.
3. Regenerate the checked-in manifests with
   `python3 -B updater/android.py generate` and
   `python3 -B updater/ios.py generate`, then run both commands again with
   `check` to prove there is no generated drift.
4. Inspect the generated dependency changes. Confirm every enabled adapter is compatible with the selected core SDK.
5. Update `version.default` in `extension-levelplay/ext.properties`.
6. Confirm Android resolves all mediation artifacts from Maven Central. Add a network-owned repository only when that network's current official integration guide requires it.
7. Confirm iOS pods resolve from the CocoaPods trunk.
8. Review current platform setup requirements, including Android manifest entries and iOS privacy, ATS, and SKAdNetwork configuration.
9. Run the repository scans, API checks, and both Bob builds described below.

The official iOS distribution still contains historical vendor naming in some upstream Pod, framework, header, and class identifiers. Keep those identifiers only where the current vendor artifact requires them; never expose them through the Lua namespace, public API, sample, or extension-owned configuration.

## Adding or removing an adapter

Adapter switches live in the `[levelplay]` section of `game.project` and use the form `<network>_android` or `<network>_ios`.

When adding an adapter:

1. Add its private setting to `extension-levelplay/ext.properties`.
2. Add its current artifact to the Android or iOS dependency template.
3. Add any network-required manifest, plist, repository, or linker settings.
4. Teach the relevant updater about the official artifact and version source.
5. Add the key to the setup guide and build the sample with the adapter enabled.

Do not add a compatibility alias for a retired network or API.

## Verification

From the repository root, run a repository-wide audit for retired public names and APIs. Then resolve and build with the repository-root/local `bob.jar`:

```sh
java -jar bob.jar \
  --archive \
  --platform armv7-android \
  --architectures arm64-android \
  --variant debug \
  --bundle-format apk \
  --build-server https://build.defold.com \
  resolve distclean build bundle

java -jar bob.jar \
  --archive \
  --platform arm64-ios \
  --architectures arm64-ios \
  --variant debug \
  --build-server https://build.defold.com \
  resolve distclean build bundle
```

For release verification, use the exact architectures, build server, signing inputs, and bundle format required by the release workflow. Install the Android APK on a device or emulator, launch it, and inspect logcat for native crashes and initialization results. Install and run the iOS build on a valid signed device or simulator target when signing assets are available.

Bob 1.13.2 supports an Apple Silicon iOS simulator build without device signing:

```sh
java -jar bob.jar \
  --archive \
  --platform arm64_sim-ios \
  --architectures arm64_sim-ios \
  --variant debug \
  --build-server https://build.defold.com \
  --output build/simulator/resources \
  --bundle-output /tmp/levelplay-simulator-bundle \
  resolve build bundle

xcrun simctl install booted /tmp/levelplay-simulator-bundle/LevelPlay.app
xcrun simctl launch booted com.defold.levelplay
```

For an Android keep-rule check, set `android.r8_keep_rules` to
`/builtins/manifests/android/dmengine.keep`, enable the adapters to verify, and
build a release APK. Confirm `build/arm64-android/mapping.txt` identifies R8,
then use the sample's **Validate** button and check the `IntegrationHelper`
logcat entries for every enabled network. AdMob and Ad Manager share the Google
adapter and validator result. Enter **Test Suite** in a fresh process before
using other SDK actions; its network list follows the app key's dashboard
configuration, so enabling an adapter alone does not add it to that list.
