"""Worker unique (verrou) : évalue l'inbox avec Jev, fait rédiger les souvenirs par claude -p, annonce le résultat.

Lancé par les hooks, en arrière-plan. Un seul worker à la fois ; il s'arrête quand l'inbox est vide.
"""
import json
import msvcrt
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import decideur  # noqa: E402
import store  # noqa: E402
import tiroirs  # noqa: E402
from journal import log  # noqa: E402

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

CONSIGNE = """Tu es le rédacteur du second cerveau personnel de l'utilisateur{nom}. On te donne des échanges
récents entre lui et Claude. Pour chacun, écris de 0 à 3 souvenirs, seulement s'ils restent vrais et utiles dans une
AUTRE conversation future.

À retenir :
- un fait durable sur lui ou son environnement (matériel, réseau, comptes, serveurs, outils, emplacement d'un projet) ;
- une préférence générale sur la façon de répondre ou de travailler, valable quel que soit le sujet ;
- une leçon technique réutilisable née d'une erreur (ce qui ne marche pas, ce qui a fini par marcher) ;
- une décision ou une règle durable d'un projet ;
- un événement personnel daté (déplacement, rendez-vous, échéance) : mets alors sa date d'expiration.

À NE PAS retenir :
- une consigne qui ne vaut que pour la tâche en cours (« audite ta réponse », « pas de sous-agent ici », « fais une liste ») ;
- ce qui est au futur ou hypothétique, sauf un événement personnel daté ;
- un détail isolé (nom de fichier vu en passant, version, état d'avancement) ;
- ce que Claude a seulement déduit ou supposé : ne retiens que ce que l'utilisateur a affirmé ou qu'un résultat a confirmé ;
- un secret (mot de passe, clé, jeton) ;
- une règle ou une décision propre à un projet qui a un dossier sur le PC (champ "tiroir_projet" renseigné) : elle
  relève du CLAUDE.md de ce projet, que Claude Code gère lui-même. Un fait sur ce projet qui ne se lit pas dans ses
  fichiers (emplacement d'une archive, hébergement) peut en revanche être retenu.

Si l'utilisateur demande explicitement de retenir quelque chose (« souviens-toi », « retiens », « note que »,
« n'oublie pas »), écris-le, sauf si un souvenir existant le dit déjà.

Écris chaque souvenir en une phrase autonome, en français, compréhensible sans l'échange, avec les noms propres utiles.

Fiabilité (champ "fiabilite") : "affirme" si {prenom} l'a dit lui-même ; "constate" si un résultat d'outil, un fichier
ou une commande l'a montré ; "deduit" seulement si c'est une conclusion de Claude non confirmée (à éviter : n'écris un
souvenir déduit que s'il est vraiment utile).

Univers (champ "univers") : "commun" pour ce qui concerne {prenom} lui-même quel que soit le contexte (ses machines,
comptes, réseau, outils, préférences générales de travail) ; "courant" pour ce qui appartient à l'univers de l'échange
(indiqué dans "univers" : son employeur, un client, ou sa sphère perso comme {perso}). Dans le doute, "courant".
Si un souvenir existant ci-dessous dit déjà la même chose, n'écris rien. S'il devient faux, écris le nouveau et
indique l'identifiant de l'ancien dans "remplace".

Nous sommes le {date}. Chaque échange porte sa propre date ("date") : calcule les dates relatives (« demain »,
« lundi prochain ») à partir de la date de l'échange, pas d'aujourd'hui. Les échanges sont dans l'ordre
chronologique : un fait plus récent l'emporte sur un plus ancien. Projet de chaque échange : indiqué dans "projet".
Le champ "avant" donne les échanges précédents de la même conversation (du plus récent au plus ancien) : il aide à
comprendre de quoi parle l'échange, mais n'en tire pas de souvenir.

{regles}

Réponds UNIQUEMENT avec ce JSON, sans texte autour :
{{"souvenirs": [{{"echange": <id>, "texte": "...", "type": "fait|preference|lecon|decision_projet|evenement",
"portee": "global|projet", "fiabilite": "affirme|constate|deduit", "univers": "commun|courant",
"expire": "AAAA-MM-JJ ou null", "remplace": <id ou null>, "tiroir": "racine/…"}}],
"nouveaux_tiroirs": [{{"chemin": "racine/…/nom", "description": "une ligne", "mots_cles": ["…"]}}]}}

Souvenirs existants proches :
{existants}

Échanges :
{echanges}
"""


