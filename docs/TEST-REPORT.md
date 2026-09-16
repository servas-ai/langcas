# LANGKAS · Testbericht

**Datum: 16. September 2026 · Version 0.1.0**

## Tatsächlich ausgeführt

| Prüfung | Ergebnis | Umfang / Grenze |
|---|---|---|
| Backend-Suite | **95 bestanden, 0 fehlgeschlagen, 0 übersprungen** | Python 3.13.5, Linux, 89,48 Sekunden; reale lokale HTTP-Verbindungen, SQLite und gestartete OS-Prozesse. |
| Browser-Suite | **2 Testfälle bestanden** | Chromium auf Linux, 24,73 Sekunden: ein Kernablauf mit 26 Prüfpunkten und ein separater Zwei-Tab-Test. |
| JavaScript | **0 unbehandelte Fehler / 0 Console-Errors** | In den durchlaufenen Browserabläufen. Keine Garantie für alle möglichen Zustände. |
| Separater Serverstart | **Bestanden** | `python3 -m langcas serve --port 0` als eigener Prozess, echte HTTP-Health-Abfrage, authentifizierter Bootstrap, leerer produktiver Startzustand, SIGTERM mit Exit-Code 0. |
| Syntax / Build | **Bestanden** | Python-Compile, Node-Syntaxprüfung des kompilierten Inline-Skripts und Bridge-Skripts, Bash-Syntax für Start-/Publish-Skript, reproduzierbarer Frontend-Build. |
| Visuelle Kontrolle | **Desktop, Laufdetails und mobile Startansicht kontrolliert** | Tatsächliche Browser-Screenshots. Mobile 390 × 844; Desktop 1440 × 960. |

## Browser-Testtransport: wichtige Einschränkung

Die Testumgebung blockierte native Chromium-Navigation mit `ERR_BLOCKED_BY_ADMINISTRATOR`. Der Download zusätzlicher Playwright-Browser, darunter WebKit, scheiterte an DNS-Auflösung (`EAI_AGAIN`). Deshalb wurde für die ausgeführten Browser-Tests **ein expliziter Testtransport** verwendet:

Die echte gebaute HTML wird in Chromium geladen. Klicks, Texteingaben, DOM, Layout, Navigation, Uploads und UI-Code laufen im Browser. `fetch` wird ausschließlich im Test über eine Python-Brücke an den **tatsächlichen lokalen Backend-HTTP-Server** weitergeleitet. Der Test-EventSource liest echte persistente Events über den JSON-Polling-Endpunkt. Antworten und CLI-Prozesse werden nicht durch erfundene KI-Antworten ersetzt.

Das ist ein Integrations-/Browserablauftest, **kein vollständiger nativer Browser-Netzwerktest**. Browser-eigene SameSite-/Cookie-/CORS-Verarbeitung und natives EventSource wurden dadurch nicht Ende zu Ende geprüft. Auth-/Host-/Origin-Regeln, Cookie-Attribute und SSE-Replay wurden separat über echte HTTP-Requests im Backend getestet. Dieser Testtransport ist nicht Teil der ausgelieferten `web/index.html`.

Die Testdatei unterstützt standardmäßig native Browser-Navigation ohne Testtransport. Der enthaltene GitHub-Actions-Workflow konfiguriert native Linux-/macOS-/WebKit-Prüfungen, wurde aber noch nicht auf GitHub ausgeführt. **Kein echter Safari-/Mac-Hardwaretest bestanden.**

## 26 Browser-Prüfpunkte

Pairing-Ansicht; Backend-Login; Runner-Auswahl; Chat → echter CLI-Testprozess → Textausgabe; mehrturniger Verlauf; dauerhaftes Prozessprotokoll; Wiederöffnen der App; fehlende CLI nicht als verbunden dargestellt; Agent in SQLite speichern; Agent mit tatsächlichem CLI-Kontext testen; Projekt anlegen; Textupload speichern; Workflow-Dokument erzeugen; Workflow menschlich freigeben; laufenden Prozess abbrechen; Theme speichern; zwölf relevante Einstellungen öffnen; Backend-Health aus UI prüfen; JSON-Workspace-Import nach Bestätigung; acht Hauptansichten öffnen; Command-K; Command-Shift-O; mobile Startansicht ohne Overflow; mobiler Drawer und Runner-Karten; mobile Laufliste; Fehlerfreiheit des durchlaufenen JavaScripts.

