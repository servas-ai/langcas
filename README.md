# LANGKAS
### KI, oba koa Kas.

Lokaler KI-Arbeitsplatz: **LANGKAS-Oberfläche → Python-Backend → deine CLI → persistente Chats und Laufprotokolle in SQLite.** Repository-Ziel: `servas-ai/langcas`; sichtbare Marke: `LANGKAS`.

---

## Sofort starten

Python **3.11+**, macOS oder Linux. Zum normalen Start sind **keine pip-Pakete, kein Node, kein Docker und keine externe Datenbankinstallation** nötig.

```sh
cd langcas
bash start.command
```

Das Skript startet das Backend standardmäßig auf Port **`8877`** (konfigurierbar über `LANGKAS_PORT`), zeigt den lokalen Zugangsschlüssel an und öffnet den Standardbrowser auf `http://127.0.0.1:8877`. Schlüssel im Login einfügen. Die HTML-Datei nicht per Doppelklick als `file://` starten: Der Live-Modus benötigt das Backend. Mit `Ctrl+C` beenden.

Alternativ im Terminal:

```sh
python3 -m langcas token
python3 -m langcas serve --port 8877 --open
```

**Eine passende CLI muss auf demselben Rechner installiert und dort bereits angemeldet sein.** `python3 -m langcas doctor` prüft ausführbare Programme, ruft kein kostenpflichtiges Modell auf und prüft die lokale PATH-Verfügbarkeit.

---

## Was wirklich angeschlossen ist

| Bereich | Implementierung |
|---|---|
| **Chat** | Echte CLI-Prozesse, Live-Text-Streaming, Verlauf, Dateien als Textkontext, Modell- & Runner-Auswahl. |
| **Persistenz** | SQLite/WAL: Chats, Agenten, Projekte, Prompts, Skills, Textdokumente, Einstellungen, Läufe und geordnete Events. |
| **Runner-Matrix** | Native Adapter für **Antigravity (AGY)**, **OpenAI Codex**, **Grok**, **OpenCode**, **Claude Code** und **Gemini** sowie generische Adapter. |
| **Ablaufkontrolle** | Zwei Worker maximal, Warteschlange, konfigurierbares Zeitlimit, Abbrechen samt Prozessgruppe, Exit-Code und stderr-Protokoll. |
| **Agenten** | Gespeicherte Anweisungen, Wissensdateien, Projektkontext, Skills, Versionen und echter CLI-Test. |
| **Workflows** | Ketten aus Start, KI, Texttransformation, Bedingung, menschlicher Freigabe und gespeichertem Dokument. |
| **Wiederanlauf** | Nachrichten und Events bleiben erhalten; unterbrochene Läufe werden als unterbrochen markiert, nicht still wiederholt. |
| **API** | Bearer-geschützte REST-API und ein OpenAI-kompatibler `/v1/chat/completions`-Endpunkt mit Server-Sent Events (SSE). |
| **Skill** | Integrierter `langcas`-Skill unter `skills/langcas/SKILL.md` für Antigravity- und Claude-Flotten. |

---

## Verbundene CLI-Runner

**Auto** wählt den ersten aktivierten, installierten Runner gemäß lokaler Priorität:

1. **Antigravity (`agy`):** Google DeepMind Antigravity CLI. Höchste Priorität (Prio 5). Echter `stream-json`-Adapter mit Token-Usage und Live-Streaming in die UI.
2. **OpenAI Codex (`codex`):** OpenAI Codex CLI (Prio 10). Läuft sandboxed mit `codex exec --json`.
3. **Grok (`grok`):** Grok Build CLI (Prio 15). Nutzt das Anthropic-kompatible `streaming-messages-json`-Protokoll.
4. **OpenCode (`opencode`):** OpenCode CLI (Prio 20). Direkte strukturierte JSON-Ausgabe.
5. **Claude Code (`claude`):** Claude Code CLI (Prio 25). Startet mit `--bare -p` und explizitem Werkzeugsatz.
6. **Gemini CLI (`gemini`):** Gemini Headless (Prio 30). Konservativ als potenziell schreibend eingestuft (erfordert Freigabe).