def verrou():
    """Verrou système : libéré automatiquement si le worker meurt. None si un autre worker tourne déjà."""
    config.assurer_dossier()
    fh = open(config.VERROU_WORKER, "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh
    except OSError:
        fh.close()
        return None


def evaluer(cx, echecs):
    """Passe les échanges à évaluer (et les attentes à réexaminer) dans la grille Jev.

    `echecs` : échanges déjà en erreur pendant ce passage, qu'on ne retente pas avant le prochain worker.
    """
    with cx:   # message resté sans réponse (session plantée) : on l'évalue au bout d'une heure
        cx.execute("UPDATE echanges SET statut = 'a_evaluer' WHERE statut = 'en_cours' AND ts < ?",
                   (time.time() - 3600,))
    lignes = cx.execute("SELECT * FROM echanges WHERE statut = 'a_evaluer' ORDER BY id").fetchall()
    attentes = cx.execute(
        """SELECT e.* FROM echanges e WHERE e.statut = 'en_attente' AND (e.attentes >= ? OR e.maj < ? OR EXISTS (
               SELECT 1 FROM echanges f WHERE f.session_id = e.session_id AND f.id > e.id
               AND f.statut NOT IN ('en_cours', 'a_evaluer') AND f.maj > e.maj))""",
        (config.MAX_ATTENTES, time.time() - 86400)).fetchall()
    a_traiter = [e for e in list(lignes) + list(attentes) if e["id"] not in echecs]
    for e in a_traiter:
        if re.search(config.CAPTURE_EXPLICITE, e["user_text"], re.I):
            # Demande explicite de mémoriser : toujours rédigée, sans attendre la note de Jev ni le lot.
            with cx:
                cx.execute("UPDATE echanges SET statut = 'a_ecrire', details = ?, maj = ? WHERE id = ?",
                           (json.dumps({"force": True}), time.time(), e["id"]))
            log("worker_evaluation", echange=e["id"], statut="a_ecrire", force=True)
            continue
        user, assistant = e["user_text"], e["assistant_text"] or ""
        if e["statut"] == "en_attente":
            # On réexamine avec la suite de la conversation : le problème est peut-être résolu.
            suite = cx.execute("SELECT user_text, assistant_text FROM echanges WHERE session_id = ? AND id > ? "
                               "ORDER BY id LIMIT 3", (e["session_id"], e["id"])).fetchall()
            for s in suite:
                user += "\n[suite] " + s["user_text"]
                assistant += "\n[suite] " + (s["assistant_text"] or "")
        try:
            ev = decideur.evaluer_capture(user, assistant, e["projet"])
        except Exception:
            log("worker_jev_erreur", echange=e["id"], trace=traceback.format_exc()[-400:])
            echecs.add(e["id"])
            continue
        n = ev["nouls"]
        if ev["score"] < config.SEUIL_CAPTURE:
            statut = "rejete"
        elif (n["non_resolu"] >= config.SEUIL_ATTENDRE and e["attentes"] < config.MAX_ATTENTES
              and (e["maj"] or e["ts"]) > time.time() - 86400):   # au-delà d'un jour d'attente, on tranche
            statut = "en_attente"
        else:
            statut = "a_ecrire"
        with cx:
            cx.execute("UPDATE echanges SET statut = ?, score = ?, details = ?, attentes = attentes + ?, maj = ? "
                       "WHERE id = ?", (statut, ev["score"], json.dumps(ev), 1 if statut == "en_attente" else 0,
                                        time.time(), e["id"]))
        log("worker_evaluation", echange=e["id"], statut=statut, score=round(ev["score"], 3),
            portee=ev["portee"], nouls={k: round(v, 2) for k, v in n.items()})
    return len([e for e in a_traiter if e["id"] not in echecs])


def univers_echange(e):
    return e["univers"] or config.univers_de(e["cwd"])


def rediger(cx, taille_lot=None, annoncer=True, forcer=False):
    lot = cx.execute("SELECT * FROM echanges WHERE statut = 'a_ecrire' ORDER BY ts, id LIMIT ?",
                     (taille_lot or config.LOT_REDACTION,)).fetchall()
    if not lot:
        return 0
    # Pas d'appel Haiku pour un seul échange : on attend un petit lot, sauf s'il traîne ou si une session s'est
    # terminée (fin_session demande alors une rédaction forcée).
    finies = {r[0] for r in cx.execute("SELECT session_id FROM sessions_finies")}
    if (not forcer and len(lot) < config.LOT_MIN and not any(e["session_id"] in finies for e in lot)
            and not any(store.details(e).get("force") for e in lot)
            and min(e["maj"] or e["ts"] for e in lot) > time.time() - config.ATTENTE_MAX_REDACTION):
        return 0
    existants = {}
    for e in lot:
        texte = e["user_text"] + " " + (e["assistant_text"] or "")[:500]
        try:
            import embeddings
            vecteur = embeddings.calculer([texte[:2000]], "requete")[0]
        except Exception:
            vecteur = None
        for s in store.candidats_rappel(cx, texte, e["projet"], vecteur, univers_echange(e))[:6]:
            existants[s["id"]] = s
    maintenant = time.localtime()
    date = f"{JOURS[maintenant.tm_wday]} {time.strftime('%d/%m/%Y', maintenant)}"
    with cx:
        tiroirs.assurer_racines(cx)
        projets, nouveaux_tiroirs = {}, []
        for e in lot:   # le tiroir d'un dossier de projet se crée tout seul, à son premier échange rédigé
            projets[e["id"]], crees = tiroirs.assurer_tiroir_projet(cx, e["projet"], univers_echange(e))
            nouveaux_tiroirs += crees
    echanges = "\n\n".join(
        json.dumps({"id": e["id"], "date": time.strftime("%d/%m/%Y", time.localtime(e["ts"])), "projet": e["projet"],
                    "univers": univers_echange(e), "tiroir_projet": projets[e["id"]],
                    "portee_suggeree": store.details(e).get("portee"),
                    "avant": store.precedents(cx, e["session_id"], e["id"]),
                    "utilisateur": e["user_text"][:2500], "claude": (e["assistant_text"] or "")[:2500]},
                   ensure_ascii=False) for e in lot)
    prompt = CONSIGNE.format(
        nom=f" ({config.PRENOM})" if config.PRENOM else "", prenom=config.PRENOM or "l'utilisateur",
        perso=config.SPHERE_PERSO, date=date, echanges=echanges, regles=tiroirs.regles(cx),
        existants="\n".join(f"- [{s['id']}] {s['texte']}" for s in existants.values()) or "(aucun)")
    t0 = time.perf_counter()
    r = haiku(prompt)
    brut = r.stdout.strip()
    try:
        reponse = json.loads(brut[brut.index("{"): brut.rindex("}") + 1])
        souvenirs = reponse["souvenirs"]
    except (ValueError, KeyError):
        log("worker_redaction_illisible", code=r.returncode, sortie=brut[:500], erreur=r.stderr[:300])
        with cx:   # pas de nouvel essai automatique : on le saurait par le journal, sans boucle de réessais
            cx.execute(f"UPDATE echanges SET statut = 'erreur', maj = ? WHERE id IN ({','.join(str(e['id']) for e in lot)})",
                       (time.time(),))
        return 0
    ids = {e["id"]: e for e in lot}
    annonces = {}
    with cx:
        nouveaux_tiroirs += creer_tiroirs(cx, reponse.get("nouveaux_tiroirs"))
        for s in souvenirs:
            e = ids.get(s.get("echange"))
            if not e or not s.get("texte"):
                continue
            # Le dossier personnel n'est pas un projet : ce qui s'y dit vaut partout.
            portee = "projet" if s.get("portee") == "projet" and e["projet"] != "perso" else "global"
            expire = s.get("expire") if s.get("expire") not in (None, "null", "") else None
            if expire and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(expire)):
                expire = None
            fiabilite = s.get("fiabilite") if s.get("fiabilite") in ("affirme", "constate", "deduit") else None
            univers = None if s.get("univers") == "commun" else univers_echange(e)
            tiroir, crees = placer(cx, s.get("tiroir"), univers_echange(e))
            nouveaux_tiroirs += crees
            cx.execute("INSERT INTO souvenirs(ts, portee, projet, type, texte, expire, source_echange, fiabilite, "
                       "univers, tiroir) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (time.time(), portee, e["projet"] if portee == "projet" else None,
                        s.get("type") or "fait", s["texte"].strip(), expire, e["id"], fiabilite, univers, tiroir))
            # Remplacement limité aux souvenirs montrés au rédacteur : un identifiant inventé ne désactive rien.
            if isinstance(s.get("remplace"), int) and s["remplace"] in existants:
                cx.execute("UPDATE souvenirs SET actif = 0, maj = ? WHERE id = ?", (time.time(), s["remplace"]))
            annonces.setdefault(e["session_id"], []).append(s["texte"].strip())
        cx.execute(f"UPDATE echanges SET statut = 'ecrit', maj = ? WHERE id IN ({','.join(str(i) for i in ids)})",
                   (time.time(),))
        if annoncer:   # une annonce par souvenir et par tiroir créé, en entier : l'affichage choisit ce qu'il montre
            for session_id, textes in annonces.items():
                for texte in textes:
                    store.annoncer(cx, texte, session_id)
            session = lot[0]["session_id"]
            for chemin in dict.fromkeys(nouveaux_tiroirs):
                store.annoncer(cx, f"📁 nouveau tiroir : {chemin}", session)
    log("worker_redaction", echanges=list(ids), souvenirs=sum(len(v) for v in annonces.values()),
        tiroirs_crees=nouveaux_tiroirs, s=round(time.perf_counter() - t0, 1))
    return len(lot)


