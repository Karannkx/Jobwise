#!/usr/bin/env bash
# Build a Debian package from the PyInstaller output.
# Usage: packaging/linux/build_deb.sh            (run from anywhere, after PyInstaller finished)
# Output: dist/Jobwise-Linux-amd64.deb
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BUNDLE="dist/Jobwise"
[ -x "$BUNDLE/Jobwise" ] || { echo "PyInstaller bundle not found at $BUNDLE - run pyinstaller first" >&2; exit 1; }

VERSION="$(python3 -c 'import resume_matcher; print(resume_matcher.__version__)')"
ARCH="$(dpkg --print-architecture)"
PKG="jobwise"
STAGE="build/deb/${PKG}_${VERSION}_${ARCH}"
OUT="dist/Jobwise-Linux-${ARCH}.deb"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/jobwise" "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" "$STAGE/usr/share/pixmaps" \
         "$STAGE/usr/share/icons/hicolor/512x512/apps" "$STAGE/usr/share/doc/${PKG}"

cp -a "$BUNDLE/." "$STAGE/opt/jobwise/"
install -m 0644 assets/icon.png "$STAGE/usr/share/pixmaps/jobwise.png"
install -m 0644 assets/icon.png "$STAGE/usr/share/icons/hicolor/512x512/apps/jobwise.png"
install -m 0644 packaging/linux/jobwise.desktop "$STAGE/usr/share/applications/jobwise.desktop"
install -m 0644 README.md "$STAGE/usr/share/doc/${PKG}/README.md"
printf 'Jobwise %s\nCopyright (c) Karan Kumar (karannkx). All rights reserved.\n' "$VERSION" \
    > "$STAGE/usr/share/doc/${PKG}/copyright"

# launcher on PATH
cat > "$STAGE/usr/bin/jobwise" <<'EOF'
#!/bin/sh
exec /opt/jobwise/Jobwise "$@"
EOF
chmod 0755 "$STAGE/usr/bin/jobwise"

INSTALLED_KB="$(du -sk "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Karan Kumar (karannkx) <kkumar04600@gmail.com>
Installed-Size: ${INSTALLED_KB}
Depends: libc6 (>= 2.31), libgl1, libegl1, libfontconfig1, libfreetype6, libdbus-1-3, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xinerama0, libxcb-xkb1
Description: AI-powered job matching and resume analysis system
 Job search and matching desktop application that parses resumes,
 ranks candidates and analyses skill gaps using the Google Gemini API.
 Results are decision support only. Candidate text is sent to Google
 Gemini for analysis; data is otherwise stored locally.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi
exit 0
EOF
cp "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# normalise permissions
find "$STAGE" -type d -exec chmod 0755 {} +

mkdir -p dist
dpkg-deb --root-owner-group --build "$STAGE" "$OUT" >/dev/null
echo "Built $OUT"
dpkg-deb --info "$OUT" | sed -n '1,12p'
