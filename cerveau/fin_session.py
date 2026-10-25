"""Hook SessionEnd : les échanges encore « en attente » de cette session seront tranchés au prochain passage du worker."""
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
from lanceur import lancer_worker  # noqa: E402
import store  # noqa: E402


def main():
    data = json.load(sys.stdin)
    if config.exclu(data.get("cwd")):
        return
    cx = store.connexion()
    with cx:
        n = cx.execute("UPDATE echanges SET attentes = ? WHERE session_id = ? AND statut = 'en_attente'",
                       (config.MAX_ATTENTES, data.get("session_id"))).rowcount
        # Un message envoyé puis interrompu n'aura jamais de porte 2 : on l'évalue quand même.
        m = cx.execute("UPDATE echanges SET statut = 'a_evaluer' WHERE session_id = ? AND statut = 'en_cours'",
                       (data.get("session_id"),)).rowcount
        # Enregistrée en base : même si un worker tourne déjà, il saura qu'il doit rédiger ce lot sans attendre.
        cx.execute("INSERT OR REPLACE INTO sessions_finies(session_id, ts) VALUES (?, ?)",
                   (data.get("session_id"), time.time()))
    lancer_worker(forcer=True)   # la conversation est finie : on rédige même un lot incomplet
    log("fin_session", session=data.get("session_id"), en_attente=n, interrompus=m)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("fin_session_erreur", trace=traceback.format_exc()[-800:])
