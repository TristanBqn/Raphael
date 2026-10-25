"""Import de l'historique Claude Code dans le second cerveau.

1. Découpe chaque session en échanges (message de l'utilisateur + réponse de Claude), sans le bruit.
2. Évalue chaque échange avec Jev, en lui donnant la suite de la conversation (pas d'attente : on connaît la suite).
3. Fait rédiger les souvenirs dans l'ordre chronologique, puis calcule leurs vecteurs.

Usage : python import_historique.py [--evaluer-seulement]
"""
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
sys.path.insert(0, os.path.join(ICI, "..", "outils"))
import config  # noqa: E402
import decideur  # noqa: E402
import store  # noqa: E402
import worker  # noqa: E402
from historique import load_sessions  # noqa: E402
from filtres import message_utilisateur  # noqa: E402
from journal import log  # noqa: E402

PROJETS_EXCLUS = re.compile(r"Temp|scratch|pilote|spikes|hooks-test|cerveau", re.I)
CONCURRENCE = 8
LOT_IMPORT = 8


def date_ts(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def decouper(session):
    """Échanges utiles d'une session : [(ts, texte utilisateur, texte Claude)]."""
    tours, courant = [], None
    for e in session.events:
        if e.role == "user":
            texte = message_utilisateur(e.text)
            if texte is None:
                courant = None
                continue
            courant = [date_ts(e.timestamp), texte, []]
            tours.append(courant)
        elif courant is not None:
            courant[2].append(e.text if e.role == "assistant" else "[erreur d'outil] " + e.text)
    return [(ts, u, "\n".join(a)) for ts, u, a in tours]


async def evaluer_tout(items):
    sem = asyncio.Semaphore(CONCURRENCE)

    async def un(item):
        async with sem:
            state = {"project": item["projet"],
                     "exchange": {"user": item["user"][:3000], "assistant": item["assistant"][:3000]},
                     "what_happened_next": item["suite"][:1500]}
            for essai in range(3):
                try:
                    r = await decideur._appel(state, decideur.questions_capture(), 60)
                    n = {k: v.noul for k, v in r.nouls.items()}
                    return {"nouls": n, "score": decideur.score_capture(n), "portee": r.choices["portee"].choice,
                            "tokens": r.usage.input_tokens}
                except Exception as exc:
                    erreur = str(exc)[:200]
                    await asyncio.sleep(2 * (essai + 1))
            return {"erreur": erreur}

    return await asyncio.gather(*(un(i) for i in items))


def main():
    cx = store.connexion()
    fh = worker.verrou()          # aucun worker de fond ne doit rédiger en même temps
    if fh is None:
        print("Un worker tourne déjà : réessaie dans une minute.")
        return
    t0 = time.perf_counter()
    items = []
    for s in load_sessions():
        if PROJETS_EXCLUS.search(s.project) or PROJETS_EXCLUS.search(s.cwd or ""):
            continue
        tours = decouper(s)
        projet = store.projet_de(s.cwd)
        for i, (ts, u, a) in enumerate(tours):
            suite = " | ".join(t[1][:500] for t in tours[i + 1:i + 3])   # les deux messages suivants de l'utilisateur
            items.append({"session": s.session_id, "rang": i, "ts": ts, "projet": projet,
                          "user": u, "assistant": a, "suite": suite})
    print(f"{len(items)} échanges à évaluer")
    resultats = asyncio.run(evaluer_tout(items))
    gardes = 0
    with cx:
        for it, ev in zip(items, resultats):
            if "erreur" in ev:
                statut = "erreur"
            else:
                statut = "a_ecrire" if ev["score"] >= config.SEUIL_CAPTURE else "rejete"
            gardes += statut == "a_ecrire"
            cx.execute("INSERT INTO echanges(ts, session_id, prompt_id, projet, user_text, assistant_text, statut, "
                       "score, details, maj) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (it["ts"], it["session"], f"import-{it['rang']}", it["projet"], it["user"], it["assistant"],
                        statut, ev.get("score"), json.dumps(ev), time.time()))
    tokens = sum(ev.get("tokens", 0) for ev in resultats)
    print(f"Jev : {gardes} échanges à rédiger sur {len(items)} ({tokens:,} tokens, ≈ {tokens * 0.042 / 1e6:.3f} $), "
          f"{sum('erreur' in ev for ev in resultats)} erreurs, {time.perf_counter() - t0:.0f} s")
    log("import_evaluation", echanges=len(items), a_ecrire=gardes, tokens=tokens)
    if "--evaluer-seulement" in sys.argv:
        return
    lots = 0
    while True:
        n = worker.rediger(cx, LOT_IMPORT, annoncer=False, forcer=True)   # pas d'annonce : des centaines de souvenirs noieraient l'écran
        if n == 0:
            break
        lots += 1
        restant = cx.execute("SELECT COUNT(*) FROM echanges WHERE statut = 'a_ecrire'").fetchone()[0]
        print(f"lot {lots} rédigé, reste {restant} échanges", flush=True)
    worker.vectoriser(cx)
    total = cx.execute("SELECT COUNT(*) FROM souvenirs WHERE actif = 1").fetchone()[0]
    print(f"Terminé en {time.perf_counter() - t0:.0f} s : {lots} lots, {total} souvenirs actifs")
    log("import_fin", lots=lots, souvenirs=total)
    fh.close()


if __name__ == "__main__":
    main()
