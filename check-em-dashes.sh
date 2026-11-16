#!/bin/bash
# GTA Router - fail if an em dash has crept back into the app's text.
#
# WHY: no em dashes anywhere a user reads is a standing rule of this project
# (see docs/design-rules.md), and a first cleanup only fixed one screen.
# The trap is that a plain grep for the character misses the HTML entity
# spellings, which is exactly how 7 of them survived the first cleanup.
#
# Usage:  bash check-em-dashes.sh        (exit 0 = clean, 1 = found some)

cd "$(dirname "$0")"

# every way an em dash can be written into HTML
PATTERNS='—|&mdash;|&#8212;|&#[xX]2014;|&#151;'

# En dashes are fine - the rule is about em dashes only, and "Youth 13-19"
# legitimately uses one.

hits=$(grep -nE "$PATTERNS" web/index.html web/app.js web/core.js 2>/dev/null)

if [ -z "$hits" ]; then
  echo "OK: no em dashes in web/index.html, app.js or core.js"
  exit 0
fi

echo "FOUND em dashes in the app's text:"
echo ""
echo "$hits"
echo ""
echo "Replace each one with:"
echo "  a colon      for labels      Start: click the map"
echo "  a comma      for fare lines  UP Express, youth"
echo "  a full stop  for errors      That took too long. Try again."
echo ""
echo "Note this only checks the source. Strings built in JavaScript are"
echo "worth re-checking in the running app with the menus open."
exit 1
