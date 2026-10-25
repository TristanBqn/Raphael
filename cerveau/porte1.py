"""Porte 1 (hook UserPromptSubmit) : capture le message, annonce ce qui a été capitalisé, injecte les souvenirs utiles.

Ne bloque jamais la conversation : toute erreur est journalisée et le hook sort sans rien injecter.
"""
import json
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

if os.environ.get(config.GARDE):
    sys.exit(0)
config.flux_utf8()

from filtres import message_utilisateur  # noqa: E402
from journal import log  # noqa: E402
from masque import mask_secrets  # noqa: E402
import store  # noqa: E402
import tiroirs  # noqa: E402


FIABILITE = {"affirme": "dit par " + (config.PRENOM or "l'utilisateur"), "constate": "constaté", "deduit": "déduit, non confirmé"}
# « Discipline d'affirmation » : une mémoire est pertinente, jamais complète.
AFFIRMATION = ("L'absence d'un fait dans ces souvenirs ne prouve pas qu'il n'existe pas : dire « je n'ai pas trouvé » "
               "plutôt que « ça n'existe pas ».")


def formater(souvenirs):
    lignes = []
    for s in souvenirs:
        portee = "général" if s["portee"] == "global" else f"projet {s['projet']}"
        etiquettes = ([s["type"], portee] + ([FIABILITE[s["fiabilite"]]] if s.get("fiabilite") in FIABILITE else [])
                      + [time.strftime("noté le %d/%m/%Y", time.localtime(s["ts"]))])   # un fait peut avoir vieilli
        lignes.append(f"- [{', '.join(etiquettes)}] {s['texte']}")
    return "\n".join(lignes)


RETOUR = re.compile(r"^\s*(faux|inutile)\b\s*(\d+(?:\s*[,et ]+\s*\d+)*)?\s*[.!]*\s*$", re.I)
SEUIL_INUTILE = 3   # désactivé après 3 retours « inutile »


