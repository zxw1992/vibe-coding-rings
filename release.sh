#!/usr/bin/env bash
# Usage: ./release.sh 1.0.3 "新功能描述"
set -e

VERSION="${1:?Usage: ./release.sh <version> <release-notes>}"
NOTES="${2:?Usage: ./release.sh <version> <release-notes>}"
DMG="dist/VibeCodingRings-${VERSION}.dmg"

echo "==> Updating version in setup.py..."
sed -i '' "s/\"CFBundleVersion\": \".*\"/\"CFBundleVersion\": \"${VERSION}\"/" setup.py
sed -i '' "s/\"CFBundleShortVersionString\": \".*\"/\"CFBundleShortVersionString\": \"${VERSION}\"/" setup.py

echo "==> Cleaning previous build..."
rm -rf build dist

echo "==> Building .app..."
python setup.py py2app 2>&1 | grep -E "(error|Error|Done|warning:.*recipe)" || true

echo "==> Packaging .dmg..."
create-dmg \
  --volname "Vibe Coding Rings" \
  --window-size 560 340 \
  --icon-size 128 \
  --icon "Vibe Coding Rings.app" 140 150 \
  --app-drop-link 420 150 \
  --hide-extension "Vibe Coding Rings.app" \
  "${DMG}" \
  "dist/Vibe Coding Rings.app"

echo "==> Committing & tagging v${VERSION}..."
git add setup.py
git commit -m "chore: bump version to v${VERSION}" || echo "(nothing to commit)"
git tag "v${VERSION}"
git push && git push origin "v${VERSION}"

echo "==> Creating GitHub Release..."
gh release create "v${VERSION}" \
  --repo zxw1992/vibe-coding-rings \
  --title "v${VERSION}" \
  --notes "${NOTES}"

echo "==> Uploading DMG..."
gh release upload "v${VERSION}" "${DMG}" \
  --repo zxw1992/vibe-coding-rings \
  --clobber

echo ""
echo "Done! https://github.com/zxw1992/vibe-coding-rings/releases/tag/v${VERSION}"
