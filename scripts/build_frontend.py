"""Build the self-contained UI from the supplied LANGKAS prototype and our bridge."""
from pathlib import Path
import json, re, subprocess
ROOT=Path(__file__).resolve().parent.parent
src=(ROOT/'web/demo.html').read_text()
line=next(x for x in src.splitlines() if x.startswith('function seed()'))
models=next(x for x in src.splitlines() if x.startswith('const Models='))
seed=json.loads(subprocess.check_output(['node','-e','const VERSION=3;'+models+'\n'+line+'\nconsole.log(JSON.stringify(seed()))'],text=True))
for key in ['chats','projects','folders','docs','tasks','members','groups','apiKeys','memories','audit']:
    seed[key]=[]
seed['profile']={'name':'Du','fullName':'Lokaler Nutzer','email':'','job':'','avatar':''}
seed['prefs'].update(defaultModel='auto',about='',web=False,images=False,memory=False)
seed['workspace'].update(name='LANGKAS Workspace',domain='',plan='Local',teamShare=False,description='Deine CLIs. Ein Arbeitsplatz. KI, oba koa Kas.')
seed['capabilities'].update(web=False,images=False,research=False)
seed['models']={'auto':True,'claude':True,'gemini':True,'codex':True}
seed['usage']={k:0 for k in seed['usage']}
seed['connections']={}
seed['canvas'].update(title='Neues Dokument',text='')
for a in seed['agents']:
    a.update(owner='Du',visibility='private',model='auto',knowledge=[],integrations=[],subagents=[],verified=False,history=[])
for p in seed['prompts']: p.update(owner='Du',visibility='private')
seed['workflows']=[{'id':'w_notes','name':'Notizen → Dokument','description':'Ohne KI: Notizen strukturieren und als Markdown in der Bibliothek speichern.','active':False,'runs':[],'nodes':[
 {'id':'n_start','type':'trigger','name':'Notizen eingeben','config':'Ersten Punkt klären\nZweiten Punkt planen'},
 {'id':'n_transform','type':'transform','name':'Als Liste strukturieren','config':''},
 {'id':'n_output','type':'output','name':'Dokument speichern','config':'Notizen'}]},
 {'id':'w_review','name':'Entwurf → Freigabe','description':'Deine CLI erstellt den Text. Du prüfst ihn vor dem Speichern.','active':False,'runs':[],'nodes':[
 {'id':'n_review_start','type':'trigger','name':'Auftrag eingeben','config':'Schreibe einen kurzen Statusbericht.'},
 {'id':'n_review_ai','type':'ai','name':'Text mit CLI erstellen','config':'Erstelle den gewünschten Entwurf. Erfinde keine Fakten.'},
 {'id':'n_review_approval','type':'approval','name':'Deine Freigabe','config':'Prüfe den Inhalt vor dem Speichern.'},
 {'id':'n_review_output','type':'output','name':'Freigegebenes Dokument','config':'Freigegebener Entwurf'}]}]
# Static seed is source-controlled; no identities, example chats or artificial metrics.
seed['created']=0
(ROOT/'web/seed.json').write_text(json.dumps(seed,ensure_ascii=False,indent=2)+'\n')
src=src.replace(line,'function seed(){return '+json.dumps(seed,ensure_ascii=False,separators=(',',':'))+'}')
src=src.replace(models,"const Models=[{id:'auto',name:'Auto · installierte CLI',provider:'local',mark:'terminal',desc:'Ersten verfügbaren, aktivierten Runner wählen'}];")
src=re.sub(r"^try\{const raw=localStorage.*$",'',src,flags=re.M)
src=src.replace("function badge(t,cls=''){return `<span class=\"badge ${cls}\">${t}</span>`}","function badge(t,cls=''){return `<span class=\"badge ${esc(cls)}\">${esc(t)}</span>`}")
src=src.replace("'tasks','settings'];ui.view", "'tasks','settings','runners','runs'];ui.view")
src=src.replace("model:'gpt-5.6-terra'", "model:'auto'")
src=src.replace('Models.filter(m=>store.models[m.id])',"Models.filter(m=>m.id==='auto'||live.runners.some(r=>r.id===m.id&&r.enabled&&r.available))")
src=src.replace("a?.starters?.length?a.starters:['Schreibe eine klare E-Mail','Fasse ein Dokument zusammen','Analysiere unsere Beispieldaten','Entwickle neue Ideen']", "a?.starters?.length?a.starters:['Schreibe eine klare E-Mail','Fasse ein Dokument zusammen','Erkläre mir diesen Code','Entwickle neue Ideen']")
src=src.replace('KI-Schritte sind lokale Demos. Externe Aufrufe werden nicht ausgeführt.','KI-Schritte starten echte CLI-Prozesse. Freigaben, Abbruch und Protokolle findest du unter Läufe. HTTP-Actions sind nicht aktiviert.')
src=src.replace('Kombiniere Agenten, Integrationen, Bedingungen und Human-in-the-Loop. Teste jeden Lauf, bevor du bereitstellst.','Kombiniere echte CLI-Schritte, Textverarbeitung, Bedingungen und Freigaben. Start erfolgt manuell; kein Zeitplaner.')
src=src.replace('Veröffentlichen erzeugt eine lokale Version. In einer produktiven Umgebung würden hier Workspace-, Slack- oder Teams-Freigaben greifen.','Veröffentlichen speichert eine Version in SQLite. Diese Installation hat einen lokalen Eigentümer; Team-, Slack- und Teams-Freigaben sind nicht angeschlossen.')
src=src.replace('lokale Vorschau','Vorlagen-Vorschau')
src=src.replace('Nur lokales Demoprofil. Kein Login oder E-Mail-Versand.','Lokales Profil. Die E-Mail dient nicht zur Anmeldung.')
src=src.replace("'required maxlength=\"150\"'","'maxlength=\"150\"'")
src=src.replace('Du verwaltest diesen lokalen Demo-Workspace.','Du verwaltest diesen lokalen Arbeitsplatz.')
src=src.replace('Wird im API-Modus in regulären Chats als Workspace-Kontext berücksichtigt.','Wird regulären CLI-Chats als Workspace-Kontext mitgegeben.')
src=src.replace('Nur Konfiguration. Die Demo hat keine Zugriffskontrolle.','Nicht aktiviert. Zugriff erfolgt ausschließlich mit lokalem Schlüssel / Sitzung.')
src=src.replace('Demo zurücksetzen','Workspace zurücksetzen')
src=src.replace('Entfernt alle lokalen Änderungen und lädt die Beispieldaten neu.','Entfernt Workspace-Inhalte und lädt die leeren Startvorlagen. Laufprotokolle bleiben separat erhalten.')
src=src.replace('Automatisch lokal gespeichert','In SQLite gespeichert, sobald synchronisiert')
src=src.replace('Lokal gespeichert','Workspace gespeichert')
src=src.replace('Unabhängige, lokale Demo','Lokaler CLI-Arbeitsplatz')
src=src.replace("title=Titles[ui.view]||'Chat'", "title=Titles[ui.view]||'Chat'")
# No insecure browser API endpoint path is exposed in live mode. No localStorage import at startup.
start=src.rfind('try{validateComplete(store)}')
end=src.index('</script>',start)
src=src[:start]+(ROOT/'web/bridge.js').read_text()+'\n'+src[end:]
src=src.replace('</head>','<style>\n'+(ROOT/'web/live.css').read_text()+'\n</style></head>')
(ROOT/'web/index.html').write_text(src)
print('Built web/index.html',len(src.encode()),'bytes')
