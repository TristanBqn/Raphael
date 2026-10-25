"""Hook SessionStart : affiche le dernier bilan de santé connu, relance un bilan complet et démarre le service
d'embeddings en arrière-plan (le premier message de la session n'attend plus le chargement du modèle)."""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

if os.environ.get(config.GARDE):
    sys.exit(0)
config.flux_utf8()

from journal import log  # noqa: E402
from lanceur import _lancer, lancer_service  # noqa: E402

PERIME = 6 * 3600   # au-delà, le bilan affiché est signalé comme ancien


def main():
    data = json.load(sys.stdin)
    if config.exclu(data.get("cwd")):
        return
    lancer_service()
    _lancer("sante.py", ["--sonde"])
    import sante
    try:
        with open(sante.FICHIER, encoding="utf-8") as fh:
            b = json.load(fh)
    except (OSError, ValueError):
        print(json.dumps({"systemMessage": "🧠 Cerveau Jev · premier bilan de santé en cours…"}, ensure_ascii=False))
        return
    message = sante.banniere(b, config.univers_de(data.get("cwd")))
    if time.time() - b["ts"] > PERIME:
        message += f" (bilan du {time.strftime('%d/%m %H:%M', time.localtime(b['ts']))})"
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    log("demarrage", source=data.get("source"), banniere=message)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("demarrage_erreur", trace=traceback.format_exc()[-800:])
