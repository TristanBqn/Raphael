"""Réglages du second cerveau : chemins, seuils, modèles. Tout ce qui se règle est ici."""
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DONNEES = os.environ.get("SECOND_CERVEAU_DATA", os.path.join(RACINE, "data", "cerveau"))
BASE = os.path.join(DONNEES, "cerveau.db")
VERROU_WORKER = os.path.join(DONNEES, "worker.lock")
JOURNAL = os.path.join(DONNEES, "cerveau.log")
PYTHON = os.path.join(RACINE, ".venv", "Scripts", "python.exe")

GARDE = "SECOND_CERVEAU_WORKER"   # posée sur le worker : ses propres sessions claude -p ne déclenchent rien
DOSSIER_PERSO = os.path.expanduser("~")

# Jev
MODELE_JEV = "jev-1.13.0"         # version épinglée : les seuils ci-dessous sont réglés pour elle
DELAI_JEV_PORTE1 = 1.5            # au-delà, la porte 1 se rabat sur la recherche locale seule
SEUIL_BESOIN_MEMOIRE = 0.5        # porte 1 : faut-il chercher dans la mémoire ?
SEUIL_PERTINENCE = 0.35           # porte 1 : injecter un souvenir en trop coûte peu, en rater un coûte une mauvaise réponse
SEUIL_CAPTURE = 0.25              # porte 2 : score composite au-dessus duquel on fait rédiger un souvenir
SEUIL_ATTENDRE = 0.6              # porte 2 : probabilité « problème pas encore résolu » qui fait attendre
MAX_ATTENTES = 3                  # nombre de réévaluations avant de trancher quand même

# Embeddings (EmbeddingGemma-300M, avec ses préfixes de tâche)
MODELE_EMBEDDINGS = os.path.join(RACINE, "modeles", "embeddinggemma-300m-ONNX")
PREFIXE_REQUETE = "task: search result | query: "
PREFIXE_DOCUMENT = "title: none | text: "
PORT_EMBEDDINGS = 47811           # service local qui garde le modèle en mémoire (127.0.0.1 uniquement)
VEILLE_SERVICE = 30 * 60          # le service s'arrête après 30 min sans requête pour libérer la RAM
DELAI_SERVICE = 2.0

# Rappel : recherche hybride sémantique + plein texte, fusionnée par rang (RRF), puis tri final par Jev
MAX_CANDIDATS = 12                # candidats proposés à Jev
K_RRF = 60                        # constante classique de la fusion par rang réciproque
SIMILARITE_MIN = 0.15             # en dessous, un souvenir n'est pas candidat par le sens
MAX_INJECTES = 5                  # souvenirs injectés au plus par message

# Rédaction des souvenirs (worker)
MODELE_REDACTION = "haiku"
LOT_REDACTION = 5                 # échanges rédigés ensemble par appel à claude -p
# Regroupement : la moitié des échanges retenus par Jev ne donnent aucun souvenir, et relever le seuil en perdrait
# de vrais (mesuré sur l'import). On attend donc d'avoir quelques échanges avant d'appeler Haiku.
LOT_MIN = 3                       # nombre d'échanges en attente qui déclenche une rédaction
ATTENTE_MAX_REDACTION = 10 * 60   # ... ou ancienneté du plus vieux (secondes) ; la fin de session force la rédaction

# Rappel de secours : Jev hésite sur un souvenir pourtant proche par le sens (« ma machine distante » → VPS)
SEUIL_BESOIN_FORT = 0.75          # l'utilisateur demande clairement quelque chose qui le concerne...
SIMILARITE_RATTRAPAGE = 0.3       # ... le meilleur candidat est proche par le sens...
PERTINENCE_RATTRAPAGE = 0.2       # ... et Jev ne l'exclut pas franchement : on l'injecte quand même

# Univers : un périmètre par employeur, client ou sphère. Un souvenir propre à un
# univers ne ressort que dans cet univers ; un souvenir « commun » (univers vide) ressort partout.
# Le premier motif trouvé dans le chemin du dossier de travail l'emporte ; sinon UNIVERS_DEFAUT.
UNIVERS = []                      # ex. [("onedrive - mon employeur", "Employeur"), ("\\client-a", "ClientA")]
UNIVERS_DEFAUT = "perso"

