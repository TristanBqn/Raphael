"""Arbre des tiroirs : chaque souvenir est rangé sous racine/sujet/sous-sujet…

Le rédacteur (Haiku) descend l'arbre et range chaque souvenir dans le tiroir le plus profond qui correspond, ou crée
un tiroir au bon endroit. Le code garantit qu'un sujet n'existe qu'à un seul endroit et décide quels tiroirs le
rappel ouvre : le tiroir du dossier de travail, ceux dont le message parle, et les tiroirs toujours ouverts.
"""
import json
import re
import time
import unicodedata

import config

REGLES = """Tiroir (champ "tiroir") : range chaque souvenir dans l'arbre ci-dessous, en donnant son chemin complet.
1. Un sujet n'existe qu'à UN SEUL endroit de l'arbre : si un tiroir existant porte sur ce sujet, range le souvenir
   dedans ou dans l'un de ses sous-tiroirs. Ne recrée jamais un sujet ailleurs.
2. Sinon, pars de la racine (toi, perso, ou l'univers employeur ou client de l'échange) et descends tant qu'un tiroir
   correspond ; arrête-toi au tiroir le plus profond qui correspond.
3. Un projet qui a un dossier sur le PC va dans son tiroir de projet (champ "tiroir_projet" de l'échange), jamais
   sous une machine. Seul un service SANS dossier local va sous la machine qui le fait tourner (un agent installé sur
   un serveur : toi/<serveur>/<agent>). Un outil installé va dans toi/Outils. Une fonction va sous le service qui
   l'assure.
4. Si aucun sous-tiroir ne correspond et que le sujet est DURABLE (une machine, un service, un projet, un composant,
   un domaine où d'autres souvenirs viendront), crée un tiroir au bon endroit : donne son chemin, une description
   d'une ligne et 3 à 5 mots-clés dans "nouveaux_tiroirs". Une anecdote ou un sujet ponctuel reste dans le tiroir
   parent : pas de tiroir pour un seul souvenir isolé.
Noms de tiroirs courts (nom propre ou un à trois mots), sans « / ». Réutilise exactement les noms existants.

Arbre actuel (chemin : description) :
{arbre}"""


def norme(s):
    """Nom comparable : sans accents, sans casse, sans ponctuation."""
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(s).lower()).encode("ascii", "ignore").decode())


def racines():
    """Racines fixes : toi, perso, et une par univers employeur ou client (config.UNIVERS)."""
    r = dict(config.RACINES)
    for _, nom in config.UNIVERS:
        r.setdefault(nom, f"univers {nom} : le travail dans ce contexte et ses projets")
    return r


def clients():
    return {nom for _, nom in config.UNIVERS}


def assurer_racines(cx):
    for chemin, description in racines().items():
        cx.execute("INSERT OR IGNORE INTO tiroirs(chemin, description, mots_cles, ts) VALUES (?, ?, '[]', ?)",
                   (chemin, description, time.time()))


def arbre(cx):
    return {r["chemin"]: dict(r) for r in cx.execute("SELECT * FROM tiroirs ORDER BY chemin")}


def mots_cles(t):
    return json.loads(t["mots_cles"] or "[]") if t else []


def texte_arbre(cx):
    return "\n".join(f"- {c} : {t['description'] or ''}" + (f" [mots-clés : {', '.join(mots_cles(t))}]"
                                                             if mots_cles(t) else "")
                     for c, t in arbre(cx).items())


def regles(cx):
    return REGLES.format(arbre=texte_arbre(cx))


def _domaine(chemin):
    """Les univers clients sont cloisonnés : un nom n'y est rapproché que d'un tiroir du même univers."""
    racine = chemin.split("/", 1)[0]
    return racine if racine in clients() else ""