def traiter_retour(cx, data, prompt):
    """« faux » ou « inutile » (éventuellement suivi de numéros) juge les souvenirs injectés au message précédent.

    Renvoie le texte à afficher, ou None si le message n'est pas un retour. Le message n'est alors pas envoyé à Claude.
    """
    m = RETOUR.match(prompt)
    if not m:
        return None
    # Seulement si des souvenirs ont été injectés au message précédent de cette conversation : sinon « faux »
    # est une vraie réponse à Claude, qu'on laisse passer.
    precedent = cx.execute("SELECT prompt_id FROM echanges WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                           (data.get("session_id"),)).fetchone()
    dernier = cx.execute("SELECT prompt_id FROM injections WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                         (data.get("session_id"),)).fetchone()
    if not precedent or not dernier or dernier["prompt_id"] != precedent["prompt_id"]:
        return None
    ids = [r["souvenir_id"] for r in cx.execute(
        "SELECT souvenir_id FROM injections WHERE session_id = ? AND prompt_id = ? ORDER BY id",
        (data.get("session_id"), dernier["prompt_id"]))]
    if m.group(2):
        rangs = [int(x) for x in re.findall(r"\d+", m.group(2))]
        ids = [ids[r - 1] for r in rangs if 0 < r <= len(ids)]
    verdict, faits = m.group(1).lower(), []
    with cx:
        for sid in ids:
            s = cx.execute("SELECT texte, retours FROM souvenirs WHERE id = ?", (sid,)).fetchone()
            if s is None:
                continue
            retours = json.loads(s["retours"]) if s["retours"] else []
            retours.append({"verdict": verdict, "ts": time.time()})
            desactiver = verdict == "faux" or sum(r["verdict"] == "inutile" for r in retours) >= SEUIL_INUTILE
            cx.execute("UPDATE souvenirs SET retours = ?, actif = CASE WHEN ? THEN 0 ELSE actif END, maj = ? WHERE id = ?",
                       (json.dumps(retours), desactiver, time.time(), sid))
            faits.append(("🗑️ désactivé : " if desactiver else "noté inutile : ") + s["texte"])
    log("retour", verdict=verdict, souvenirs=ids)
    return "🧠 " + "\n".join(faits) if faits else "Numéro de souvenir introuvable."


def tiroirs_du_message(cx, prompt, precedents, projet, univers, vecteur):
    """Tiroirs ouverts d'office (toujours ouverts, dossier de travail, tiroirs nommés dans le message ou les messages
    précédents) et sujets proches par le sens que Jev doit confirmer.

    Seules les racines de l'univers courant sont permises (« toi », plus « perso » ou le client) : un client ne voit
    ni la sphère perso ni un autre client.
    """
    permises = {"toi", univers if univers in tiroirs.clients() else "perso"}
    a_ouvrir = [c for c in [tiroirs.tiroir_du_projet(cx, projet)]
                + tiroirs.mentionnes(cx, " ".join([prompt] + [e["user"] for e in precedents]))
                if c and c.split("/")[0] in permises]
    ouverts = tiroirs.toujours_ouverts(cx) | tiroirs.ouvrir(cx, a_ouvrir)
    # Sujets déjà entièrement ouverts : inutile de les faire confirmer par Jev.
    deja = {tiroirs.sujet(c) for c in ouverts if "/" in c and tiroirs.ouvrir(cx, [tiroirs.sujet(c)]) <= ouverts}
    proches = [c for c in tiroirs.proches(cx, vecteur, deja, config.TIROIRS_A_VERIFIER * 2)
               if c.split("/")[0] in permises][:config.TIROIRS_A_VERIFIER]
    return ouverts, proches


def rappeler(cx, prompt, projet, univers, precedents, vecteur):
    """Choix des souvenirs à injecter : tiroirs ouverts, candidats de ces tiroirs, puis tri final par Jev."""
    import decideur
    ouverts, proches = tiroirs_du_message(cx, prompt, precedents, projet, univers, vecteur)
    sous = {p: tiroirs.ouvrir(cx, [p]) - ouverts for p in proches}
    visibles = ouverts | set().union(*sous.values()) if sous else ouverts
    candidats = store.candidats_rappel(cx, prompt, projet, vecteur, univers, visibles)
    for c in candidats:
        c["verifier"] = next((i for i, p in enumerate(proches) if c.get("tiroir") in sous[p]), None)
    arbre = tiroirs.arbre(cx)
    a_verifier = [f"{p} : {arbre[p]['description'] or ''}" for p in proches]
    r = decideur.rappel(prompt, projet, candidats, precedents, a_verifier, projet_local=projet != "perso")
    r.update(candidats=candidats, ouverts=ouverts, proches=proches)
    return r


def main():
    t0 = time.perf_counter()
    data = json.load(sys.stdin)
    if config.exclu(data.get("cwd")):   # dossier exclu (config.EXCLUSIONS)
        return
    texte = message_utilisateur(data.get("prompt", ""))
    if texte is None:   # message d'agent, notification, contenu de skill : ni capture ni rappel
        log("porte1_ignore", debut=data.get("prompt", "")[:40])
        return
    prompt = mask_secrets(texte)
    projet = store.projet_de(data.get("cwd"))
    univers = config.univers_de(data.get("cwd"))
    cx = store.connexion()
    reponse_retour = traiter_retour(cx, data, prompt)
    if reponse_retour is not None:
        # Retour pur : on ne dérange pas Claude, le hook bloque le message et affiche le résultat.
        print(json.dumps({"decision": "block", "reason": reponse_retour}, ensure_ascii=False))
        return
    precedents = store.precedents(cx, data.get("session_id"))   # avant d'insérer ce message
    with cx:
        cx.execute("INSERT INTO echanges(ts, session_id, prompt_id, projet, cwd, univers, user_text, statut) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, 'en_cours')",
                   (time.time(), data.get("session_id"), data.get("prompt_id"), projet, data.get("cwd"), univers,
                    prompt))
        annonces, annonces_autres = store.annonces_a_montrer(cx, data.get("session_id"))

    try:
        from embeddings import vecteur_requete
        vecteur = vecteur_requete(prompt[:2000])
    except Exception:
        vecteur = None
        log("porte1_embeddings_indisponibles", trace=traceback.format_exc()[-300:])
    t_vec = round((time.perf_counter() - t0) * 1000)
    r = rappeler(cx, prompt, projet, univers, precedents, vecteur)
    besoin, retenus = r["besoin"], r["retenus"]
    inbox = store.chercher_inbox(cx, prompt, projet)

    message, contexte = [], []
    if annonces or annonces_autres:
        # Bornées : un gros lot ne doit ni noyer l'écran ni gonfler le contexte.
        items = annonces + [f"(autre conversation) {a}" for a in annonces_autres]
        reste = len(items) - 3
        message.append("🧠 Capitalisé :\n" + "\n".join(f"  · {a}" for a in items[:3])
                       + (f"\n  · … et {reste} autre(s)" if reste > 0 else ""))
        if annonces:
            contexte.append("Le second cerveau a enregistré depuis le dernier message : " + " ; ".join(annonces)[:1500])
    if retenus:   # en entier, un par ligne : on ne peut juger « utile » ou « inutile » que ce qu'on voit
        message.append(f"🔎 {len(retenus)} souvenir(s) injecté(s) (réponds « faux 2 » ou « inutile » pour corriger) :\n"
                       + "\n".join(f"  [{i}] {s['texte']}" for i, s in enumerate(retenus, 1)))
        contexte.append("Souvenirs du second cerveau de l'utilisateur, pertinents pour ce message "
                        "(à utiliser s'ils s'appliquent, sans les citer inutilement) :\n" + formater(retenus)
                        + "\n" + AFFIRMATION)
        with cx:
            for s in retenus:
                cx.execute("UPDATE souvenirs SET utilisations = utilisations + 1, dernier_usage = ? WHERE id = ?",
                           (time.time(), s["id"]))
                cx.execute("INSERT INTO injections(ts, session_id, prompt_id, souvenir_id) VALUES (?, ?, ?, ?)",
                           (time.time(), data.get("session_id"), data.get("prompt_id"), s["id"]))
    elif besoin is not None and besoin >= config.SEUIL_BESOIN_MEMOIRE:
        contexte.append("Le second cerveau n'a pas de souvenir pertinent pour ce message. " + AFFIRMATION)
    if inbox and (besoin or 0) >= config.SEUIL_BESOIN_MEMOIRE:
        contexte.append("Échanges récents pas encore consolidés en souvenirs, peut-être utiles :\n"
                        + "\n".join(f"- {e['user_text'][:300]}" for e in inbox))

    sortie = {}
    if message:
        sortie["systemMessage"] = "\n".join(message)
    if contexte:
        sortie["hookSpecificOutput"] = {"hookEventName": "UserPromptSubmit", "additionalContext": "\n\n".join(contexte)}
    if sortie:
        print(json.dumps(sortie, ensure_ascii=False))
    log("porte1", projet=projet, candidats=len(r["candidats"]), inbox=len(inbox), besoin=besoin, source=r["source"],
        univers=univers, projet_courant=r["projet_courant"], contexte=len(precedents),
        tiroirs=sorted({tiroirs.sujet(c) for c in r["ouverts"]}), proches=r["proches"],
        confirmes=[r["proches"][i] for i in r["tiroirs"]], notes=r["notes"],
        injectes=[s["id"] for s in retenus], annonces=len(annonces), ms_vecteur=t_vec,
        ms=round((time.perf_counter() - t0) * 1000))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("porte1_erreur", trace=traceback.format_exc()[-800:])
