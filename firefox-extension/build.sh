#!/bin/bash
# Packages this folder into ytdlp-gui.xpi — a plain zip with a .xpi
# extension, which is what Firefox's "Install Add-on From File" expects
# for a permanent (non-temporary) install. Symlinked files (background.js,
# icons — shared with extension/) are dereferenced into real files in the
# archive, since Firefox's install flow doesn't resolve symlinks.
set -e

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

OUT="$SCRIPT_DIR/ytdlp-gui.xpi"
rm -f "$OUT"

cd "$SCRIPT_DIR"
zip -X -r "$OUT" \
  manifest.json background.js \
  icon16.png icon48.png icon128.png \
  icon16-disabled.png icon48-disabled.png icon128-disabled.png

echo "Built: $OUT"
echo "In Firefox: about:addons -> gear icon -> Install Add-on From File -> select this .xpi"
