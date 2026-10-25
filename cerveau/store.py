"""Stockage SQLite : échanges capturés (l'inbox), souvenirs, annonces, journal des injections."""
import json
import os
import re
import sqlite3
import time

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS echanges (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    session_id TEXT, prompt_id TEXT, projet TEXT, cwd TEXT,
    user_text TEXT NOT NULL, assistant_text TEXT,
    statut TEXT NOT NULL DEFAULT 'en_cours',   -- en_cours, a_evaluer, en_attente, a_ecrire, ecrit, rejete
    score REAL, details TEXT, attentes INTEGER NOT NULL DEFAULT 0, maj REAL
);
CREATE INDEX IF NOT EXISTS echanges_statut ON echanges(statut);
CREATE INDEX IF NOT EXISTS echanges_prompt ON echanges(session_id, prompt_id);

CREATE TABLE IF NOT EXISTS souvenirs (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL, maj REAL,
    portee TEXT NOT NULL,          -- global ou projet
    projet TEXT,                   -- renseigné si portee = projet
    type TEXT NOT NULL,            -- fait, preference, lecon, decision_projet, evenement
    texte TEXT NOT NULL,
    expire TEXT,                   -- date AAAA-MM-JJ après laquelle le souvenir n'est plus injecté
    source_echange INTEGER,
    utilisations INTEGER NOT NULL DEFAULT 0, dernier_usage REAL,
    actif INTEGER NOT NULL DEFAULT 1,
    retours TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS souvenirs_fts USING fts5(
    texte, content='souvenirs', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS souvenirs_ai AFTER INSERT ON souvenirs BEGIN
    INSERT INTO souvenirs_fts(rowid, texte) VALUES (new.id, new.texte); END;
CREATE TRIGGER IF NOT EXISTS souvenirs_ad AFTER DELETE ON souvenirs BEGIN
    INSERT INTO souvenirs_fts(souvenirs_fts, rowid, texte) VALUES ('delete', old.id, old.texte); END;
CREATE TRIGGER IF NOT EXISTS souvenirs_au AFTER UPDATE OF texte ON souvenirs BEGIN
    INSERT INTO souvenirs_fts(souvenirs_fts, rowid, texte) VALUES ('delete', old.id, old.texte);
    INSERT INTO souvenirs_fts(rowid, texte) VALUES (new.id, new.texte); END;

CREATE VIRTUAL TABLE IF NOT EXISTS echanges_fts USING fts5(
    user_text, content='echanges', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS echanges_ai AFTER INSERT ON echanges BEGIN
    INSERT INTO echanges_fts(rowid, user_text) VALUES (new.id, new.user_text); END;

CREATE TABLE IF NOT EXISTS annonces (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, texte TEXT NOT NULL, montree INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions_finies (
    session_id TEXT PRIMARY KEY, ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS injections (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, session_id TEXT, prompt_id TEXT, souvenir_id INTEGER
);
CREATE TABLE IF NOT EXISTS tiroirs (
    chemin TEXT PRIMARY KEY,       -- racine/sujet/sous-sujet
    description TEXT, mots_cles TEXT,   -- mots_cles : liste JSON, pour reconnaître le sujet dans un message
    projet TEXT,                   -- dossier de projet local rattaché à ce tiroir (nom renvoyé par projet_de)
    ts REAL NOT NULL
);
"""

MOTS_VIDES = set("""
le la les un une des du de d l au aux et ou mais donc or ni car ce cet cette ces mon ma mes ton ta tes son sa ses
notre nos votre vos leur leurs je tu il elle on nous vous ils elles me te se moi toi lui y en ne pas plus que qui
quoi dont où est sont été être avoir ai as a avons avez ont fait faire faut peut pour par sur sous dans avec sans
chez vers entre comme tout tous toute toutes très bien aussi alors si oui non ça cela ceci c qu j m n s t
euh bah ok stp merci bonjour juste encore déjà même
the a an and or but of to in on at for with is are was be it this that you i we my your can do does
""".split())


CONTENEURS = {"documents", "downloads", "desktop", "bureau", "téléchargements", "onedrive"}


def connexion():
    config.assurer_dossier()
    cx = sqlite3.connect(config.BASE, timeout=5)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL")
    cx.executescript(SCHEMA)
    colonnes = {r[1] for r in cx.execute("PRAGMA table_info(souvenirs)")}
    if "embedding" not in colonnes:   # vecteur EmbeddingGemma (768 float32)
        cx.execute("ALTER TABLE souvenirs ADD COLUMN embedding BLOB")
    if "fiabilite" not in colonnes:   # affirme (dit par l'utilisateur), constate (résultat ou fichier), deduit
        cx.execute("ALTER TABLE souvenirs ADD COLUMN fiabilite TEXT")
    if "univers" not in colonnes:     # vide = commun à tous les univers
        cx.execute("ALTER TABLE souvenirs ADD COLUMN univers TEXT")
    if "tiroir" not in colonnes:      # chemin dans l'arbre des tiroirs (vide : pas encore rangé)
        cx.execute("ALTER TABLE souvenirs ADD COLUMN tiroir TEXT")
    if "univers" not in {r[1] for r in cx.execute("PRAGMA table_info(echanges)")}:
        cx.execute("ALTER TABLE echanges ADD COLUMN univers TEXT")
    if "session_id" not in {r[1] for r in cx.execute("PRAGMA table_info(annonces)")}:
        cx.execute("ALTER TABLE annonces ADD COLUMN session_id TEXT")
    return cx


def requete_fts(texte):
    """Transforme une phrase en requête FTS5 : mots porteurs, en préfixe, reliés par OR."""
    mots = [m for m in re.findall(r"[\w.\-]{3,}", texte.lower()) if m not in MOTS_VIDES]
    mots = list(dict.fromkeys(m.strip(".-") for m in mots if m.strip(".-")))[:20]
    return " OR ".join(f'"{m}"*' for m in mots)


def visibles(projet, univers, tiroirs=None, p=""):
    """Filtre SQL (et ses paramètres) des souvenirs que le rappel peut voir.

    Avec `tiroirs` : ceux des tiroirs ouverts, plus ceux pas encore rangés selon l'ancienne règle (portée et univers).
    L'univers reste un cloisonnement en plus des tiroirs : depuis un dossier client, un souvenir de la sphère perso
    reste invisible même si son tiroir (un service perso sous toi/VPS) est ouvert.
    `p` : préfixe de table dans la requête (« s. »).
    """
    univers = univers or config.UNIVERS_DEFAUT
    filtre = f"{p}actif = 1 AND ({p}expire IS NULL OR {p}expire >= ?) AND ({p}univers IS NULL OR {p}univers = ?)"
    params = [time.strftime("%Y-%m-%d"), univers]
    if tiroirs is None:
        return f"{filtre} AND ({p}portee = 'global' OR {p}projet = ?)", params + [projet]
    tiroirs = sorted(tiroirs)
    filtre += (f" AND ({p}tiroir IN ({','.join('?' * len(tiroirs))}) "
               f"OR ({p}tiroir IS NULL AND ({p}portee = 'global' OR {p}projet = ?)))")
    return filtre, params + tiroirs + [projet]


def chercher_souvenirs(cx, texte, projet, limite, univers=None, tiroirs=None):
    q = requete_fts(texte)
    if not q:
        return []
    filtre, params = visibles(projet, univers, tiroirs, "s.")
    return cx.execute(
        f"""SELECT s.*, bm25(souvenirs_fts) AS rang FROM souvenirs_fts JOIN souvenirs s ON s.id = souvenirs_fts.rowid
           WHERE souvenirs_fts MATCH ? AND {filtre} ORDER BY rang LIMIT ?""", [q] + params + [limite]).fetchall()


def candidats_rappel(cx, texte, projet, vecteur=None, univers=None, tiroirs=None):
    """Recherche hybride : par le sens (EmbeddingGemma) et par les mots (FTS5), fusionnées par
    rang réciproque (RRF). Jev fait ensuite le tri final. Sans vecteur, la recherche plein texte seule.
    `tiroirs` : limite la recherche aux tiroirs ouverts (None : ancienne règle de portée et d'univers)."""
    import numpy as np
    from embeddings import depuis_blob
    filtre, params = visibles(projet, univers, tiroirs)
    tous = {r["id"]: dict(r, similarite=None)
            for r in cx.execute(f"SELECT * FROM souvenirs WHERE {filtre}", params)}
    rangs = {}
    if vecteur is not None:
        avec = [r for r in tous.values() if r["embedding"]]
        if avec:
            sims = np.stack([depuis_blob(r["embedding"]) for r in avec]) @ vecteur
            ordre = [(avec[i]["id"], float(sims[i])) for i in np.argsort(-sims)]
            for rang, (sid, sim) in enumerate(ordre[:config.MAX_CANDIDATS * 2]):
                tous[sid]["similarite"] = sim
                if sim >= config.SIMILARITE_MIN:
                    rangs[sid] = rangs.get(sid, 0) + 1 / (config.K_RRF + rang)
    for rang, r in enumerate(chercher_souvenirs(cx, texte, projet, config.MAX_CANDIDATS * 2, univers, tiroirs)):
        rangs[r["id"]] = rangs.get(r["id"], 0) + 1 / (config.K_RRF + rang)
    meilleurs = sorted(rangs, key=lambda i: -rangs[i])[:config.MAX_CANDIDATS]
    return [tous[i] for i in meilleurs if i in tous]


def precedents(cx, session_id, avant_id=None, n=None):
    """Échanges précédents de la conversation, du plus récent au plus ancien, coupés : ils éclairent le message."""
    n = config.CONTEXTE_ECHANGES if n is None else n
    if not session_id or n <= 0:
        return []
    lignes = cx.execute("SELECT user_text, assistant_text FROM echanges WHERE session_id = ? AND id < ? "
                        "AND user_text != '[purgé]' ORDER BY id DESC LIMIT ?",
                        (session_id, avant_id if avant_id is not None else 1 << 62, n)).fetchall()
    c = config.CONTEXTE_CARACTERES
    return [{"user": r["user_text"][:c], "assistant": (r["assistant_text"] or "")[:c]} for r in lignes]


def chercher_inbox(cx, texte, projet, limite=3):
    """Échanges capturés mais pas encore rédigés : retrouvables avant même d'être écrits."""
    q = requete_fts(texte)
    if not q:
        return []
    return cx.execute(
        """SELECT e.* FROM echanges_fts JOIN echanges e ON e.id = echanges_fts.rowid
           WHERE echanges_fts MATCH ? AND e.statut IN ('en_attente', 'a_ecrire') AND (e.projet = ? OR ? = 'perso')
           ORDER BY bm25(echanges_fts) LIMIT ?""", (q, projet, projet, limite)).fetchall()


def annonces_a_montrer(cx, session_id):
    """Annonces de cette conversation, puis celles d'autres conversations (signalées comme telles)."""
    rows = cx.execute("SELECT id, texte, session_id FROM annonces WHERE montree = 0 ORDER BY id").fetchall()
    if rows:
        cx.execute(f"UPDATE annonces SET montree = 1 WHERE id IN ({','.join(str(r['id']) for r in rows)})")
    return ([r["texte"] for r in rows if r["session_id"] == session_id],
            [r["texte"] for r in rows if r["session_id"] != session_id])


def annoncer(cx, texte, session_id):
    cx.execute("INSERT INTO annonces(ts, texte, session_id) VALUES (?, ?, ?)", (time.time(), texte, session_id))


def details(row):
    return json.loads(row["details"]) if row["details"] else {}


def projet_de(cwd):
    """Nom du projet : la racine git si elle existe, sinon le dossier ; 'perso' pour le dossier personnel."""
    if not cwd:
        return "perso"
    chemin = os.path.abspath(cwd)
    if os.path.normcase(chemin) == os.path.normcase(config.DOSSIER_PERSO):
        return "perso"
    d = chemin
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return os.path.basename(d)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    # Documents, Téléchargements… ne sont pas des projets : on les traite comme le dossier personnel.
    if (os.path.normcase(os.path.dirname(chemin)) == os.path.normcase(config.DOSSIER_PERSO)
            and os.path.basename(chemin).lower() in CONTENEURS):
        return "perso"
    return os.path.basename(chemin)
