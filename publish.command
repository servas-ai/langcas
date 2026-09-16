#!/bin/bash
# Creates a PRIVATE repository only. No force push, token extraction or unrelated repository writes.
set -euo pipefail
cd -- "$(dirname -- "$0")"
REPO='servas-ai/langcas'
command -v gh >/dev/null 2>&1 || { echo 'GitHub CLI (gh) fehlt. Installiere sie und melde dich mit gh auth login an.' >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo 'git fehlt.' >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo 'Keine aktive GitHub-Anmeldung. Zuerst gh auth login.' >&2; exit 1; }
if [[ ! -d .git ]]; then
  git init -b main
  git add .gitignore .gitattributes README.md NOTICE.md requirements-dev.txt start.command publish.command langcas web scripts tests docs skills .github evidence
  git -c user.name='LANGKAS Builder' -c user.email='build@langkas.local' commit -m 'Build LANGKAS local CLI cockpit with persistence and tests'
fi
ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
if [[ -n "$ORIGIN" && "$ORIGIN" != "https://github.com/$REPO.git" && "$ORIGIN" != "git@github.com:$REPO.git" && "$ORIGIN" != "https://github.com/$REPO" ]]; then
  echo "Abbruch: Dieses Verzeichnis hat bereits ein anderes origin: $ORIGIN" >&2; exit 1
fi
if gh repo view "$REPO" >/dev/null 2>&1; then
  if [[ -z "$ORIGIN" ]]; then
    echo "$REPO existiert bereits. Kein vorhandenes Repository automatisch übernommen." >&2; exit 1
  fi
  git push -u origin main
else
  if [[ -n "$ORIGIN" ]]; then
    echo 'origin existiert, aber das Ziel ist nicht lesbar. Berechtigungen prüfen; keine automatische Neuerstellung.' >&2; exit 1
  fi
  gh repo create "$REPO" --private --description 'LANGKAS – lokaler KI-Arbeitsplatz für CLI-Assistenten. KI, oba koa Kas.' --source=. --remote=origin --push
fi
gh repo view "$REPO" --json nameWithOwner,url,isPrivate
