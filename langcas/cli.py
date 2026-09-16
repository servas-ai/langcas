"""Command-line entry point: server, health checks and registered CLI adapters."""
from __future__ import annotations
import argparse
import json
import os
import signal
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from . import __version__
from .config import Config


def main():
    parser=argparse.ArgumentParser(prog='langcas',description='LANGKAS · KI, oba koa Kas. Lokale UI für deine CLI-Assistenten.')
    parser.add_argument('--version',action='version',version=__version__)
    commands=parser.add_subparsers(dest='command',required=True)
    default_port=int(os.environ.get('LANGKAS_PORT',8877))
    serve=commands.add_parser('serve',help='Lokalen Server starten')
    serve.add_argument('--port',type=int,default=default_port)
    serve.add_argument('--open',action='store_true',help='UI im Standardbrowser öffnen')
    commands.add_parser('token',help='Lokalen Zugriffsschlüssel anzeigen')
    commands.add_parser('doctor',help='Installierte Runner prüfen (kein Modellaufruf)')
    ask=commands.add_parser('ask',help='Über den laufenden LANGKAS-Server fragen')
    ask.add_argument('prompt',nargs='?')
    ask.add_argument('--runner',default='auto')
    ask.add_argument('--model',default='')
    ask.add_argument('--port',type=int,default=default_port)
    ask.add_argument('--json',action='store_true')
    add=commands.add_parser('add-runner',help='Vertrauenswürdigen lokalen CLI-Adapter registrieren')
    add.add_argument('id'); add.add_argument('--name'); add.add_argument('--exec',dest='executable',required=True)
    add.add_argument('--arg',action='append',default=[])
    add.add_argument('--input',choices=['text','json'],default='text')
    add.add_argument('--output',choices=['text','jsonl'],default='text')
    add.add_argument('--permission',choices=['read-only','workspace-write'],default='read-only')
    add.add_argument('--timeout',type=int,default=180)
    enable=commands.add_parser('enable',help='Runner lokal aktivieren/deaktivieren')
    enable.add_argument('id'); enable.add_argument('--disable',action='store_true')
    workspace=commands.add_parser('add-workspace',help='Arbeitsverzeichnis lokal freigeben')
    workspace.add_argument('id'); workspace.add_argument('path'); workspace.add_argument('--name')
    args=parser.parse_args()
    try:
        config=Config()
        if args.command=='token': print(config.token); return
        if args.command=='doctor':
            print('LANGKAS '+__version__+' · '+sys.platform+' · Python '+sys.version.split()[0])
            print('Daten: '+str(config.directory))
            for r in config.public_runners(): print(f"{r['id']:18} {r['status']:16} {r['permission']} · Anmeldung ungeprüft")
            print('Keine kostenpflichtige Anfrage ausgeführt. Server nach lokalen Konfigurationsänderungen neu laden.')
            return
        if args.command in ('add-runner','enable','add-workspace'):
            data=config.raw
            if args.command=='add-runner':
                if args.id in config.runners: raise ValueError('Runner existiert bereits. runners.json gezielt bearbeiten.')
                data['runners'].append({'id':args.id,'name':args.name or args.id,'adapter':'generic','command':args.executable,
                    'args':args.arg,'input':args.input,'output':args.output,'permission':args.permission,
                    'timeout':args.timeout,'enabled':True,'priority':10})
            elif args.command=='enable':
                found=False
                for r in data['runners']:
                    if r['id']==args.id: r['enabled']=not args.disable; found=True
                if not found: raise ValueError('Runner nicht gefunden.')
            else:
                path=Path(args.path).expanduser().resolve()
                if not path.is_dir(): raise ValueError('Workspace-Verzeichnis existiert nicht.')
                data['workspaces'].append({'id':args.id,'path':str(path),'name':args.name or args.id})
            config.save(data)
            print('Gespeichert. In der UI unter Runner „Neu erkennen“ wählen.'); return
        if args.command=='ask':
            prompt=args.prompt or (sys.stdin.read() if not sys.stdin.isatty() else '')
            if not prompt.strip(): raise ValueError('Prompt fehlt.')
            model=args.runner+('/'+args.model if args.model else '')
            request=urllib.request.Request(f'http://127.0.0.1:{args.port}/v1/chat/completions',
                        data=json.dumps({'model':model,'messages':[{'role':'user','content':prompt}],'stream':not args.json}).encode(),
                        headers={'Content-Type':'application/json','Authorization':'Bearer '+config.token})
            try:
                with urllib.request.urlopen(request,timeout=3700) as response:
                    if args.json: print(response.read().decode()); return
                    for raw in response:
                        line=raw.decode().strip()
                        if not line.startswith('data: '): continue
                        if line=='data: [DONE]': break
                        event=json.loads(line[6:])
                        if 'error' in event: raise ValueError(event['error']['message'])
                        text=event.get('choices',[{}])[0].get('delta',{}).get('content','')
                        print(text,end='',flush=True)
                    print()
            except urllib.error.HTTPError as exc:
                try: message=json.loads(exc.read())['error']['message']
                except Exception: message=str(exc)
                raise ValueError(message) from None
            return
        if args.command=='serve':
            if not 0<=args.port<=65535: raise ValueError('Ungültiger Port.')
            from .app import App,Server
            app=App(config.directory)
            try: server=Server(('127.0.0.1',args.port),app)
            except OSError:
                app.close(); raise
            url='http://127.0.0.1:'+str(server.server_address[1])
            print('LANGKAS '+__version__+' · '+url,flush=True)
            print('Nur lokal erreichbar. Anmeldung mit: python3 -m langcas token',flush=True)
            print('Zum Beenden Ctrl+C. Provider können Cloud-Dienste nutzen.',flush=True)
            if args.open: webbrowser.open(url)
            def stop(*_): threading.Thread(target=server.shutdown,daemon=True).start()
            signal.signal(signal.SIGTERM,stop)
            signal.signal(signal.SIGINT,stop)
            try: server.serve_forever(poll_interval=.2)
            finally: server.server_close(); app.close()
    except (ValueError,OSError,urllib.error.URLError) as exc:
        print('LANGKAS: '+str(exc),file=sys.stderr)
        sys.exit(1)

if __name__=='__main__': main()
