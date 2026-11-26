#!/usr/bin/env bash
# Download the SEC quarterly Form 3/4/5 data sets (2014 onward) into data/raw/form345.
# Needs EDGAR_USER_AGENT in .env ("AppName contact@email"), per the SEC fair-access policy.
set -euo pipefail
cd "$(dirname "$0")/.."
UA=$(grep -E '^EDGAR_USER_AGENT=' .env | cut -d= -f2- | tr -d '"')
mkdir -p data/raw/form345
cd data/raw/form345
curl -s -L -A "$UA" "https://www.sec.gov/dera/data/form-345" \
  | grep -o -E 'href="[^"]*form345\.zip"' | sed 's/href="//;s/"$//' | sort -u \
  | grep -E '/(201[4-9]|20[2-9][0-9])q[1-4]_' > _links.txt
while read -r p; do
  f=$(basename "$p")
  [ -s "$f" ] || curl -s -f -A "$UA" -o "$f" "https://www.sec.gov$p"
  sleep 0.3   # far below the 10 requests per second ceiling
done < _links.txt
ls *_form345.zip | wc -l
