# LANGKAS API v0.1

Standardbasis `http://127.0.0.1:8765`. CLI-Zugriff über `Authorization: Bearer <lokaler Schlüssel>`. Browserzugriff über die mit `POST /api/auth/login` erhaltene HttpOnly-/SameSite-Strict-Sitzung. Login-Inhalt: `{"token":"..."}`. Logout: `POST /api/auth/logout` mit `{}`. Die Anmeldung erlaubt Zugriff auf lokale CLI-Ausführung und private Chats; Schlüssel geheim halten.

## Chats und Läufe

```http
POST /api/runs
Content-Type: application/json
Idempotency-Key: request_123
```

```json
{
  "prompt": "Fasse dieses Dokument zusammen.",
  "provider": "auto",
  "model": "",
  "chat_id": null,
  "agent": null,
  "project": null,
  "files": [],
  "workspace": null
}
```

HTTP 202 enthält unter anderem `id`, `chat_id`, `message_id`, `provider`, `status`, `output`. Leere `chat_id` erzeugt einen Chat. Folgefragen verwenden die vorhandene Chat-ID. Dateireferenzen zeigen auf gespeicherte Textdateien; Arbeitsverzeichnisse auf lokal registrierte IDs, niemals frei eingegebene Pfade. Derselbe Idempotenzschlüssel mit gleichem Payload gibt denselben Lauf zurück; geänderter Payload führt zu 409. Pro Chat ist ein aktiver Lauf erlaubt.

`GET /api/runs` listet die letzten 50 Läufe. `GET /api/runs/{id}` liefert Zustand und Ausgabe. `POST /api/runs/{id}/cancel` mit `{}` bricht ab. Freigabe: `POST /api/runs/{id}/approve` mit `{"approve":true}` oder `false`. Es gibt keine implizite Freigabe bei erneutem Laden.

### Dauerhafte Events

`GET /api/runs/{id}/events` liefert Server-Sent Events mit numerischer `id`, `event` und JSON-`data`. Typen sind unter anderem `status`, `delta`, `process`, `tool`, `log`, `stderr`, `step`, `artifact`, `done`. Ein delta enthält `{"text":"..."}`. Clients müssen Event-IDs deduplizieren. Wiederaufnahme über `Last-Event-ID` oder `?since=N`; Events sind in SQLite gespeichert.

Für Polling-Clients: `GET /api/runs/{id}/events?format=json&since=N` liefert `{events,run}`. Der Browser verwendet im normalen Produktmodus natives EventSource; der Polling-Transport in `tests/browser_transport.js` ist nur für die gesperrte Testumgebung bestimmt und nicht Teil der ausgelieferten HTML.

Status: `queued`, `running`, `awaiting_approval`, `succeeded`, `failed`, `cancelled`, `interrupted`. Kein automatischer Retry nach Fehler oder Neustart.

## Workspace

`GET /api/bootstrap` liefert State, Revision, Runner, registrierte Workspaces und implementierte Features. `GET /api/state` liefert `{revision,state}`. `PUT /api/state` erfordert den aktuellen Revisionswert und den vollständigen State. Konflikt: 409. Strukturfehler: 422. Das Backend schützt Nachrichten aktiver Läufe vor Überschreiben durch den Browser.

`GET /api/export` sichert den Workspace als JSON; `POST /api/import` nimmt `{revision,state}` an. Events, Auth-Schlüssel und lokale Runner-Konfiguration sind nicht Teil dieses Exports. Für vollständige Sicherung siehe README.

Sammlungen: `GET /api/collections/{collection}` und `GET /api/collections/{collection}/{id}`. POST/PATCH nutzen `{revision,data}`; DELETE `{revision}`. IDs sind keine Dateipfade. Änderungen werden als vollständiger Workspace validiert.

Textdatei anlegen: `POST /api/files` mit `{"name":"notes.md","text":"..."}`. HTTP 201 enthält `file.id` und SHA-256. Download: `GET /api/files/{id}/download`. Kein PDF-/Office-Textparser und keine Bildanalyse. `GET /api/search?q=...` bietet textbasiertes Suchen in gespeicherten Inhalten, keine Vektorsuche.

`GET /api/runners`, `POST /api/config/reload`, `GET /api/audit`, `GET /api/stats`, `GET /health`. Config-Reload liest ausschließlich die lokale Datei; keine Befehle im HTTP-Payload. Änderungen der Worker-Anzahl erfordern Neustart (`restart_required=true`). `/health` enthält keine privaten Inhalte und benötigt kein Login.

## Agenten und Workflows

`POST /api/agents/{id}/run` oder `POST /api/workflows/{id}/run` mit `{"prompt":"...","provider":"auto"}`. Alternativ bei `/api/runs` `agent` oder `workflow` setzen. Workflows führen erlaubte Knoten der gespeicherten Vorlage aus. Nicht unterstützte HTTP-Actions: 501. Menschliche Workflow-Freigaben laufen nach fünf Minuten ab. Eine wartende Workflow-Freigabe belegt einen Worker; anfängliche Ausführungsfreigaben starten noch keinen Prozess.

## Textkompatibler Chat-Endpunkt

```sh
TOKEN="$(python3 -m langcas token)"
curl --no-buffer http://127.0.0.1:8765/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"model":"claude","messages":[{"role":"user","content":"Servas!"}],"stream":true}'
```

`model` ist eine Runner-ID oder `runner/modell-id`, z. B. `claude` bzw. `auto`. Antwortformat: `choices[0].message.content`, bei Streaming `choices[0].delta.content` und abschließend `[DONE]`. Fehler im bereits geöffneten Stream erscheinen als `error`-Event, nicht als Erfolgstext.

Unterstützt werden nur `model`, `messages`, `stream`, `user`; Rollen system/developer/user/assistant mit Textinhalt. Keine Bilder, Tools, JSON-Schema-Garantie oder Sampling-Parameter. Keine vollständige API-Emulation. Schreibfähige Runner erhalten hier 403, da sie die explizite Freigabe über `/api/runs` benötigen. `/v1/models` meldet Runner und deren Verfügbarkeit statt einer erfundenen Liste von Provider-Modellen.

## Zugriff und typische Fehler

401 nicht angemeldet; 403 falscher Origin/Host bzw. fehlende Ausführungsfreigabe; 404 unbekannte Referenz; 409 Revisions-/Chat-/Idempotenzkonflikt; 413 zu groß; 415 falscher Content-Type; 422 ungültiger Auftrag; 428 fehlende Revision; 429 Loginlimit/volle Queue; 501 nicht angeschlossene Workflow-Aktion; 502 Providerfehler bei nichtstreamender Kompatibilitäts-API; 503 kein verfügbarer Runner. Ein bereits angenommener Lauf kann später mit `failed` enden: Deshalb immer Laufstatus prüfen.