# Dossiers où les hooks du cerveau Jev ne font rien (un dossier qui a déjà ses propres hooks de mémoire, par exemple).
EXCLUSIONS = []                   # ex. [os.path.join(os.path.expanduser("~"), "AutreCerveau")]

# Pertinence forte : une question qui paraît générale (« comment je dois signer mes commits ? ») peut appeler un
# souvenir personnel. Si Jev juge un candidat très pertinent et qu'il est proche par le sens, on l'injecte quand même.
SEUIL_PERTINENCE_FORTE = 0.7
SIMILARITE_PERTINENCE_FORTE = 0.4

# Conservation : les textes bruts des échanges traités sont effacés après ce délai (les souvenirs restent)
CONSERVATION_ECHANGES = 90 * 86400

# Contexte : Jev (porte 1) et le rédacteur jugent le message à la lumière des échanges précédents de la conversation
CONTEXTE_ECHANGES = 2             # échanges précédents fournis
CONTEXTE_CARACTERES = 300         # coupés à cette longueur (message et réponse) : ils éclairent, ils ne décident pas

# Mode projet : le message ne porte que sur le projet ouvert. Ses fichiers et git font foi, donc aucun fait n'est
# injecté ; seules les préférences et leçons générales (racine « toi ») passent, en pertinence forte.
SEUIL_PROJET_COURANT = 0.5

# Tiroirs : les souvenirs sont rangés dans un arbre (racine/sujet/sous-sujet…), créé au fil de l'eau par le
# rédacteur. Le rappel n'ouvre que le tiroir du dossier, les tiroirs mentionnés et les tiroirs toujours ouverts ;
# ouvrir un tiroir ouvre aussi ses parents et ses sous-tiroirs.
RACINES = {"toi": "l'utilisateur lui-même quel que soit le contexte : préférences de travail, leçons générales, "
                  "comptes, ses machines (PC, serveurs…) et ce qui tourne dessus, ses outils installés (toi/Outils)",
           "perso": "ses projets personnels (ceux qui ont un dossier sur le PC) et sa vie personnelle"}
TOUJOURS_OUVERTS = ["toi"]                     # sans leurs sous-tiroirs (les machines s'ouvrent quand on en parle)
TOUJOURS_OUVERTS_AVEC_SOUS_TIROIRS = ["toi/Outils"]
TIROIRS_A_VERIFIER = 3            # tiroirs proches par le sens que Jev confirme (en plus des mots-clés)
SEUIL_TIROIR = 0.5                # Jev : le message concerne-t-il ce tiroir ?

# Capture forcée : une demande explicite de mémoriser est toujours rédigée, sans attendre la note de Jev
CAPTURE_EXPLICITE = (r"\b(souviens[- ]toi|rappelle[- ]toi|retiens|note que|n'oublie pas|mémorise|"
                     r"garde en mémoire|garde en tête)\b")

# Identité dans les consignes du rédacteur et à l'injection (vide : « l'utilisateur »)
PRENOM = ""
SPHERE_PERSO = "ses projets personnels"   # exemples de la sphère perso donnés au rédacteur

# Question Jev de classer_univers.py : une option par univers, plus « commun »
UNIVERS_JEV = {
    "instructions": "Which sphere of the user's life does `memory` belong to?",
    "criteria": {
        "commun": "About the user themselves whatever the context: their computers, network, accounts, servers, "
                  "tools, or general preferences on how answers and work should be done.",
        "perso": "Their personal sphere: side projects, their personal life.",
    },
}

# Réglages personnels (prénom, univers…) : config_local.py, non versionné (modèle : config_local.exemple.py)
try:
    from config_local import *  # noqa: E402,F401,F403
except ImportError:
    pass


def univers_de(cwd):
    chemin = (cwd or "").lower().replace("/", "\\")
    return next((nom for motif, nom in UNIVERS if motif in chemin), UNIVERS_DEFAUT)


def exclu(cwd):
    chemin = os.path.normcase(os.path.abspath(cwd or "."))
    return any(chemin == os.path.normcase(d) or chemin.startswith(os.path.normcase(d) + os.sep) for d in EXCLUSIONS)


def assurer_dossier():
    os.makedirs(DONNEES, exist_ok=True)


def flux_utf8():
    """Windows lit et écrit en cp1252 : sans ça, les accents envoyés par Claude Code arrivent en « Ã© »
    et un emoji dans la sortie fait planter le hook."""
    for flux in (sys.stdin, sys.stdout):
        try:
            flux.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
