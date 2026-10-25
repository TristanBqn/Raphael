"""Décisions des deux portes. Implémentation Jev aujourd'hui ; un modèle local pourra la remplacer.

Questions en anglais (Jev est entraîné surtout en anglais), contenu en français.
La grille de rétention vient des corrections de l'utilisateur (16/10/2026).
"""
import asyncio
import os
import re

import config

# --------------------------------------------------------------------------- questions de la porte 1


def _noul(q, oui, non):
    from typesafe_sdk import Noul, NoulCriteria
    return Noul(instructions=q, criteria=NoulCriteria(true=oui, false=non))


CONTEXTE = ("Judge `prompt`; `previous_exchanges` (most recent first) only help to understand what `prompt` refers "
            "to.")


def questions_besoin():
    return {"besoin": _noul(
        "Would a good answer to `prompt` need information about this specific user that is not written in `prompt`: "
        "their computer, servers, accounts, preferences, past decisions, or their projects? " + CONTEXTE,
        "Yes: `prompt` refers to the user's own things or history (my server, my project, as before, like last time), "
        "or asks what is known about them.",
        "No: `prompt` is self-contained, a general question, or an instruction fully specified in the message.")}


def questions_pertinence(n):
    return {f"s{i}": _noul(
        f"Would `memories[{i}]` help to answer `prompt`?",
        "Yes: it gives a fact, preference or rule that the answer should take into account.",
        "No: it is unrelated or does not change the answer.") for i in range(n)}


def questions_projet():
    """Mode projet : le message ne porte que sur le projet ouvert, dont les fichiers et git font foi."""
    return {"projet_courant": _noul(
        "Is `prompt` only about working on the current project named in `project` (its code, files, git repository, "
        "build, archives), so that the project's own files are enough to handle it? " + CONTEXTE,
        "Yes: e.g. archive this repo, fix this bug, add a file to .gitignore, commit and push these changes, put this "
        "project on GitHub, remember where this project's archive is.",
        "No: it is about the user's other machines, servers, accounts, other projects or personal life, or it asks "
        "what was remembered or decided before (where is the archive I made, like last time).")}


def questions_tiroirs(n):
    """Tiroirs proches par le sens : le message en parle-t-il vraiment ?"""
    return {f"t{i}": _noul(
        f"Is `prompt` about the subject described in `drawers[{i}]`? " + CONTEXTE,
        "Yes: `prompt`, or what it refers to in `previous_exchanges`, is about this subject.",
        "No: it is about something else, or only shares a word with it.") for i in range(n)}

# --------------------------------------------------------------------------- questions de la porte 2


def questions_capture():
    from typesafe_sdk import Choice
    q = {
        "fait": _noul("Does `exchange` reveal a lasting fact about the user's computer, network, accounts, servers, "
                      "installed tools, or where one of their projects or files is located?",
                      "Yes: a concrete fact about their setup or the location of something they own.",
                      "No: no such fact."),
        "preference": _noul("Does the user, in `exchange.user`, express how they want answers or work to be done in "
                            "general (level of detail, simplicity, tone, scope of changes)?",
                            "Yes: a working or communication preference that could apply to other requests.",
                            "No: no general preference."),
        "lecon": _noul("Does `exchange` contain a technical lesson: something that does not work, is missing or breaks, "
                       "or a fix that finally worked?",
                       "Yes: a reusable technical finding, often after an error.",
                       "No: no technical finding."),
        "regle_projet": _noul("Does `exchange` settle a decision, rule or constraint that a project must keep following?",
                              "Yes: a lasting choice or constraint for a project.",
                              "No: no lasting project decision."),
        "evenement": _noul("Does the user mention a dated personal event or plan (a trip, a meeting, a deadline)?",
                           "Yes: a personal event with a date or a relative date such as tomorrow.",
                           "No: no personal event."),
        "tache_seule": _noul("Is `exchange.user` only an instruction for the current request, such as asking to check, "
                             "audit, list, push, or not to use a tool for this answer?",
                             "Yes: it only tells the assistant what to do right now, with nothing lasting in it.",
                             "No: it contains something beyond the current request."),
        "detail_isole": _noul("Is everything in `exchange` an isolated or temporary detail unlikely to matter later "
                              "(a version seen in passing, a progress status, the assistant describing what it just did)?",
                              "Yes: only isolated or temporary details.",
                              "No: something in it could matter later."),
        "non_resolu": _noul("At the end of `exchange`, is the problem still unresolved (an error not fixed yet, a choice "
                            "still open, a fix not yet confirmed by the user)?",
                            "Yes: still in progress or waiting for confirmation.",
                            "No: resolved, decided, or nothing pending."),
        "portee": Choice(instructions="If something from `exchange` were saved, where would it be useful?",
                         criteria={"global": "In any conversation: facts about the user or their setup, general "
                                             "preferences, general technical lessons, personal events.",
                                   "projet": "Only when working on the project named in `project`."}),
    }
    return q


def score_capture(n):
    """Composite : un critère positif vrai, sans qu'une exclusion l'emporte (événements jamais exclus)."""
    positif = max(n["fait"], n["preference"], n["lecon"], n["regle_projet"], n["evenement"])
    exclusion = max(n["tache_seule"], n["detail_isole"])
    return max(positif * (1 - exclusion), n["evenement"])

# --------------------------------------------------------------------------- appels


def cle_api():
    """La variable d'environnement, sinon le registre utilisateur : une session lancée avant l'enregistrement
    de la clé ne la voit pas dans son environnement."""
    cle = os.environ.get("TYPESAFE_API_KEY")
    if cle:
        return cle
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        return winreg.QueryValueEx(k, "TYPESAFE_API_KEY")[0]


