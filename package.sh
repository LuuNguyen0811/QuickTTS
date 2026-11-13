#!/bin/zsh
setopt errexit nounset pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
"$PY" -m pip install pyinstaller
"$PY" "$ROOT/ensure_models.py"
"$PY" "$ROOT/assets/make_icons.py"
iconutil -c icns "$ROOT/assets/AppIcon.iconset" -o "$ROOT/assets/AppIcon.icns"
"$PY" -m PyInstaller --noconfirm --windowed --name ChickEN \
  --icon "$ROOT/assets/AppIcon.icns" \
  --osx-bundle-identifier local.chicken \
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

PLIST="$ROOT/dist/ChickEN.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleName ChickEN" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName ChickEN" "$PLIST"
/usr/libexec/PlistBuddy -c "Delete :LSEnvironment" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSEnvironment dict" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSEnvironment:MallocLargeCache string 0" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSEnvironment:MallocSpaceEfficient string 1" "$PLIST"

SDK="$(xcrun --sdk macosx --show-sdk-path)"
xcrun --sdk macosx swiftc -O -swift-version 5 -target arm64-apple-macosx15.0 \
  -sdk "$SDK" \
  -framework SwiftUI -framework AppKit -framework Translation \
  -Xlinker -weak_framework -Xlinker FoundationModels \
  -o "$ROOT/helper/ChickENMenu" \
  "$ROOT/helper/ChickENMenu.swift"
cp "$ROOT/helper/ChickENMenu" "$ROOT/dist/ChickEN.app/Contents/MacOS/ChickENMenu"
SIGN_DIR="$ROOT/.signing"
KEYCHAIN="$SIGN_DIR/chicken.keychain-db"
SIGN_PASS="chicken-local"
SIGN_NAME="ChickEN Local"
mkdir -p "$SIGN_DIR"
if ! security find-certificate -c "$SIGN_NAME" "$KEYCHAIN" >/dev/null 2>&1; then
  CONFIG="$SIGN_DIR/codesign.cnf"
  cat > "$CONFIG" <<'EOF'
[req]
distinguished_name = dn
prompt = no
x509_extensions = codesign_ext
[dn]
CN = ChickEN Local
[codesign_ext]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
1.2.840.113635.100.6.1.13 = critical,DER:0500
EOF
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -config "$CONFIG" \
    -keyout "$SIGN_DIR/key.pem" \
    -out "$SIGN_DIR/cert.pem"
  openssl pkcs12 -export -legacy \
    -inkey "$SIGN_DIR/key.pem" \
    -in "$SIGN_DIR/cert.pem" \
    -out "$SIGN_DIR/cert.p12" \
    -passout pass:"$SIGN_PASS"
  rm -f "$KEYCHAIN" "$KEYCHAIN-db"
  security create-keychain -p "$SIGN_PASS" "$KEYCHAIN"
  security set-keychain-settings -lut 21600 "$KEYCHAIN"
  security unlock-keychain -p "$SIGN_PASS" "$KEYCHAIN"
  security import "$SIGN_DIR/cert.p12" -k "$KEYCHAIN" -P "$SIGN_PASS" \
    -T /usr/bin/codesign -T /usr/bin/security
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
    -k "$SIGN_PASS" "$KEYCHAIN"
  rm -f "$SIGN_DIR/key.pem" "$SIGN_DIR/cert.pem" "$SIGN_DIR/cert.p12" "$CONFIG"
fi
security unlock-keychain -p "$SIGN_PASS" "$KEYCHAIN"
codesign --force --deep --sign "$SIGN_NAME" --keychain "$KEYCHAIN" "$ROOT/dist/ChickEN.app"

echo "self-test"
rm -f /tmp/kokoro-app-self-test.txt
"$ROOT/dist/ChickEN.app/Contents/MacOS/ChickEN" --self-test
cat /tmp/kokoro-app-self-test.txt

if [[ "${SKIP_DMG:-0}" == 1 ]]; then
  echo "built $ROOT/dist/ChickEN.app"
  exit 0
fi
STAGE="$(mktemp -d)"
cp -R "$ROOT/dist/ChickEN.app" "$STAGE/ChickEN.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname ChickEN -srcfolder "$STAGE" -ov -format UDZO "$ROOT/ChickEN.dmg"
rm -rf "$STAGE"
ls -lh "$ROOT/ChickEN.dmg"
echo "built $ROOT/ChickEN.dmg"