def haiku(prompt):
    """Appel au rédacteur. Sans outil ni MCP, et sans transcript : le contenu des échanges ne peut rien faire
    exécuter (les sessions de l'utilisateur sont en mode auto), et ces rédactions ne polluent pas l'historique."""
    return subprocess.run([shutil.which("claude"), "-p", "--model", config.MODELE_REDACTION, "--output-format", "text",
                           "--tools", "", "--strict-mcp-config", "--no-session-persistence"],
                          input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=240,
                          cwd=config.DONNEES, creationflags=subprocess.CREATE_NO_WINDOW)


def creer_tiroirs(cx, nouveaux):
    """Tiroirs proposés par le rédacteur (chemin, description, mots-clés), passés par l'anti-doublon."""
    crees = []
    for n in nouveaux or []:
        if isinstance(n, dict) and n.get("chemin"):
            crees += tiroirs.resoudre(cx, n["chemin"], n.get("description"), n.get("mots_cles"))[1]
    return crees


def placer(cx, chemin, univers):
    """Tiroir final d'un souvenir. Dans un univers client, ce qui n'est pas « toi » reste chez le client."""
    if not chemin:
        return None, []
    racine = str(chemin).split("/", 1)[0].strip()
    if univers in tiroirs.clients() and tiroirs.norme(racine) not in (tiroirs.norme("toi"), tiroirs.norme(univers)):
        chemin = univers + "/" + str(chemin).split("/", 1)[-1] if "/" in str(chemin) else univers
    return tiroirs.resoudre(cx, chemin)


