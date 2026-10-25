"""Range dans un univers les souvenirs qui n'en ont pas encore (souvenirs antérieurs aux univers).

Jev choisit l'univers ; si sa confiance est faible, le souvenir reste commun (visible partout).
Usage : python classer_univers.py [--appliquer]   (sans option : simulation)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import decideur  # noqa: E402
import store  # noqa: E402

CONFIANCE_MIN = 0.5
CONFIANCE_CLIENT = 0.75


def question():
    from typesafe_sdk import Choice
    return {"univers": Choice(**config.UNIVERS_JEV)}


async def classer(souvenirs):
    sem = asyncio.Semaphore(8)

    async def un(s):
        async with sem:
            r = await decideur._appel({"memory": s["texte"]}, question(), 30)
            c = r.choices["univers"]
            return c.choice, c.confidence
    return await asyncio.gather(*(un(s) for s in souvenirs))


def main():
    cx = store.connexion()
    souvenirs = cx.execute("SELECT id, texte FROM souvenirs WHERE univers IS NULL").fetchall()
    resultats = asyncio.run(classer(souvenirs))
    decisions = {}
    for s, (choix, conf) in zip(souvenirs, resultats):
        # Ranger chez un client cache le souvenir partout ailleurs : on l'exige avec plus de confiance.
        seuil = CONFIANCE_CLIENT if choix not in ("commun", "perso") else CONFIANCE_MIN
        univers = None if choix == "commun" or conf < seuil else choix
        decisions[s["id"]] = univers
        print(f"{univers or 'commun':9s} ({choix} {conf:.2f}) {s['texte'][:95]}")
    from collections import Counter
    print("\nbilan :", Counter(v or "commun" for v in decisions.values()))
    if "--appliquer" in sys.argv:
        with cx:
            for sid, univers in decisions.items():
                cx.execute("UPDATE souvenirs SET univers = ? WHERE id = ?", (univers, sid))
        print("appliqué")


if __name__ == "__main__":
    main()
