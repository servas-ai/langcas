# Sicherheitsmodell und Grenzen

## Vertrauensgrenze

Diese Version ist ein **lokaler Einzelbenutzer-CLI-Arbeitsplatz**, kein gehärteter öffentlich erreichbarer SaaS-Dienst. Der Server bindet ausschließlich an `127.0.0.1`. Keine LAN-Freigabe, kein Reverse-Proxy-Deployment, keine fremden Benutzer ohne weitere Entwicklung. Zugang zum LANGKAS-Schlüssel bedeutet Zugang zur Ausführung der registrierten CLIs mit Rechten des lokalen Benutzers.

Der Browser kann nur registrierte Runner und Workspace-IDs auswählen. Neue Commands, Argumente oder Pfade werden lokal konfiguriert. Prozesse laufen ohne Shell-Interpolation in separaten POSIX-Prozessgruppen. Abbruch beendet die Gruppe; Zeit-, Prozess- und Ausgabelimits verhindern unbegrenzte Standardläufe. Sich absichtlich abkoppelnde Programme und Kernel-Angriffe werden damit nicht sandboxed.

Ein Arbeitsverzeichnis ist keine Zugriffsgrenze. Der generische Lesemodus ist nicht technisch erzwingbar. Nur vertrauenswürdige Wrapper starten; schreibfähige Adapter explizit als solche registrieren. Bei Änderungen an fremden Projekten sind normale Git-/Backup-Kontrollen weiterhin nötig. CLI-Tools können eigene Netzverbindungen, Plugins, Hooks und Provider-Zugriffe haben. LANGKAS behauptet nicht, alles davon plattformübergreifend zu isolieren.

## Implementierte Schutzmaßnahmen

- Lokaler zufälliger Eigentümerschlüssel, nicht in HTML/Repo; Hash statt Browser-Session-Token in SQLite, HttpOnly/SameSite-Strict-Sitzung mit Ablauf.
- Host-/Origin-/Sec-Fetch-Site-Prüfung, keine CORS-Freigabe, Login-Ratenlimit, No-Store, No-Sniff, Frame-Sperre.
- Commands nicht durch HTTP editierbar; keine Shell; Provider-Secrets nicht absichtlich an den Browser ausgegeben. LANGKAS-interne Umgebungsvariablen werden vor dem CLI-Start entfernt.
- Dateinamen werden nicht als lokale Schreibpfade verwendet. Keine privaten Konfigurationsdateien über den Webserver erreichbar.
- Atomare SQLite-Transaktionen, Revisionsprüfung, Schutz aktiver Assistant-Ausgaben, Idempotenz und eindeutige aktive Chat-Aufträge.
- Exklusive Prozesssperre pro Datenordner: ein zweiter Server kann keine laufenden Aufträge als unterbrochen markieren.
- Explizite Ausführungsfreigabe für schreibfähige Runner und getrennte inhaltliche Workflow-Freigaben.
- Keine automatische Wiederholung nach einem Absturz: angefangene Läufe werden als unterbrochen angezeigt. Bereits erfolgte Seiteneffekte werden dadurch nicht rückgängig gemacht.

## Offen / nicht zugesichert

Kein SSO, keine RBAC-/Team-Grenzen, keine Datenverschlüsselung auf Anwendungsebene, kein Secret-Vault, keine allgemeine OS-Sandbox, keine Sicherheitszertifizierung und kein vollständiges Security-Audit. Die Legacy-One-File-UI verwendet Inline-JavaScript; ihre CSP erlaubt deshalb Inline-Inhalte. Das ist nicht die Zielarchitektur für einen öffentlich gehosteten Mehrbenutzerdienst.

Private Inhalte liegen in SQLite und temporären Workspace-Dateien. CLI-Ausgaben können selbst sensible Daten enthalten. Bekannte Tokenmuster werden in Logs redigiert; das ist **kein universeller Secret-Filter**, und Antworttext kann bewusst angeforderte private Inhalte enthalten. Provider-CLIs können Cloud-Modelle nutzen und Gebühren/Abonnementlimits verbrauchen. Der Begriff „lokal“ bezieht sich auf UI, Orchestrierung und Datenspeicher, nicht automatisch auf die Modellinferenz.

Prompt-Injection durch Dokumente lässt sich nicht allein durch einen Texttrenner ausschließen. Dateiinhalte werden als Daten markiert; entscheidend bleiben CLI-Berechtigungen, vertrauenswürdige Programme und menschliche Freigabe. Zugangsschlüssel nicht in fremde Browser-Seiten kopieren. Keine Inhalte unbekannter Herkunft blind importieren.

## Betrieb

Backups: Server geordnet beenden, gesamten Datenordner kopieren. Schlüsselwechsel: Server beenden, neuen mindestens 32 Zeichen langen zufälligen Schlüssel lokal setzen; bestehende Sitzungen müssen separat widerrufen bzw. bewusst invalidiert werden. Zugangsdaten niemals commiten. Vor einem produktiven Team-/Internetbetrieb sind ein separates Auth-/Tenant-Modell, harte Prozessisolation, Secret-Verwaltung, Audit/Retention, Transportverschlüsselung, Recovery-Tests und ein eigener Sicherheitstest erforderlich.

Ein harter Betriebssystem-Abbruch wie `kill -9` kann einen bereits gestarteten CLI-Prozess verwaist zurücklassen. Nach einem solchen Abbruch Prozesse und mögliche Seiteneffekte prüfen; Recovery markiert den Datenbank-Lauf als unterbrochen, garantiert aber keinen rückwirkenden Prozessabbruch. Normales Beenden und UI-Abbruch werden separat getestet.
