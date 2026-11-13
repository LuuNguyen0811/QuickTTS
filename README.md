# QuickTTS

## Download

[https://luunguyen0811.github.io/QuickTTS/](https://luunguyen0811.github.io/QuickTTS/)

A tool that speaks selected text with Kokoro, on this Mac, with no API key.

## Install

1. Open `QuickTTS.dmg`.
2. Drag **QuickTTS** onto **Applications**.
3. Open **QuickTTS** from Applications. 
4. Grant permission

QuickTTS appears in the menu bar as a speaker icon. It does not stay in the Dock. The first time it opens, the settings window is shown.

Quit from the menu bar icon. QuickTTS does not start again at login.

## Settings

Open the menu bar icon and choose **Settings…**.

- **Model:** Fast (int8) or Best quality (full). The default is **Best quality (full)**. It is slower and uses more memory. Both are inside the app.
- **Voice:** default Female-Heart. Names look like Male-Eric and Female-Heart. English voices are listed first.
- **Shortcut:** click **Record shortcut**, then press the keys. The default is **Option+`**. On the ABC layout, Option+` is a dead key, so include Control if that shortcut does not fire. The shortcut opens the action menu.
- **Test voice** speaks a longer sample sentence.

The shortcut opens an action menu at the pointer: Speak, Proofread, Rewrite, and Translate. Speak uses Kokoro. Proofread and Rewrite use Apple Intelligence on macOS 26. Translate uses the system Translation framework, and the language you pick is remembered. Escape or a click outside closes the menu. With nothing selected, the same shortcut stops the current clip instead of copying. **Stop** in the menu bar menu, and the **Stop** button in Settings, do the same: playback ends, a clip that is still being created is dropped, and the audio file is removed. More than 4000 characters is read from the start through 4000 characters.

The speech model is loaded for that clip and released when the audio has been created. macOS is told not to keep those freed blocks in a memory cache, so the extra memory drops once the clip is ready to play. The next clip loads the model again.

Settings are saved in `~/Library/Application Support/QuickTTS/config.json`.

## Permissions

QuickTTS has to be allowed once, under its own name:

1. **System Settings → Privacy & Security → Accessibility.** Enable **QuickTTS**. This lets it read the selection and copy when an app does not expose the selection.
2. **System Settings → Privacy & Security → Input Monitoring.** Enable **QuickTTS**. This lets the shortcut work in every app.

The menu item **Open Permission Settings** opens those panes. If the shortcut still does nothing after you enable them, quit QuickTTS and open it again.

## Build

From this repository, `package.sh` uses `.venv`. It installs PyInstaller, downloads any model file that is missing or not a real weight file, builds `dist/QuickTTS.app`, compiles the Swift action menu into that app, signs it, runs a short self-test, and writes `QuickTTS.dmg` here.

```sh
./package.sh
```

To build the app and skip the disk image:

```sh
SKIP_DMG=1 ./package.sh
```

While changing code, run the menu bar app directly instead of packaging it:

```sh
.venv/bin/python kokoro_app.py
```

The action menu is a separate binary, `helper/QuickTTSMenu`. Rebuild it after editing `helper/QuickTTSMenu.swift`, then quit and reopen the Python app so it launches the new helper. `./package.sh` already includes this compile.

```sh
SDK="$(xcrun --sdk macosx --show-sdk-path)"
xcrun --sdk macosx swiftc -O -swift-version 5 -target arm64-apple-macosx15.0 \
  -sdk "$SDK" \
  -framework SwiftUI -framework AppKit -framework Translation \
  -Xlinker -weak_framework -Xlinker FoundationModels \
  -o helper/QuickTTSMenu helper/QuickTTSMenu.swift
```

## Command-line server

From this repository, `start.sh` downloads the fast model and voices when `models/` does not already have usable copies, then runs a local server on `127.0.0.1:8765` plus a separate hotkey listener. The listener uses **Option+`** or **Control+Option+`**. Do not run that at the same time as the menu bar app. Both would listen for a shortcut.

```sh
./start.sh
./stop.sh
```