def resoudre(cx, chemin, description=None, mots=None, projet=None):
    """Chemin proposé → tiroir réel, créé au besoin avec ses parents. Renvoie (chemin, tiroirs créés).

    Anti-doublon : un étage qui répète son parent disparaît (Client/CLIENT), et un nom déjà présent ailleurs
    dans l'arbre (sans accents ni casse) renvoie vers ce tiroir : un sujet n'existe qu'à un seul endroit.
    Un chemin qui ne part pas d'une racine est rangé sous l'univers par défaut.
    """
    existants = arbre(cx)
    parties = [p.strip() for p in str(chemin or "").split("/") if p.strip()]
    if not parties:
        return None, []
    racine = next((r for r in racines() if norme(r) == norme(parties[0])), None)
    parties = [racine] + parties[1:] if racine else [config.UNIVERS_DEFAUT] + parties
    actuel, crees = parties[0], []
    for i, p in enumerate(parties[1:], 1):
        dernier = i == len(parties) - 1
        if norme(actuel.rsplit("/", 1)[-1]) == norme(p):
            continue
        meme = next((c for c in existants if "/" in c and norme(c.rsplit("/", 1)[-1]) == norme(p)
                     and _domaine(c) == _domaine(actuel)), None)
        if meme:
            actuel = meme
            if dernier and description and not existants[meme].get("description"):
                cx.execute("UPDATE tiroirs SET description = ?, mots_cles = ? WHERE chemin = ?",
                           (description, json.dumps(mots or [], ensure_ascii=False), meme))
            continue
        actuel = f"{actuel}/{p}"
        cx.execute("INSERT INTO tiroirs(chemin, description, mots_cles, projet, ts) VALUES (?, ?, ?, ?, ?)",
                   (actuel, description if dernier else None,
                    json.dumps((mots or []) if dernier else [], ensure_ascii=False),
                    projet if dernier else None, time.time()))
        existants[actuel] = {"description": description if dernier else None}
        crees.append(actuel)
    if projet and actuel != parties[0]:
        cx.execute("UPDATE tiroirs SET projet = ? WHERE chemin = ? AND projet IS NULL", (projet, actuel))
    return actuel, crees


def tiroir_du_projet(cx, projet):
    if not projet or projet == "perso":
        return None
    r = cx.execute("SELECT chemin FROM tiroirs WHERE projet = ?", (projet,)).fetchone()
    return r["chemin"] if r else None


def assurer_tiroir_projet(cx, projet, univers):
    """Tiroir d'un dossier de projet local : créé sous perso (ou sous l'univers client) au premier souvenir."""
    if not projet or projet == "perso":
        return None, []
    chemin = tiroir_du_projet(cx, projet)
    if chemin:
        return chemin, []
    racine = univers if univers in clients() else "perso"
    return resoudre(cx, f"{racine}/{projet}", f"projet local « {projet} »", [projet], projet)


def ouvrir(cx, chemins, avec_sous_tiroirs=True):
    """Tiroirs ouverts : les chemins donnés, leurs parents et (par défaut) leurs sous-tiroirs."""
    tous, ouverts = arbre(cx), set()
    for c in chemins:
        if c not in tous:
            continue
        parties = c.split("/")
        ouverts.update("/".join(parties[:i]) for i in range(1, len(parties) + 1))
        if avec_sous_tiroirs:
            ouverts.update(t for t in tous if t.startswith(c + "/"))
    return ouverts


def toujours_ouverts(cx):
    return (ouvrir(cx, config.TOUJOURS_OUVERTS, avec_sous_tiroirs=False)
            | ouvrir(cx, config.TOUJOURS_OUVERTS_AVEC_SOUS_TIROIRS))


def _mots(texte):
    return " " + re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", str(texte).lower())
                        .encode("ascii", "ignore").decode()).strip() + " "


def mentionnes(cx, texte):
    """Tiroirs dont le nom ou un mot-clé apparaît dans le texte (mot entier, sans accents ni casse)."""
    t, trouves = _mots(texte), []
    for c, tiroir in arbre(cx).items():
        if "/" not in c:
            continue
        termes = [c.rsplit("/", 1)[-1]] + mots_cles(tiroir)
        if any(len(_mots(m).strip()) >= 2 and _mots(m) in t for m in termes):
            trouves.append(c)
    return trouves


def sujet(chemin):
    """Tiroir de premier niveau sous la racine (toi/Serveur, perso/MonProjet…) : l'unité que Jev confirme."""
    return "/".join(chemin.split("/")[:2])


def proches(cx, vecteur, deja, n):
    """Sujets dont un souvenir est proche du message par le sens, hors sujets déjà ouverts : Jev confirmera."""
    if vecteur is None:
        return []
    import numpy as np
    from embeddings import depuis_blob
    lignes = [r for r in cx.execute("SELECT tiroir, embedding FROM souvenirs WHERE actif = 1 AND tiroir LIKE '%/%' "
                                    "AND embedding IS NOT NULL")]
    if not lignes:
        return []
    sims = np.stack([depuis_blob(r["embedding"]) for r in lignes]) @ vecteur
    meilleur = {}
    for r, s in zip(lignes, sims):
        k = sujet(r["tiroir"])
        if k not in deja and s >= config.SIMILARITE_MIN:
            meilleur[k] = max(meilleur.get(k, -1), float(s))
    return sorted(meilleur, key=lambda k: -meilleur[k])[:n]