RANGEMENT = """Tu ranges des souvenirs du second cerveau de l'utilisateur dans son arbre de tiroirs.

{regles}

Réponds UNIQUEMENT avec ce JSON :
{{"nouveaux_tiroirs": [{{"chemin": "racine/…/nom", "description": "une ligne", "mots_cles": ["…"]}}],
"rangements": [{{"id": <id>, "tiroir": "racine/…"}}]}}

Souvenirs (le champ "tiroir_projet" indique le tiroir du dossier de projet d'où vient le souvenir) :
{souvenirs}
"""


def ranger_restants(cx, lot=12):
    """Range les souvenirs actifs sans tiroir (rédaction sans tiroir valable, ou souvenirs antérieurs)."""
    restants = cx.execute("SELECT * FROM souvenirs WHERE actif = 1 AND tiroir IS NULL ORDER BY id LIMIT ?",
                          (lot,)).fetchall()
    if not restants:
        return 0
    with cx:
        tiroirs.assurer_racines(cx)
        items = "\n".join(json.dumps({"id": s["id"], "type": s["type"], "texte": s["texte"],
                                      "tiroir_projet": tiroirs.tiroir_du_projet(cx, s["projet"])},
                                     ensure_ascii=False) for s in restants)
    r = haiku(RANGEMENT.format(regles=tiroirs.regles(cx), souvenirs=items))
    brut = r.stdout.strip()
    try:
        reponse = json.loads(brut[brut.index("{"): brut.rindex("}") + 1])
    except ValueError:
        log("worker_rangement_illisible", code=r.returncode, sortie=brut[:500], erreur=r.stderr[:300])
        return 0
    places = {s["id"]: s for s in restants}
    crees, ranges = [], 0
    with cx:
        crees += creer_tiroirs(cx, reponse.get("nouveaux_tiroirs"))
        for g in reponse.get("rangements") or []:
            s = places.get(g.get("id")) if isinstance(g, dict) else None
            if not s:
                continue
            chemin, c = placer(cx, g.get("tiroir"), s["univers"])
            if chemin:
                cx.execute("UPDATE souvenirs SET tiroir = ? WHERE id = ?", (chemin, s["id"]))
                crees += c
                ranges += 1
                places.pop(s["id"])
        for s in places.values():   # oubliés par Haiku : rangés par défaut plutôt que réessayés à chaque passage
            defaut = tiroirs.tiroir_du_projet(cx, s["projet"]) or (s["univers"] if s["univers"] in tiroirs.clients()
                                                                   else "toi" if s["univers"] is None else "perso")
            cx.execute("UPDATE souvenirs SET tiroir = ? WHERE id = ?", (defaut, s["id"]))
    log("worker_rangement", souvenirs=ranges, par_defaut=[s["id"] for s in places.values()], tiroirs_crees=crees)
    return ranges


