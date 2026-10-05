from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os

ROOT = Path(__file__).parent
PORT = int(os.getenv('PORT', '5173'))
os.chdir(ROOT)
print(f'Community Agent preview: http://127.0.0.1:{PORT}')
ThreadingHTTPServer(('0.0.0.0', PORT), SimpleHTTPRequestHandler).serve_forever()
