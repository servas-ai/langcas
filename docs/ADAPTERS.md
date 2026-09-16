# CLI-Adapter

Der Runtime-Vertrag ist absichtlich klein: ein vertrauenswürdiges ausführbares Programm, getrennte argv-Argumente, stdin und stdout/stderr. `shell=False`; es gibt keinen HTTP-Endpunkt zum Einstellen von Befehlen. Konfigurationsänderungen erfolgen lokal in `runners.json` oder über `python3 -m langcas add-runner`.

## Generischer Adapter

```json
{
  "id": "mein-cli",
  "name": "Mein Assistent",
  "adapter": "generic",
  "command": "/absoluter/pfad/mein-wrapper",
  "args": [],
  "input": "json",
  "output": "jsonl",
  "permission": "read-only",
  "enabled": true,
  "priority": 10,
  "timeout": 180
}
```

`input=text` liefert den Kontext als `[SYSTEM]`, `[USER]`, `[ASSISTANT]`-Abschnitte an stdin. `input=json` liefert ein JSON-Objekt mit `messages`, `prompt` und `model`. `args` ist ein Array einzelner Argumente, keine Shell-Zeile. Die Platzhalter `{prompt}` und `{model}` werden innerhalb eines Arguments ersetzt. Bei `{prompt}` wird kein zusätzlicher stdin-Prompt gesendet; für große oder sensible Inhalte ist stdin vorzuziehen.

`output=text` übernimmt stdout als Text. `output=jsonl` erwartet eine JSON-Nachricht je Zeile:

```json
{"type":"delta","text":"Servas. "}
{"type":"delta","text":"Hier ist das Ergebnis."}
{"type":"result","text":"Servas. Hier ist das Ergebnis."}
```

Wenn Deltas vorhanden waren, wiederholt das abschließende `result` den Text nicht. Ein `{"type":"error","message":"..."}`-Event ist ein Fehlschlag. Exit-Code ungleich null und leere Antwort sind ebenfalls Fehlschläge. stderr wird getrennt begrenzt protokolliert. `usage` wird nur übernommen, wenn die CLI es tatsächlich liefert; LANGKAS berechnet keine erfundenen Kosten oder Tokenzahlen.

## Lokal testen, ohne KI-Kosten

Dieser Befehl registriert **explizit einen Testprozess, kein Sprachmodell**:

```sh
python3 -m langcas add-runner testprozess \
  --name 'Testprozess – keine KI' \
  --exec "$(command -v python3)" \
  --arg="$(pwd)/tests/fixtures/cli_fixture.py" \
  --input json --output jsonl
```

In der UI Runner neu erkennen und Testprozess auswählen. Er antwortet mit einem gekennzeichneten Echo. Anschließend wieder deaktivieren:

```sh
python3 -m langcas enable testprozess --disable
```

## Herstelleradapter

Claude-Code-, Gemini- und Codex-Ausgaben werden strukturiert normalisiert. Es gibt Tests für ihre Eventformate; in der Build-Umgebung wurden **keine echten Provider-CLI-/Modell-Anfragen** ausgeführt. Bei abweichenden CLI-Versionen erscheint der reale Fehler. Ein neues Flag wird nicht still ignoriert und Berechtigungen werden nicht heimlich gelockert.

Claude wird mit `--bare` und einer expliziten Werkzeugliste gestartet. Gemini wird konservativ als schreibfähig behandelt und braucht vor jeder Ausführung eine Freigabe. Codex fordert einen expliziten CLI-Sandboxmodus an und ist anfangs deaktiviert. Eigene Shell-Aliasse, native GUI-/Browser-Harnesses, vollständige interaktive Terminalprogramme und proprietäre Orca-Steuerprotokolle sind nicht pauschal eingebaut. Dafür muss ein zum jeweiligen Programm passender nichtinteraktiver Wrapper registriert werden.

Anmeldedaten werden von der jeweiligen CLI aus deren normalem Benutzerprofil genutzt. Nicht im Repository oder Browser hinterlegen. CLI-Provider können Prompts und Dateikontext an Cloud-Dienste senden.

## Grenzen

Zwei Worker maximal, Queue 64, konfigurierbares Zeitlimit 1–3600 Sekunden. CLI-Wire-Ausgabe maximal 4 MB, Antwort maximal zwei Millionen Zeichen. Chatkontext maximal 250.000 Zeichen, Prompt maximal 50.000 Zeichen. Ein Verlauf enthält nicht die native Provider-Session; der Kontext wird bei jeder Folgefrage erneut übertragen. Das kann Provider-Verbrauch verursachen.

Der generische `read-only`-Modus ist eine Vertrauensangabe, **keine erzwungene Betriebssystem-Sandbox**. Ein bösartiger Wrapper könnte außerhalb seines Arbeitsverzeichnisses lesen oder schreiben. Schreibfähige Adapter müssen mit `permission=workspace-write` registriert werden und lösen eine explizite UI-Freigabe aus. Keine privaten/relevanten Produktionsverzeichnisse ohne bewusste Prüfung freigeben.
