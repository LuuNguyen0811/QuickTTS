#!/bin/zsh
setopt errexit nounset pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
"$PY" -m pip install pyinstaller
"$PY" "$ROOT/ensure_models.py"
"$PY" "$ROOT/assets/make_icons.py"
iconutil -c icns "$ROOT/assets/AppIcon.iconset" -o "$ROOT/assets/AppIcon.icns"
"$PY" -m PyInstaller --noconfirm --windowed --name QuickTTS \
  --icon "$ROOT/assets/AppIcon.icns" \
  --osx-bundle-identifier local.quicktts \
  --collect-all kokoro_onnx \
  --collect-all espeakng_loader \
  --collect-all phonemizer \
  --collect-all onnxruntime \
  --add-data "models/kokoro-v1.0.int8.onnx:models" \
  --add-data "models/kokoro-v1.0.onnx:models" \
  --add-data "models/voices-v1.0.bin:models" \
  --add-data "assets/menubarTemplate.png:assets" \
  --hidden-import AppKit \
  --hidden-import Foundation \
  --hidden-import Quartz \
  --hidden-import ApplicationServices \
  --hidden-import CoreFoundation \
  --hidden-import objc \
  --hidden-import hotkey \
  kokoro_app.py

PLIST="$ROOT/dist/QuickTTS.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleName QuickTTS" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName QuickTTS" "$PLIST"
/usr/libexec/PlistBuddy -c "Delete :LSEnvironment" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSEnvironment dict" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSEnvironment:MallocLargeCache string 0" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSEnvironment:MallocSpaceEfficient string 1" "$PLIST"
codesign --force --deep --sign - "$ROOT/dist/QuickTTS.app"

echo "self-test"
rm -f /tmp/kokoro-app-self-test.txt
"$ROOT/dist/QuickTTS.app/Contents/MacOS/QuickTTS" --self-test
cat /tmp/kokoro-app-self-test.txt

STAGE="$(mktemp -d)"
cp -R "$ROOT/dist/QuickTTS.app" "$STAGE/QuickTTS.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname QuickTTS -srcfolder "$STAGE" -ov -format UDZO "$ROOT/QuickTTS.dmg"
rm -rf "$STAGE"
ls -lh "$ROOT/QuickTTS.dmg"
echo "built $ROOT/QuickTTS.dmg"
