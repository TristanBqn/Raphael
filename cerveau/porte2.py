"""Porte 2 (hook Stop) : complète l'échange avec la réponse de Claude, le dépose dans l'inbox, réveille le worker.

Rapide (quelques ms) : l'évaluation par Jev et la rédaction se font dans le worker.
"""
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
from masque import mask_secrets  # noqa: E402
import store  # noqa: E402


def main():
    t0 = time.perf_counter()
    data = json.load(sys.stdin)
    if config.exclu(data.get("cwd")):
        return
    reponse = mask_secrets(str(data.get("last_assistant_message") or ""))
    cx = store.connexion()
    with cx:
        ligne = cx.execute("SELECT * FROM echanges WHERE session_id = ? AND prompt_id = ? ORDER BY id DESC LIMIT 1",
                           (data.get("session_id"), data.get("prompt_id"))).fetchone()
        if ligne and ligne["statut"] in ("en_cours", "a_evaluer"):
            cx.execute("UPDATE echanges SET assistant_text = ?, statut = 'a_evaluer', maj = ? WHERE id = ?",
                       (reponse, time.time(), ligne["id"]))
        elif ligne:
            # Nouvel arrêt pour le même message (un /goal relance Claude) : la suite devient un échange à part,
            # sans réévaluer ce qui a déjà été traité.
            cx.execute("INSERT INTO echanges(ts, session_id, prompt_id, projet, cwd, univers, user_text, "
                       "assistant_text, statut, maj) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'a_evaluer', ?)",
                       (time.time(), ligne["session_id"], ligne["prompt_id"], ligne["projet"], ligne["cwd"],
                        ligne["univers"], "(suite) " + ligne["user_text"], reponse, time.time()))
        else:
            log("porte2_sans_porte1", session=data.get("session_id"))
    lancer_worker()
    log("porte2", echange=ligne["id"] if ligne else None, ms=round((time.perf_counter() - t0) * 1000))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("porte2_erreur", trace=traceback.format_exc()[-800:])