Der zusätzliche Zwei-Tab-Test prüft die Zusammenführung unterschiedlicher Änderungen und einen echten Konflikt bei gleichzeitiger Änderung desselben Feldes. Der erste Stand bleibt auf dem Server erhalten; der zweite Tab zeigt einen Speicherkonflikt und behält seine lokale Änderung.

## Wichtige Backend-Prüfungen

Authentifizierung, Logout und Session-Attribute; Login-Ratenlimit; Host-/Origin-Prüfung; nicht ausgelieferte private Pfade; ungültiges JSON; atomare State-Validierung; Revisionskonflikte; Sammlung-CRUD; Unicode; echte CLI-Prozesse; SSE und Event-Replay; Verlauf und Folgefragen; Agent-/Projekt-/Skill-/Workspace-Kontext; Dateikontext auch in Folgefragen; Upload/Download; explizite CLI-Fehler und fehlende Programme; Zeitlimit, Abbruch und Prozessgruppe; nicht als Shell ausgeführte Prompts; begrenzte Ausgabe; Idempotenz und aktiver Chat-Lock; Worker-Limit; Workflow-Bedingungen und Freigaben; API-Streaming; Neustart-Persistenz; Datenbank-Recovery ohne automatische erneute Ausführung; CLI-`ask`; Provider-Parser; sensible Logmuster; lokale Pfad- und Konfigurationsprüfung; Sperre gegen zweiten Server auf demselben Datenordner.

## Was die Test-CLI bedeutet

Die Prozess-Fixture in `tests/fixtures/cli_fixture.py` ist **kein Sprachmodell**. Sie führt tatsächlich ein separates Programm aus und erzeugt deterministische Text-/JSONL-Ausgaben, Fehler, Wartezeiten und Kindprozesse. Damit lassen sich Ausführung und Fehlerbehandlung kostenfrei prüfen. Hersteller-Eventformate werden zusätzlich separat getestet.

**Nicht ausgeführt:** echte Claude-, Gemini-, Codex-, Orca-, Grok- oder Antigravity-Modellaufrufe, Provider-Logins, echte Schreibzugriffe eines Herstelleragenten, produktive Kundendaten, öffentliche Deployments oder Cloud-Billing. Beim sauberen Produktstart wurden in dieser Umgebung keine der drei Hersteller-CLIs erkannt. Es wurde deshalb keine echte Provider-Verbindung behauptet.

## Während der Arbeit behoben

HTTP-Verbindungsabbrüche nach Fehlerantworten; nicht konsumierter Logout-Body; falscher Runner nach lokalem Workflow; wiederholter Dateikontext; falsche Annahme über das Import-Antwortformat; sichere Behandlung von Tab-Konflikten; zweite Serverinstanz durfte zuvor Recovery auf den laufenden Datenbestand anwenden; irreführende lokale Demo-/Speicherhinweise in Live-Einstellungen.

Ein Zwischen-Screenshot erwischte die mobile Sidebar während ihrer Übergangsanimation. Der abschließende Screenshot wartet auf das Ende der Animation und prüft zusätzlich die tatsächlichen Begrenzungen von Sidebar und Composer, nicht nur die Dokumentbreite.

## Repository-Status

Das Paket enthält den vollständigen Quellstand und reproduzierbare Tests. **`servas-ai/langcas` wurde remote nicht erstellt oder gepusht.** Zweimaliger Mac-Connector-Zugriff scheiterte; die vorhandenen GitHub-Aktionen boten keine Repository-Erstellung. `publish.command` wurde auf Bash-Syntax geprüft, aber nicht mit einem authentifizierten GitHub-Push ausgeführt.

## Belege

`evidence/backend-junit.xml`, `evidence/ui-junit.xml`, `evidence/browser-results.json`, `evidence/startup-smoke.json` sowie die Browser-Screenshots. Die Rohdaten beschreiben die ausgeführten Tests, nicht eine allgemeine Zusicherung von Fehlerfreiheit oder Produktionssicherheit.
