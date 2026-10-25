"""Bilan de santé du cerveau Jev (lint et health-check de la base SQLite).

Contrôles déterministes (base, journal) et, avec --sonde, contrôles en direct (Jev, service d'embeddings,
contradictions entre souvenirs proches). Le résultat est écrit dans sante.json, que le hook de démarrage affiche.
Usage : python sante.py [--sonde]
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import store  # noqa: E402

FICHIER = os.path.join(config.DONNEES, "sante.json")
MAX_PAIRES_CONTRADICTION = 10
SEUIL_CONTRADICTION = 0.7


def paires_proches(cx, bas, haut, limite):
    import numpy as np
    from embeddings import depuis_blob
    act = [r for r in cx.execute("SELECT id, texte, embedding FROM souvenirs WHERE actif = 1 AND embedding IS NOT NULL")]
    if len(act) < 2:
        return []
    v = np.stack([depuis_blob(r["embedding"]) for r in act])
    s = v @ v.T
    i, j = np.triu_indices(len(act), 1)
    choix = [(float(s[a, b]), act[a], act[b]) for a, b in zip(i, j) if bas <= s[a, b] < haut]
    return sorted(choix, key=lambda x: -x[0])[:limite]


def contradictions(cx):
    """Jev juge, en un seul appel, si des souvenirs proches par le sens se contredisent."""
    import decideur
    paires = paires_proches(cx, 0.75, 0.97, MAX_PAIRES_CONTRADICTION)
    if not paires:
        return []
    questions = {f"p{k}": decideur._noul(
        f"Do `pairs[{k}].a` and `pairs[{k}].b` state facts that cannot both be true at the same time?",
        "Yes: one says something the other contradicts (different value, opposite decision, outdated status).",
        "No: they are compatible, complementary, or say the same thing.") for k in range(len(paires))}
    r = decideur.appel({"pairs": [{"a": a["texte"], "b": b["texte"]} for _, a, b in paires]}, questions, 30)
    return [{"a": a["id"], "b": b["id"], "p": round(r.nouls[f"p{k}"].noul, 2)}
            for k, (_, a, b) in enumerate(paires) if r.nouls[f"p{k}"].noul >= SEUIL_CONTRADICTION]


def bilan(sonde=False):
    cx = store.connexion()
    q = lambda sql, *a: cx.execute(sql, a).fetchone()[0]  # noqa: E731
    maintenant = time.time()
    b = {
        "ts": maintenant,
        "souvenirs": q("SELECT COUNT(*) FROM souvenirs WHERE actif = 1"),
        "sans_vecteur": q("SELECT COUNT(*) FROM souvenirs WHERE actif = 1 AND embedding IS NULL"),
        "expires": q("SELECT COUNT(*) FROM souvenirs WHERE actif = 1 AND expire < date('now')"),
        "juges_inutiles": q("SELECT COUNT(*) FROM souvenirs WHERE actif = 1 AND retours LIKE '%inutile%'"),
        "jamais_utilises_60j": q("SELECT COUNT(*) FROM souvenirs WHERE actif = 1 AND utilisations = 0 AND ts < ?",
                                 maintenant - 60 * 86400),
        "quasi_doublons": len(paires_proches(cx, 0.92, 1.01, 100)),
        "echanges_bloques": q("SELECT COUNT(*) FROM echanges WHERE (statut = 'en_cours' AND ts < ?) "
                              "OR (statut = 'en_attente' AND maj < ?) OR statut = 'erreur'",
                              maintenant - 3600, maintenant - 86400),
        "erreurs_24h": 0,
    }
    if os.path.exists(config.JOURNAL):
        with open(config.JOURNAL, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    e = json.loads(ligne)
                except ValueError:
                    continue
                if e["t"] > maintenant - 86400 and ("erreur" in e["evt"] or "illisible" in e["evt"]):
                    b["erreurs_24h"] += 1
    try:
        import decideur
        decideur.cle_api()
        b["cle_api"] = True
    except Exception:
        b["cle_api"] = False
    if sonde:
        b["service"] = service_ok()
        b["jev"], b["jev_ms"] = jev_ok() if b["cle_api"] else (False, None)
        try:
            b["contradictions"] = contradictions(cx) if b["jev"] else None
        except Exception:
            b["contradictions"] = None
    return b


def service_ok():
    """Le service s'arrête seul après inactivité : arrêté n'est pas une panne. On le relance, et seul un échec du
    redémarrage est signalé."""
    def ping():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{config.PORT_EMBEDDINGS}/", timeout=2) as r:
                return json.loads(r.read()).get("ok", False)
        except OSError:
            return False
    if ping():
        return True
    from lanceur import lancer_service
    lancer_service()
    for _ in range(15):          # le modèle met 1 à 2 s à charger
        time.sleep(1)
        if ping():
            return True
    return False


def jev_ok():
    import decideur
    t0 = time.perf_counter()
    try:
        decideur.appel({"text": "ping"}, {"ok": decideur._noul("Is `text` a word?", "Yes.", "No.")}, 5)
        return True, round((time.perf_counter() - t0) * 1000)
    except Exception:
        return False, None


def problemes(b):
    p = []
    if not b.get("cle_api"):
        p.append("clé Jev introuvable")
    if b.get("jev") is False:
        p.append("Jev injoignable")
    if b.get("service") is False:
        p.append("service d'embeddings arrêté")
    if b["sans_vecteur"]:
        p.append(f"{b['sans_vecteur']} souvenir(s) sans vecteur")
    if b["echanges_bloques"]:
        p.append(f"{b['echanges_bloques']} échange(s) bloqué(s)")
    if b["erreurs_24h"]:
        p.append(f"{b['erreurs_24h']} erreur(s) en 24 h (voir cerveau.log)")
    if b.get("contradictions"):
        p.append(f"{len(b['contradictions'])} contradiction(s) possible(s) : "
                 + ", ".join(f"n° {c['a']} / n° {c['b']}" for c in b["contradictions"][:3]))
    if b["quasi_doublons"]:
        p.append(f"{b['quasi_doublons']} quasi-doublon(s)")
    return p


def banniere(b, univers):
    p = problemes(b)
    etat = "✅ en forme" if not p else "⚠️ " + " · ".join(p)
    return f"🧠 Cerveau Jev · {b['souvenirs']} souvenirs · univers {univers} · {etat}"


def main():
    sonde = "--sonde" in sys.argv
    b = bilan(sonde)
    config.assurer_dossier()
    with open(FICHIER, "w", encoding="utf-8") as fh:
        json.dump(b, fh, ensure_ascii=False)
    if sys.stdout and sys.stdout.isatty() or "--afficher" in sys.argv:
        config.flux_utf8()
        print(banniere(b, config.univers_de(os.getcwd())))
        print(json.dumps({k: v for k, v in b.items() if k != "ts"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
