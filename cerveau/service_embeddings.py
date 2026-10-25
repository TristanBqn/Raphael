"""Service local d'embeddings : garde EmbeddingGemma en mémoire, écoute sur 127.0.0.1, s'arrête seul après inactivité."""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import embeddings  # noqa: E402
from journal import log  # noqa: E402

derniere_requete = time.time()
verrou_modele = threading.Lock()


class Gestionnaire(BaseHTTPRequestHandler):
    def do_GET(self):
        self._repondre(200, {"ok": True, "pid": os.getpid()})

    def do_POST(self):
        global derniere_requete
        derniere_requete = time.time()
        try:
            corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            with verrou_modele:
                v = embeddings.calculer(corps["textes"], corps.get("mode", "document"))
            self._repondre(200, {"vecteurs": v.tolist()})
        except Exception as e:
            self._repondre(400, {"erreur": str(e)})

    def _repondre(self, code, donnees):
        corps = json.dumps(donnees).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *args):
        pass


def surveiller(serveur):
    while time.time() - derniere_requete < config.VEILLE_SERVICE:
        time.sleep(30)
    log("service_embeddings_veille")
    serveur.shutdown()


def main():
    try:
        serveur = ThreadingHTTPServer(("127.0.0.1", config.PORT_EMBEDDINGS), Gestionnaire)
    except OSError:
        return  # déjà lancé par un autre hook
    t0 = time.perf_counter()
    embeddings.calculer(["préchauffage"], "requete")
    log("service_embeddings_pret", pid=os.getpid(), s=round(time.perf_counter() - t0, 2))
    threading.Thread(target=surveiller, args=(serveur,), daemon=True).start()
    serveur.serve_forever()


if __name__ == "__main__":
    main()
