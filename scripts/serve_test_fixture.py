"""For local browser QA only. Explicit test process, not a provider integration."""
import sys,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from conftest import configured
from langcas.app import App,Server
p=Path(sys.argv[1]);configured(p);app=App(p);server=Server(('127.0.0.1',int(sys.argv[2])),app)
print('QA fixture listening',server.server_address,flush=True)
try: server.serve_forever()
except KeyboardInterrupt: pass
finally: server.server_close();app.close()