async def _appel(state, questions, delai):
    from typesafe_sdk import AsyncTypeSafeClient
    async with AsyncTypeSafeClient(api_key=cle_api(), model=config.MODELE_JEV, timeout=delai) as client:
        return await asyncio.wait_for(client.system_one(state=state, questions=questions), delai)


def appel(state, questions, delai):
    return asyncio.run(_appel(state, questions, delai))


def _forts(notes):
    return [c for p, c in notes if p >= config.SEUIL_PERTINENCE_FORTE
            and (c.get("similarite") or 0) >= config.SIMILARITE_PERTINENCE_FORTE][:config.MAX_INJECTES]


def _general(c):
    """Souvenir sur l'utilisateur lui-même (racine « toi »), valable quel que soit le projet."""
    return (c.get("tiroir") or "").split("/")[0] == "toi" or (not c.get("tiroir") and c["portee"] == "global")


def rappel(prompt, projet, candidats, precedents=(), a_verifier=(), projet_local=False):
    """Porte 1, en un seul appel : faut-il la mémoire, le message ne porte-t-il que sur le projet ouvert, quels
    tiroirs proches le concernent vraiment, et quels candidats servent ?

    `a_verifier` : descriptions des tiroirs proches par le sens à faire confirmer ; chaque candidat porte dans
    « verifier » l'index du tiroir dont il dépend (None : tiroir ouvert d'office).
    Renvoie un dict : besoin, retenus, source, projet_courant, tiroirs (index confirmés), notes (id → pertinence).
    Repli local si Jev est lent ou indisponible.
    """
    res = {"besoin": None, "retenus": [], "source": "aucun_candidat", "projet_courant": None, "tiroirs": [],
           "notes": {}}
    if not candidats:
        return res
    questions = {**questions_besoin(), **questions_pertinence(len(candidats)), **questions_tiroirs(len(a_verifier))}
    if projet_local:
        questions.update(questions_projet())
    state = {"project": projet, "prompt": prompt[:2000], "previous_exchanges": list(precedents),
             "memories": [c["texte"] for c in candidats], "drawers": list(a_verifier)}
    try:
        r = appel(state, questions, config.DELAI_JEV_PORTE1)
    except Exception:
        possessif = re.search(r"\b(mon|ma|mes|notre|nos)\b|\bcomme (la dernière fois|avant)\b|\bde moi\b",
                              prompt.lower())
        surs = [c for c in candidats if c.get("verifier") is None]   # sans Jev, seulement les tiroirs ouverts d'office
        return dict(res, besoin=0.6 if possessif else 0.3, retenus=surs[:3] if possessif else [], source="repli")
    besoin = r.nouls["besoin"].noul
    confirmes = [i for i in range(len(a_verifier)) if r.nouls[f"t{i}"].noul >= config.SEUIL_TIROIR]
    projet_courant = r.nouls["projet_courant"].noul if projet_local else None
    res.update(besoin=besoin, projet_courant=projet_courant, tiroirs=confirmes,
               notes={c["id"]: round(r.nouls[f"s{i}"].noul, 2) for i, c in enumerate(candidats)})
    notes = sorted(((r.nouls[f"s{i}"].noul, c) for i, c in enumerate(candidats)
                    if c.get("verifier") is None or c["verifier"] in confirmes), key=lambda x: -x[0])
    if projet_courant is not None and projet_courant >= config.SEUIL_PROJET_COURANT:
        # Mode projet : les fichiers et git font foi (un fait mémorisé peut être périmé). Seules les préférences
        # et leçons générales passent, et seulement si Jev les juge très pertinentes.
        res.update(retenus=_forts([(p, c) for p, c in notes if c["type"] in ("preference", "lecon") and _general(c)]),
                   source="jev_projet")
        return res
    if besoin < config.SEUIL_BESOIN_MEMOIRE:
        forts = _forts(notes)
        res.update(retenus=forts, source="jev_pertinence_forte" if forts else "jev")
        return res
    retenus = [c for p, c in notes if p >= config.SEUIL_PERTINENCE][:config.MAX_INJECTES]
    if not retenus and besoin >= config.SEUIL_BESOIN_FORT:
        # Rattrapage : la question concerne clairement l'utilisateur, un souvenir est proche par le sens et Jev
        # ne l'exclut pas franchement. Injecter en trop coûte peu ; ne rien injecter laisse Claude deviner.
        proches = [(p, c) for p, c in notes if (c.get("similarite") or 0) >= config.SIMILARITE_RATTRAPAGE
                   and p >= config.PERTINENCE_RATTRAPAGE]
        if proches:   # Jev hésite : c'est le sens qui départage
            res.update(retenus=[max(proches, key=lambda x: x[1]["similarite"])[1]], source="jev_rattrapage")
            return res
    res.update(retenus=retenus, source="jev")
    return res


def evaluer_capture(user, assistant, projet):
    """Porte 2 (dans le worker). Renvoie le détail des probabilités, le score et la portée suggérée."""
    state = {"project": projet, "exchange": {"user": user[:3000], "assistant": (assistant or "")[:3000]}}
    r = appel(state, questions_capture(), 30)
    n = {k: v.noul for k, v in r.nouls.items()}
    return {"nouls": n, "score": score_capture(n), "portee": r.choices["portee"].choice,
            "portee_conf": r.choices["portee"].confidence, "tokens": r.usage.input_tokens}
