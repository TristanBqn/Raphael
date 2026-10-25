# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Objet

« Second cerveau » personnel pour Claude Code : des hooks capturent chaque échange, Jev (API TypeSafe System One) décide quoi retenir et quoi rappeler, `claude -p` (Haiku) rédige les souvenirs, stockés en SQLite et réinjectés dans les conversations suivantes. Code, commentaires, identifiants et données en français ; Windows uniquement (`msvcrt`, `winreg`, drapeaux `CREATE_NO_WINDOW`).

## Environnement et commandes

- Python 3.14 dans `.venv` (dépendances : `requirements.txt`). Toujours lancer avec `.venv/Scripts/python.exe`.
- Clé API : `TYPESAFE_API_KEY` (variable d'environnement, sinon lue dans le registre `HKCU\Environment` par `decideur.cle_api()`).
- Pas de tests, linter ni build. Vérifications ponctuelles :
  - `spikes/test_jev.py` : teste la clé Jev et mesure la latence.
  - `cerveau/sante.py --sonde --afficher` : bilan de santé (Jev, service d'embeddings, base, contradictions).
  - Les hooks se déclarent dans `~/.claude/settings.json` (modèle : `exemples/settings.hooks.json`) : toute session Claude Code les déclenche, sauf dans `config.EXCLUSIONS`.
  - Import de l'historique Claude Code : `.venv/Scripts/python.exe cerveau/import_historique.py [--evaluer-seulement]`. Prend le verrou du worker (abandonne si un worker tourne), exclut les projets de `PROJETS_EXCLUS`, et tranche directement `a_ecrire`/`rejete` sans passer par `en_attente` (la « suite » = les deux messages utilisateur suivants).
- Les scripts de `outils/` utilisent des chemins relatifs (`../data/annotation/`) et s'importent entre eux : les lancer depuis `outils/`.
- Débogage : `data/cerveau/cerveau.log` (JSON lignes, un événement par ligne : `porte1`, `worker_evaluation`, `worker_redaction`, `*_erreur`…). Base : `data/cerveau/cerveau.db`. `SECOND_CERVEAU_DATA` permet de pointer vers un autre dossier de données.
- `data/`, `modeles/` (EmbeddingGemma-300M ONNX q8), `cerveau/config_local.py`, `.env` sont ignorés par git.

## Architecture (`cerveau/`)

Flux d'un échange, statut porté par `echanges.statut` :
`en_cours` → `a_evaluer` → (`en_attente`)* → `a_ecrire` | `rejete` → `ecrit` | `erreur`.

1. **`porte1.py`** (hook `UserPromptSubmit`, synchrone, latence critique) : masque les secrets, lit les `CONTEXTE_ECHANGES` (2) échanges précédents de la conversation (`store.precedents`, coupés à `CONTEXTE_CARACTERES`), insère l'échange `en_cours`, affiche les annonces du worker, calcule le vecteur de la requête, ouvre les tiroirs utiles (`tiroirs_du_message` : toujours ouverts, tiroir du dossier, tiroirs nommés par nom ou mot-clé, plus `TIROIRS_A_VERIFIER` sujets proches par le sens que Jev confirme), recherche hybride dans ces tiroirs (`store.candidats_rappel` : EmbeddingGemma + FTS5 fusionnés par RRF), puis tri final par Jev (`decideur.rappel`, un seul appel : `besoin`, `projet_courant` si le dossier est un projet, confirmation des tiroirs proches, pertinence de chaque candidat). Injection via `additionalContext` ; souvenirs et annonces affichés en entier, un par ligne. Le journal `porte1` garde les notes de chaque candidat pour mesurer. Les messages « faux [n] » / « inutile [n] » sont interceptés (`decision: block`) pour juger les souvenirs injectés au message précédent : « faux » désactive aussitôt, « inutile » après `SEUIL_INUTILE` (3) retours.
2. **`porte2.py`** (hook `Stop`, quelques ms) : ajoute la réponse de Claude, passe l'échange à `a_evaluer`, lance le worker. Aucun appel réseau ici.
3. **`fin_session.py`** (hook `SessionEnd`) : force la décision sur les échanges `en_attente` et récupère les messages interrompus.
4. **`worker.py`** (arrière-plan, un seul à la fois via verrou `msvcrt` sur `worker.lock`) : `evaluer` (grille Jev de `decideur.questions_capture` → `score_capture` composite ; `non_resolu` élevé ⇒ `en_attente`, réexaminé avec la suite de la conversation jusqu'à `MAX_ATTENTES` ; une demande explicite de mémoriser, `CAPTURE_EXPLICITE`, passe directement à `a_ecrire` sans Jev ni attente de lot), `rediger` (lot envoyé à `claude -p --model haiku` avec la `CONSIGNE`, les souvenirs proches, les échanges précédents (`avant`) et l'arbre des tiroirs ; JSON attendu, champ `remplace` pour désactiver un ancien souvenir, champ `tiroir` et liste `nouveaux_tiroirs`), `vectoriser`, puis `ranger_restants` (souvenirs sans tiroir, rangés par Haiku ou à défaut dans le tiroir de leur projet ou leur racine). Une annonce par souvenir et par tiroir créé. S'arrête quand l'inbox est vide (20 tours max).
5. **Embeddings** : `embeddings.py` calcule sur place ou interroge `service_embeddings.py` (HTTP 127.0.0.1:47811, garde le modèle en RAM, s'arrête après 30 min d'inactivité). `lanceur.py` démarre worker et service détachés (`CREATE_BREAKAWAY_FROM_JOB` pour survivre à la fermeture de Claude Code).
6. **`filtres.py`** : `message_utilisateur()` écarte ce que l'utilisateur n'a pas écrit (messages d'agents, notifications, contenus de skills, retours de hooks) et extrait l'objectif des `/goal`. Utilisé par la porte 1 et l'import.
7. **`demarrage.py`** (hook `SessionStart`) : affiche le dernier bilan de `sante.py` (`data/cerveau/sante.json`), relance `sante.py --sonde` (Jev, service, contradictions entre souvenirs proches) et démarre le service d'embeddings. `sante.py --sonde --afficher` donne le bilan à la main.
8. **Univers** : `config.UNIVERS` associe un motif de chemin à un univers (employeur, clients ; défaut `perso`). `souvenirs.univers` vide = commun. Le rappel ne voit que le commun et l'univers courant, en plus du filtre par tiroirs : depuis un dossier client, un souvenir perso reste invisible même si son tiroir est ouvert. `classer_univers.py` range dans un univers les souvenirs qui n'en ont pas (Jev, confiance ≥ 0,75 pour un univers client).
9. **`store.py`** : schéma SQLite (créé/migré à chaque `connexion()`, WAL), tables `echanges`, `souvenirs` (+ colonnes `embedding` BLOB float32×768 et `tiroir`), `tiroirs`, `annonces`, `injections`, index FTS5 synchronisés par triggers. `projet_de(cwd)` = nom de la racine git, `perso` pour le dossier personnel (toujours portée `global`).
10. **Tiroirs** (`tiroirs.py`) : arbre `racine/sujet/sous-sujet…` (racines `toi`, `perso` et une par univers client, `config.RACINES`). Le rédacteur descend l'arbre et range chaque souvenir dans le tiroir le plus profond qui correspond, ou crée un tiroir pour un sujet durable (`REGLES`) ; le code garantit l'unicité d'un sujet (`resoudre` : sans accents ni casse, un nom déjà présent renvoie vers son tiroir, les univers clients restent cloisonnés). Un projet local a son tiroir sous `perso` (colonne `tiroirs.projet`), un service sans dossier local va sous sa machine (`toi/<serveur>/<service>`), les outils sous `toi/Outils`. Ouvrir un tiroir ouvre ses parents et ses sous-tiroirs ; `TOUJOURS_OUVERTS` (`toi` seul) et `TOUJOURS_OUVERTS_AVEC_SOUS_TIROIRS` (`toi/Outils`).

`config.py` centralise les seuils, modèles et chemins : y faire les réglages plutôt que dans le code. Les réglages personnels (`PRENOM`, `SPHERE_PERSO`, `UNIVERS`, `UNIVERS_JEV`, `EXCLUSIONS`) vont dans `cerveau/config_local.py`, non versionné, qui surcharge `config.py` (modèle : `config_local.exemple.py`) ; les tables de `outils/refiltrer.py` sont dans `data/annotation/refiltrer_tables.json`. Exceptions existantes : `SEUIL_INUTILE` (`porte1.py`), `CONCURRENCE`, `LOT_IMPORT`, `PROJETS_EXCLUS` (`import_historique.py`).

## Invariants à respecter

- **Garde anti-récursion** : le worker pose `SECOND_CERVEAU_WORKER=1` ; chaque hook sort immédiatement si elle est présente, sinon les sessions `claude -p` du worker déclencheraient les hooks en boucle.
- **Un hook ne doit jamais casser la conversation** : tout `main()` est enveloppé dans un `try/except` qui journalise. `config.flux_utf8()` est obligatoire avant toute lecture ou sortie (cp1252 : les accents reçus arrivent en « Ã© » et un emoji fait planter le hook).
- **Masquer avant de stocker ou d'envoyer** : tout texte passe par `masque.mask_secrets` avant SQLite ou Jev.
- **Questions Jev en anglais, contenu en français** (Jev gère moins bien le français). Jev lit littéralement : les cas limites vont dans les `criteria`. Pas de calcul, comptage ni comparaison de dates côté Jev : c'est le code qui s'en charge.
- **Modèle Jev épinglé** (`MODELE_JEV = "jev-1.13.0"`) : les seuils sont réglés pour cette version ; changer de version impose de refaire l'évaluation.
- Porte 1 : repli local (heuristique sur les possessifs) si Jev dépasse `DELAI_JEV_PORTE1`.
- **Rédacteur sans outils** : `claude -p` est lancé avec `--tools "" --strict-mcp-config --no-session-persistence` (si les sessions tournent en mode `auto`, un contenu d'échange ne doit rien pouvoir faire exécuter). `remplace` n'agit que sur les souvenirs montrés au rédacteur.
- **Rédaction groupée** : pas d'appel Haiku pour moins de `LOT_MIN` (3) échanges, sauf si le plus vieux a plus de `ATTENTE_MAX_REDACTION` ou si sa session est dans `sessions_finies` (écrite par `fin_session.py`). Mesuré sur l'import : relever `SEUIL_CAPTURE` ferait perdre de vrais souvenirs (AUC 0,62), d'où le regroupement plutôt qu'un seuil plus strict.
- **Rappel de secours** (`decideur.rappel`) : si rien ne passe `SEUIL_PERTINENCE` mais que le besoin ≥ `SEUIL_BESOIN_FORT`, le candidat le plus proche par le sens (≥ `SIMILARITE_RATTRAPAGE`, Jev ≥ `PERTINENCE_RATTRAPAGE`) est injecté.
- **Purge** : `worker.purger` efface les textes bruts des échanges traités après `CONSERVATION_ECHANGES` (90 j) ; les souvenirs restent. L'index `echanges_fts` étant externe, retirer l'ancien texte avec la commande `'delete'` avant toute modification de `user_text`.
- **Mode projet** (`decideur.rappel`) : si `projet_courant` ≥ `SEUIL_PROJET_COURANT`, le message ne porte que sur le projet ouvert, dont les fichiers et git font foi : aucun fait n'est injecté (même du projet), seules les préférences et leçons de la racine `toi` passent, en pertinence forte. Une question sur ce qui avait été retenu (« où est l'archive que j'ai faite ? ») n'est pas en mode projet.
- **Rappel en trois voies** (`decideur.rappel`, hors mode projet) : normal (besoin ≥ 0,5 puis pertinence ≥ 0,35), pertinence forte (besoin faible mais un candidat ≥ 0,7 et similarité ≥ 0,4), rattrapage (besoin ≥ 0,75, Jev hésitant, le plus proche par le sens).
- **Exclusions** : `config.EXCLUSIONS` — les hooks n'y font rien (utile pour un dossier qui a déjà ses propres hooks de mémoire).
- **Fiabilité** des souvenirs (`affirme` / `constate` / `deduit`), affichée à l'injection, avec la règle d'affirmation : l'absence d'un souvenir ne prouve pas l'absence du fait.
- **Annonces par session** (`annonces.session_id`), bornées à 3 à l'affichage ; l'import n'annonce rien.
- **Tests : ne jamais laisser de faux faits** dans la base (un faux fait peut remplacer un vrai souvenir). Tester avec `SECOND_CERVEAU_DATA` pointé vers un dossier jetable.
- Ne mémoriser que ce que l'utilisateur a affirmé ou qu'un résultat a confirmé, jamais une simple déduction de Claude.
- **Règles d'un projet local non capturées** : elles relèvent du `CLAUDE.md` du projet, que Claude Code gère lui-même ; le cerveau n'y écrit jamais et n'y renvoie pas. Un fait sur le projet qui ne se lit pas dans ses fichiers (emplacement d'une archive) peut être retenu.

## Évaluation et réglage (`outils/`, `data/annotation/`)

Les seuils et la grille de capture viennent d'un jeu d'évaluation annoté à la main (données non versionnées) :
`historique.py` (lecture des transcripts `~/.claude/projects`, réutilisé par `import_historique.py`) → `generer_jeu_evaluation.py` (Word, tours identifiés `S12-T3`) → `annotation_docx.py export|apply|read` (surlignage jaune = à retenir, vert = rappel) → `refiltrer.py` (décisions G/P/R/D) → `jev_classer.py` (classement zero-shot par Jev, résultats dans `jev_resultats.json`). Annexes : `vue_condensee.py` (vue abrégée d'une session pour la pré-annotation), `spikes/docx_vers_pdf.ps1 -Docx … -Pdf …` (conversion via Word COM). Toute modification de questions ou de seuils dans `decideur.py` / `config.py` devrait être revalidée sur un tel jeu.

## Documentation Jev

`docs/notes-jev.md` résume les points de la documentation TypeSafe (https://docs.typesafe.ai) qui contraignent la conception. La consulter, avec la doc officielle, avant d'écrire une nouvelle question Jev.