def purger(cx):
    """Efface les textes bruts des échanges traités depuis longtemps ; les souvenirs, eux, restent."""
    vieux = cx.execute("SELECT id, user_text FROM echanges WHERE statut IN ('ecrit', 'rejete', 'erreur') "
                       "AND ts < ? AND user_text != '[purgé]'", (time.time() - config.CONSERVATION_ECHANGES,)).fetchall()
    if not vieux:
        return
    with cx:
        for e in vieux:   # l'index plein texte est externe : il faut lui retirer l'ancien texte explicitement
            cx.execute("INSERT INTO echanges_fts(echanges_fts, rowid, user_text) VALUES ('delete', ?, ?)",
                       (e["id"], e["user_text"]))
        cx.execute(f"UPDATE echanges SET user_text = '[purgé]', assistant_text = NULL "
                   f"WHERE id IN ({','.join(str(e['id']) for e in vieux)})")
    log("worker_purge", echanges=len(vieux))


def vectoriser(cx):
    """Calcule le vecteur EmbeddingGemma des souvenirs qui n'en ont pas encore (nouveaux ou antérieurs)."""
    lignes = cx.execute("SELECT id, texte FROM souvenirs WHERE embedding IS NULL AND actif = 1").fetchall()
    if not lignes:
        return 0
    import embeddings
    vecteurs = embeddings.calculer([r["texte"] for r in lignes], "document")
    with cx:
        for r, v in zip(lignes, vecteurs):
            cx.execute("UPDATE souvenirs SET embedding = ? WHERE id = ?", (embeddings.vers_blob(v), r["id"]))
    log("worker_vectorisation", souvenirs=len(lignes))
    return len(lignes)


def main():
    fh = verrou()
    if fh is None:
        log("worker_deja_actif")
        return
    log("worker_debut", pid=os.getpid())
    cx = store.connexion()
    echecs = set()
    forcer = "--forcer" in sys.argv
    try:
        for _ in range(20):   # garde-fou : jamais de boucle infinie
            time.sleep(1)     # laisse le temps à d'autres échanges d'arriver pour les traiter ensemble
            fait = evaluer(cx, echecs) + rediger(cx, forcer=forcer)
            vectoriser(cx)
            if fait == 0:
                break
        while ranger_restants(cx):   # chaque passage range ou place par défaut tout son lot : la boucle finit
            pass
        purger(cx)
    finally:
        log("worker_fin")
        fh.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("worker_erreur", trace=traceback.format_exc()[-800:])