Status der Runner prüfen:

```sh
python3 -m langcas doctor
```

Runner aktivieren oder deaktivieren:

```sh
python3 -m langcas enable codex
python3 -m langcas enable gemini --disable
```

---

## Eigene Adapter & Workspaces

Kein hart kodiertes Raten von CLI-Flags. Registriere einen **nichtinteraktiven** lokalen Befehl oder einen kleinen Wrapper, der den Prompt von stdin liest und Text bzw. JSONL auf stdout ausgibt:

```sh
python3 -m langcas add-runner mein-cli \
  --name 'Mein Assistent' \
  --exec /absoluter/pfad/mein-wrapper \
  --input text --output text
```

Ein Projektverzeichnis bewusst lokal freigeben:

```sh
python3 -m langcas add-workspace mein-projekt /absoluter/pfad/zum/projekt
```

Danach im Cockpit unter Runner/Workspace auswählen. Details: [Adapter-Dokumentation](docs/ADAPTERS.md).

---

## Skill für Agenten & Flotten

Im Ordner [`skills/langcas/SKILL.md`](skills/langcas/SKILL.md) ist ein vollständiger Skill für Agentensysteme (Google Antigravity, Claude Code, etc.) enthalten. Er beschreibt:
- Erkennung des LANGKAS-Servers und Port-Fallback
- Automatisches Abrufen des Bearer-Tokens
- Aufruf von Prompts über den `langcas ask`-CLI-Wrapper oder `/v1/chat/completions`
- Auslesen von Laufprotokollen und Events aus SQLite

---

## API & Terminal

Anfragen direkt über das Terminal an den laufenden Server senden:

```sh
# Automatische Runner-Auswahl (z. B. agy)
python3 -m langcas ask 'Servas, erkläre diesen Code' --port 8877

# Gezielt an einen bestimmten Runner
python3 -m langcas ask 'Servas' --runner agy --port 8877
python3 -m langcas ask 'Servas' --runner codex --port 8877
python3 -m langcas ask 'Servas' --runner grok --port 8877
python3 -m langcas ask 'Servas' --runner opencode --port 8877
```

Streaming über die OpenAI-kompatible HTTP-API:

```sh
curl -N http://127.0.0.1:8877/v1/chat/completions \
  -H "Authorization: Bearer $(python3 -m langcas token)" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agy",
    "messages": [{"role": "user", "content": "Servas LANGKAS!"}],
    "stream": true
  }'
```

Weitere Details: [API-Spezifikation](docs/API.md) und [Sicherheitskonzept](docs/SECURITY.md).

---

## Speicherort & Persistenz

- **macOS:** `~/Library/Application Support/LANGKAS/`
- **Linux:** `~/.local/share/langcas/` bzw. `$XDG_DATA_HOME`
- **Eigener Pfad:** `LANGKAS_DATA_DIR=/absoluter/pfad`

Dort liegen:
- `langcas.sqlite3` (Chats, Agenten, Prompts, Workflows, Audit, Runs)
- `runners.json` (lokal konfigurierte Runner & Workspaces)
- `access-token` (gesicherter lokaler Schlüssel, `chmod 0600`)
- `workspaces/` (isoliertes Ausführungsverzeichnis für Läufe ohne festen Workspace)

---

## Veröffentlichung auf GitHub

Auf einem Rechner mit `git`, installierter GitHub CLI (`gh`) und berechtigter Anmeldung:

```sh
bash publish.command
```

Das Skript erstellt **`servas-ai/langcas` als privates Repository**, verknüpft das Remote `origin` und pusht den `main`-Branch.

---

## Tests

```sh
# Mit uv:
uv run --with pytest --with httpx pytest tests/test_backend.py -v

# Oder klassisch mit venv:
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/test_backend.py -q
```

Alle 97 Backend-Tests (inklusive Decodern für AGY, Codex, Grok, OpenCode, Claude und Gemini) sind vollständig abgedeckt und bestanden.
