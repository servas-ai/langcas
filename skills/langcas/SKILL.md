---
name: langcas
description: Lokaler KI-Arbeitsplatz und CLI-Cockpit (LANGKAS). Steuere und überwache das lokale Backend (Port 8877/8765), führe Chats über verbundene lokale CLIs (Antigravity agy, OpenAI Codex, Grok, OpenCode, Claude Code) aus, inspiziere SQLite-Läufe und manage Runner/Workspaces.
---

# 🚀 LANGKAS · Lokaler KI-Arbeitsplatz & CLI-Cockpit

LANGKAS verbindet die browserbasierte Oberfläche über ein leichtgewichtiges Python-Backend direkt mit echten, lokalen CLI-Assistenten. Keine erfundenen Antworten, kein unnötiger Cloud-Zwischenlayer: Echte Terminal-Prozesse, gestreamter Text und persistente Chat-/Laufprotokolle in SQLite (WAL).

---

## 🧭 Schnelle Übersicht

- **Backend-Port:** Standardmäßig `8877` (anpassbar via `LANGKAS_PORT=...`)
- **Web-Cockpit:** [http://127.0.0.1:8877](http://127.0.0.1:8877)
- **Persistenz:** `~/Library/Application Support/LANGKAS/langcas.sqlite3`
- **Konfiguration:** `~/Library/Application Support/LANGKAS/runners.json`
- **Zugriffsschlüssel:** `~/Library/Application Support/LANGKAS/access-token`

---

## ⚙️ Unterstützte lokale CLI-Runner

| Runner | Befehl | Protokoll | Priorität | Standard-Modus |
|---|---|---|---|---|
| **Antigravity (AGY)** | `agy` | `stream-json` (NDJSON live) | **5 (Auto-Wahl #1)** | `read-only` |
| **OpenAI Codex** | `codex` | `codex exec --json` | **10** | `read-only` |
| **Grok Build** | `grok` | `streaming-messages-json` | **15** | `read-only` |
| **OpenCode** | `opencode` | `opencode run --format json` | **20** | `read-only` |
| **Claude Code** | `claude` | `stream-json` | **25** | `read-only` |
| **Gemini CLI** | `gemini` | `stream-json` | **30** | `workspace-write` |

---

## 🛠️ Wichtige Befehle & Aktionen

### 1. Status prüfen (Doctor)
Prüft die installierten CLIs und Konfiguration ohne API-Kosten:
```bash
python3 -m langcas doctor
```

### 2. Zugriffsschlüssel abrufen (Token)
Gibt den aktuellen Bearer-Token für Web-Login und REST-API aus:
```bash
python3 -m langcas token
```

### 3. Server starten
```bash
# Im Hintergrund oder Terminal starten:
python3 -m langcas serve --port 8877 --open

# Oder über das Start-Skript:
bash start.command
```

### 4. Direkte Abfrage über das Backend (CLI Ask)
Führt Anfragen direkt über den LANGKAS-Server und die gewünschte CLI aus:
```bash
# Über Auto-Runner (wählt den Runner mit höchster Prio, z.B. AGY):
python3 -m langcas ask "Erkläre kurz das Konzept von LANGKAS" --port 8877

# Gezielt über Antigravity (AGY):
python3 -m langcas ask "Servas vom AGY" --runner agy --port 8877

# Gezielt über Codex:
python3 -m langcas ask "Code-Optimierung prüfen" --runner codex --port 8877

# Gezielt über Grok:
python3 -m langcas ask "Architektur-Tribunal" --runner grok --port 8877

# Gezielt über OpenCode:
python3 -m langcas ask "Code-Analyse" --runner opencode --port 8877
```

### 5. Runner aktivieren / deaktivieren
```bash
python3 -m langcas enable codex
python3 -m langcas enable gemini --disable
```

### 6. Workspace hinzufügen
Gibt ein lokales Projektverzeichnis explizit für CLI-Läufe frei:
```bash
python3 -m langcas add-workspace mein-projekt /absoluter/pfad/zum/projekt
```

---

## 🔌 API & Integration

LANGKAS stellt eine OpenAI-kompatible Schnittstelle unter `/v1/chat/completions` bereit:

```bash
curl -N http://127.0.0.1:8877/v1/chat/completions \
  -H "Authorization: Bearer $(python3 -m langcas token)" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agy",
    "messages": [{"role": "user", "content": "Servas!"}],
    "stream": true
  }'
```

---

## 🔒 Sicherheit & Berechtigungen

- **Single-User / Localhost-Only:** Keine offenen externen Ports, Same-Origin & Bearer-Token Guard.
- **Keine Cloud-Geheimnisse im Code:** Authentifizierung liegt bei den jeweiligen CLIs (`agy`, `codex`, `grok`, etc.).
- **Workspace-Schutz:** `workspace-write`-Runner erfordern vor destruktiven Dateiänderungen eine explizite Bestätigung in der Web-Oberfläche.
