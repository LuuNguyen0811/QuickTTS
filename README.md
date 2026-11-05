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
- **Shortcut:** click **Record shortcut**, then press the keys. The default is **Option+`**. On the ABC layout, Option+` is a dead key, so include Control if that shortcut does not fire.
- **Test voice** speaks a longer sample sentence.

The shortcut stops whatever is playing and speaks the new selection. With nothing selected, the same shortcut stops the current clip instead of copying. **Stop** in the menu bar menu, and the **Stop** button in Settings, do the same: playback ends, a clip that is still being created is dropped, and the audio file is removed. More than 4000 characters is read from the start through 4000 characters.

The speech model is loaded for that clip and released when the audio has been created. macOS is told not to keep those freed blocks in a memory cache, so the extra memory drops once the clip is ready to play. The next clip loads the model again.

Settings are saved in `~/Library/Application Support/QuickTTS/config.json`.

## Permissions

QuickTTS has to be allowed once, under its own name:

1. **System Settings → Privacy & Security → Accessibility.** Enable **QuickTTS**. This lets it read the selection and copy when an app does not expose the selection.
2. **System Settings → Privacy & Security → Input Monitoring.** Enable **QuickTTS**. This lets the shortcut work in every app.

The menu item **Open Permission Settings** opens those panes. If the shortcut still does nothing after you enable them, quit QuickTTS and open it again.

## Rebuild the disk image

From this repository, `package.sh` uses `.venv`, downloads any model file that is missing or not a real weight file, builds the app, and writes `QuickTTS.dmg` here.

```sh
./package.sh
```

## Command-line server

From this repository, `start.sh` downloads the fast model and voices when `models/` does not already have usable copies, then runs a local server on `127.0.0.1:8765` plus a separate hotkey listener. The listener uses **Option+`** or **Control+Option+`**. Do not run that at the same time as the menu bar app. Both would listen for a shortcut.

```sh
./start.sh
./stop.sh
```
