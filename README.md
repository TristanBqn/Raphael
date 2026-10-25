<p align="center">
  <img src="assets/raphael.png" alt="Raphael, Roi de la Sagesse : un slime bleu sur un cercle magique, entouré des messages de son second cerveau (Avis, Rapport, Réponse)" width="100%">
</p>

# Raphael — un second cerveau pour Claude Code

> **《Réponse》** Je retiens ce qui compte dans vos conversations, et je vous le rappelle avant même que vous ne le demandiez.

Raphael donne une mémoire à long terme à [Claude Code](https://claude.com/claude-code). C'est une **adaptation directe de [Kenjaku](https://github.com/tpierrain/kenjaku)**, le second cerveau de Thomas Pierrain, dont il reprend les principes et une bonne partie des mécanismes, réécrits en Python pour une autre façon de capturer et de rappeler.

Sa particularité : **la capture et le rappel sont déterministes**. Ce n'est pas le LLM qui décide seul de mémoriser (il oublie, ou retient n'importe quoi) : des hooks capturent chaque échange, et un modèle de décision spécialisé, Jev, tranche avec des probabilités que le code compare à des seuils fixes.

- **Jev** ([TypeSafe System One](https://docs.typesafe.ai)) décide : faut-il retenir cet échange ? ce message a-t-il besoin de la mémoire ? ce souvenir est-il pertinent ?
- **Claude Haiku** (`claude -p`) rédige les souvenirs en arrière-plan, sans jamais bloquer la conversation.
- **SQLite + FTS5 + EmbeddingGemma-300M** (sur la machine) stockent et retrouvent les souvenirs par les mots et par le sens.
- Les souvenirs sont rangés dans un **arbre de tiroirs** et cloisonnés par **univers** (perso, employeur, clients) : un fait d'un client ne ressort jamais chez un autre.

## Pourquoi « Raphael » ?

Dans *Moi, quand je me réincarne en Slime* (*Tensei Shitara Slime Datta Ken*), Raphael, le « Roi de la Sagesse », est la compétence qui vit dans la tête du héros : elle analyse tout ce qui se passe, garde tout en mémoire et répond aussitôt, par de courts messages **《Avis》**, **《Rapport》** ou **《Réponse》**.

C'est exactement le rôle de ce projet auprès de Claude : une voix intérieure qui analyse chaque échange, range ce qui mérite de l'être, et souffle la bonne information au bon moment. Le nom suit aussi la tradition de Kenjaku, baptisé d'après un personnage de *Jujutsu Kaisen* : à chacun son personnage d'anime.

## Ce que Raphael doit à Kenjaku

Rendons à César ce qui est à César. Raphael reprend de [Kenjaku](https://github.com/tpierrain/kenjaku) :

1. **Le principe directeur** : du déterminisme partout où c'est possible, avec des hooks déclenchés par de vrais événements plutôt que par la bonne volonté du modèle, et le LLM seulement là où son jugement apporte quelque chose. Raphael pousse ce principe jusqu'à la décision de mémoriser.
2. **Les univers** (ADR 0034 de Kenjaku) : un périmètre souple par employeur, client ou sphère de vie, pour qu'une information ne déborde pas de son contexte. Raphael déduit l'univers du dossier de travail et en fait les racines de son arbre de tiroirs.
3. **La discipline d'affirmation** : une absence n'est jamais générale. À chaque rappel, Raphael rappelle à Claude que l'absence d'un souvenir ne prouve pas l'absence du fait (« je n'ai pas trouvé » plutôt que « ça n'existe pas »).
4. **Les paliers de source** (`verbatim` > `conversation` > `human-summary` > `ai-summary`) et le garde-fou contre les résumés d'IA, devenus la **fiabilité** de chaque souvenir : *dit par vous*, *constaté* par un résultat, ou *déduit* ; et la règle de ne mémoriser que ce que vous avez affirmé ou qu'un résultat a confirmé.
5. **Le bilan de santé au démarrage** : comme le `session-health` de Kenjaku, Raphael affiche à chaque nouvelle session le dernier verdict connu pendant qu'une nouvelle sonde tourne en arrière-plan. La bannière elle-même est reprise de Kenjaku :
   ```
   🧠 Cerveau Jev · 142 souvenirs · univers perso · ✅ en forme
   ```
6. **Le lint déterministe** (`lint-vault` : liens morts, notes orphelines, pages périmées), transposé à une base de souvenirs : souvenirs sans vecteur, expirés, quasi-doublons, contradictions, jamais utilisés, jugés inutiles, échanges bloqués.
7. **EmbeddingGemma-300M en local** (ONNX quantifié), avec les mêmes préfixes de tâche (`task: search result | query: ` et `title: none | text: `).
8. **Un modèle d'embeddings gardé en mémoire** par un service local (le serveur MCP `vault-rag` de Kenjaku), plutôt que rechargé à chaque question.
9. **L'échec silencieux** (*fail-open*) : un hook qui plante journalise et se tait, il ne casse jamais la session.

Le code est réécrit en Python et adapté à SQLite : aucun fichier de Kenjaku n'est copié.

## Raphael et Kenjaku : deux philosophies

Adaptation directe ne veut pas dire copie : les deux projets ne répondent pas au même besoin.

- **Kenjaku est un lieu où l'on va** : un wiki LLM « à la Karpathy » (Markdown, compatible Obsidian, versionné dans git), alimenté par vos sources de travail (Slack, Drive, Gmail, Notion, transcriptions de réunions…). On ouvre son cerveau pour lui demander *« qu'a-t-on décidé sur le projet X, et qui s'en occupe ? »*.
- **Raphael est une présence qui vous suit** : une couche invisible dans *toutes* vos sessions Claude Code, quel que soit le dossier. Il apprend de vos conversations avec Claude (votre machine, vos comptes, vos préférences, les leçons tirées d'une erreur, les décisions de vos projets) et injecte de lui-même ce qui sert, au moment où vous écrivez.

| | **Kenjaku** | **Raphael** |
|---|---|---|
| **Usage** | On ouvre le dossier du cerveau (CLI ou Claude Desktop) pour l'interroger | Actif dans toutes les sessions Claude Code, sans rien ouvrir |
| **Ce qu'il retient** | Vos sources de travail : messages, documents, réunions, notes | Vos conversations avec Claude Code |
| **Qui décide de mémoriser** | Claude, qui rédige et range les notes du wiki, aidé de skills (`/file-back`, `/consolidate`, `/lint`) | Des hooks capturent chaque échange ; **Jev décide** (retenir, attendre la suite, rejeter) ; Haiku ne fait que rédiger |
| **Qui décide de rappeler** | Claude interroge le vault via le serveur MCP `vault-rag` | La porte 1 cherche et injecte d'office les souvenirs que Jev juge pertinents, **avant** que Claude ne réponde |
| **Stockage** | Notes Markdown + `[[wikilinks]]`, dans votre dépôt git (commit et push automatiques) | Base SQLite : souvenirs atomiques d'une phrase, datés, avec leur fiabilité et une date d'expiration éventuelle |
| **Recherche** | RAG local (EmbeddingGemma, ou une API, ou Ollama) sur un index vectoriel SQLite | Hybride EmbeddingGemma + plein texte FTS5, fusion par rang (RRF), puis tri final par Jev, limité aux tiroirs utiles |
| **Coût en contexte** | Une constitution `CLAUDE.engine.md` (environ 60 Ko) chargée à chaque session | Rien au démarrage ; quelques lignes injectées seulement quand un souvenir sert |
| **Correction** | On édite les notes, dans Obsidian ou ailleurs | On répond `faux 2` ou `inutile` au message suivant |
| **Pile** | Node.js ≥ 20, macOS et Windows, installateur guidé | Python 3.14, Windows uniquement |
| **Public visé** | Tout le monde, y compris sans profil technique | Utilisateurs de Claude Code à l'aise avec Python |
| **Maturité** | Versions publiées, moteur qui se met à jour seul, tests de mutation, ADR | Projet personnel, sans tests automatisés |

**Lequel choisir ?** Kenjaku si vous voulez un cerveau de travail qui digère vos outils et répond avec ses sources. Raphael si vous voulez que Claude Code se souvienne de vous d'une session à l'autre, sans y penser. Les deux peuvent cohabiter : ajoutez le dossier de Kenjaku à `EXCLUSIONS` dans `cerveau/config_local.py` pour que les deux cerveaux ne se superposent pas.

## Ce qui change vraiment

### 1. Jev : décider avec des probabilités, pas avec la bonne volonté d'un LLM

<p align="center">
  <img src="https://static.wikia.nocookie.net/tensei-shitara-slime-datta-ken/images/9/9f/Raphael_Abstract.png/revision/latest?cb=20210808130312" alt="Raphael, le Roi de la Sagesse, dans Moi, quand je me réincarne en Slime" width="420">
  <br><sub><i>Raphael, le Roi de la Sagesse. Image : <a href="https://tensei-shitara-slime-datta-ken.fandom.com/wiki/Raphael">wiki Fandom de Tensura</a>.</i></sub>
</p>

**Ce qu'est Jev.** Jev est un modèle *System One* de [TypeSafe](https://docs.typesafe.ai) : un petit modèle rapide qui n'écrit rien, il **répond à des questions typées** sur un état JSON.

- `Noul` : une question oui/non, qui renvoie la probabilité du « oui » (de 0 à 1) ;
- `Choice` : une option parmi plusieurs, avec la probabilité de chacune et une confiance ;
- `Score` : un niveau sur une échelle ordonnée.

Toutes les questions d'un appel sont évaluées en parallèle, en 150 à 250 ms environ, pour 0,042 $ par million de tokens en entrée. Les modèles System One sont entraînés à être **calibrés** : leurs probabilités sont optimisées pour refléter l'incertitude réelle, mesurée sur des groupes de prédictions (ce qui ne garantit pas chaque réponse prise isolément).

**Pourquoi c'est pertinent.** Demander à un LLM « faut-il retenir cet échange ? » donne une réponse en prose, qui varie d'une fois sur l'autre, et qu'on ne peut ni mesurer ni régler. Jev donne un **nombre**, et un nombre se compare à un seuil fixé dans le code, se mesure et se règle :

<p align="center">
  <img src="assets/raphael-jev.png" alt="Raphael analyse un échange : Jev donne une probabilité pour chaque critère (fait durable 0,91, préférence 0,12, leçon 0,08, simple consigne 0,05, détail isolé 0,10) ; le code calcule un score de 0,82, au-dessus du seuil de 0,25, et l'échange est retenu" width="100%">
</p>


- **La décision devient reproductible.** Les probabilités de Jev peuvent varier de quelques centièmes d'un appel à l'autre, mais la règle de décision, elle, est écrite dans `config.py`.
- **La grille de capture est mesurée.** Sur un jeu de 50 passages annotés à la main, une seule question « faut-il retenir ? » plafonnait à une AUC de 0,69 et se trompait plus souvent que « tout garder ». Découpée en 7 questions atomiques combinées par le code, la grille monte à 0,80 :
  ```
  positif   = max(fait, préférence, leçon, règle de projet, événement daté)
  exclusion = max(simple consigne pour la tâche en cours, détail isolé)
  score     = max(positif × (1 − exclusion), événement daté)   → retenu si score ≥ 0,25
  ```
- **Les seuils suivent le coût d'une erreur.** Injecter un souvenir en trop coûte quelques tokens ; en rater un coûte une mauvaise réponse. Le rappel a donc des seuils bas, la capture des seuils plus stricts.

| Décision | Question posée à Jev | Règle appliquée par le code |
|---|---|---|
| Retenir un échange | 5 critères positifs et 2 exclusions | score ≥ 0,25 |
| Attendre la suite | « Le problème est-il encore ouvert ? » | ≥ 0,6 : réexaminé avec la suite de la conversation, 3 fois au plus |
| Chercher dans la mémoire | « La réponse a-t-elle besoin d'informations sur vous ? » | ≥ 0,5 |
| Injecter un souvenir | « Ce souvenir aide-t-il à répondre ? » | ≥ 0,35, ou ≥ 0,7 si la question semble générale |
| Mode projet | « Le message ne porte-t-il que sur le projet ouvert ? » | ≥ 0,5 : seules les préférences et leçons générales passent |
| Ouvrir un tiroir proche | « Le message parle-t-il de ce sujet ? » | ≥ 0,5 |

Les questions sont écrites en anglais (Jev le gère mieux que le français) et le contenu reste en français. La version du modèle est épinglée (`jev-1.13.0`) : les seuils sont réglés pour elle.

**Et ensuite.** Toutes les décisions passent par un seul module, `cerveau/decideur.py`. Dans la continuité, **Jev sera remplacé par un modèle local comme Laya** : mêmes questions, seuils revalidés sur le jeu d'évaluation, et plus aucun échange envoyé à l'extérieur pour décider.

### 2. Le système des portes

Raphael s'accroche aux événements de Claude Code par quatre hooks. Les deux « portes » sont celles par lesquelles passe chaque échange.

```
Session ouverte ───────────► démarrage (SessionStart)
                              · bannière de santé, sonde en arrière-plan, préchauffage du modèle
Message de l'utilisateur ──► porte 1 (UserPromptSubmit) : le rappel, avant que Claude ne lise
                              · masque les secrets, enregistre l'échange
                              · ouvre les tiroirs utiles, recherche hybride (12 candidats au plus)
                              · un seul appel Jev → au plus 5 souvenirs injectés dans le contexte
Réponse de Claude ─────────► porte 2 (Stop) : la capture, en quelques millisecondes
                              · complète l'échange, le dépose dans l'inbox, réveille le worker
Worker (arrière-plan) ─────► Jev évalue l'échange : retenir, attendre la suite ou rejeter
                              · Haiku rédige les souvenirs par lots, puis vectorisation et rangement
Session fermée ────────────► fin de session (SessionEnd)
                              · tranche les échanges en attente, force la rédaction
```

**Porte 1, le rappel** (environ 0,65 s par message). En un seul appel, Jev dit si le message a besoin de la mémoire, s'il ne porte que sur le projet ouvert, quels tiroirs proches le concernent vraiment, et quels candidats sont pertinents. Trois voies d'injection : normale (besoin ≥ 0,5 puis pertinence ≥ 0,35), pertinence forte (une question qui paraît générale mais qu'un souvenir personnel change, comme « comment dois-je signer mes commits ? »), et rattrapage (le besoin est net, Jev hésite, le candidat le plus proche par le sens passe). Si Jev met plus de 1,5 s, une heuristique locale prend le relais. Les échanges capturés mais pas encore rédigés restent retrouvables.

**Porte 2, la capture.** Elle ne fait aucun appel réseau : elle ajoute la réponse de Claude à l'échange et réveille le worker, qui travaille en arrière-plan sans jamais bloquer la conversation.

**Le worker** (un seul à la fois) fait évaluer chaque échange par Jev. Un problème encore ouvert est mis **en attente**, puis réexaminé avec la suite de la conversation : on ne mémorise pas une erreur avant de savoir comment elle s'est résolue. Une demande explicite (« retiens que… », « souviens-toi… ») est toujours retenue. Haiku rédige par lots (3 échanges, 10 minutes ou la fin de la session), **sans aucun outil** : le contenu d'un échange ne peut rien faire exécuter. Un souvenir devenu faux est remplacé, et les textes bruts des échanges sont purgés après 90 jours.

**Vous gardez la main.** Dans Claude Code, Raphael se manifeste ainsi :

```
🧠 Capitalisé :
  · Le NAS de l'utilisateur est un Synology installé au bureau.
🔎 1 souvenir(s) injecté(s) (réponds « faux 2 » ou « inutile » pour corriger) :
  [1] Le NAS de l'utilisateur est un Synology installé au bureau.
```

Répondre `faux 2` désactive aussitôt le souvenir n° 2 ; `inutile` le note comme tel (désactivé au bout de 3). Ces messages sont interceptés par la porte 1 et n'arrivent jamais à Claude : 0 token.

### 3. Le classement : univers, projets et tiroirs

Kenjaku range des notes dans un wiki ; Raphael range des souvenirs d'une phrase, à trois niveaux.

**Les univers** (repris de Kenjaku) cloisonnent. Un motif dans le chemin du dossier de travail désigne l'univers (`cerveau/config_local.py`) : `perso` par défaut, un employeur, un client. Un souvenir sur vous-même (votre machine, vos préférences) est **commun** et ressort partout ; un souvenir d'univers ne ressort que dans cet univers. Depuis un dossier client, vous ne verrez ni votre vie perso ni un autre client.

**Les projets** suivent git. Le projet d'un échange est la racine git du dossier ; votre dossier personnel, Documents ou Téléchargements n'en sont pas. Un souvenir a une **portée** générale ou propre à un projet. Et quand un message ne porte que sur le projet ouvert (« corrige ce bug », « pousse sur GitHub »), Raphael passe en **mode projet** : ce sont les fichiers et git qui font foi, donc aucun fait mémorisé n'est injecté, seulement vos préférences et leçons générales. Les règles d'un projet relèvent de son `CLAUDE.md` et ne sont pas capturées ; un fait qui ne se lit pas dans ses fichiers (l'emplacement d'une archive, un hébergement) est retenu.

**Les tiroirs** organisent. Chaque souvenir est rangé dans un arbre :

```
toi/                    ← vous, quel que soit le contexte (toujours ouvert)
├── Outils/             ← vos logiciels installés (toujours ouvert)
├── PC/
└── Serveur/
    └── Agent/          ← un service sans dossier local va sous sa machine
perso/
├── MonProjet/          ← créé tout seul au premier souvenir du dossier ~/MonProjet
└── Cuisine/
ClientA/                ← un univers client, cloisonné
└── Audit 2026/
```

Haiku descend l'arbre et range chaque souvenir dans le tiroir le plus profond qui convient ; il ne crée un tiroir que pour un sujet durable, jamais pour une anecdote. Le code garantit qu'un sujet n'existe qu'à un seul endroit (un même nom, sans accents ni casse, renvoie au tiroir existant). Au rappel, Raphael n'ouvre que les tiroirs utiles : `toi` et `toi/Outils`, le tiroir du dossier courant, ceux que le message nomme (par leur nom ou un mot-clé), et jusqu'à 3 sujets proches par le sens que Jev doit confirmer. Ouvrir un tiroir ouvre ses parents et ses sous-tiroirs.

Chaque souvenir porte enfin un **type** (fait, préférence, leçon, décision de projet, événement daté avec sa date d'expiration) et une **fiabilité** (dit par vous, constaté, déduit), affichés à l'injection.

## Prérequis

- **Windows** uniquement (`msvcrt`, `winreg`, processus détachés).
- Python 3.14 (testé), Claude Code installé et connecté (`claude` dans le PATH).
- Une clé API TypeSafe (Jev).
- Environ 1,4 Go de RAM pour le service d'embeddings (il s'arrête seul après 30 min d'inactivité).

## Installation

```powershell
git clone https://github.com/TristanBqn/Raphael.git
cd Raphael
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Modèle d'embeddings (≈ 300 Mo, licence Gemma)
.venv\Scripts\hf.exe download onnx-community/embeddinggemma-300m-ONNX config.json tokenizer.json tokenizer_config.json onnx/model_quantized.onnx onnx/model_quantized.onnx_data --local-dir modeles/embeddinggemma-300m-ONNX

# Clé Jev (variable d'environnement utilisateur)
setx TYPESAFE_API_KEY "votre_cle"

# Vérification
.venv\Scripts\python.exe spikes\test_jev.py
```

Puis :

1. Copier `cerveau/config_local.exemple.py` en `cerveau/config_local.py` et l'adapter (prénom, univers, dossiers exclus).
2. Ajouter le contenu de `exemples/settings.hooks.json` dans `~/.claude/settings.json`, en remplaçant `C:/chemin/vers/Raphael` par le chemin réel.
3. Ouvrir une nouvelle session Claude Code : la bannière `🧠 Cerveau Jev · …` confirme que les hooks tournent.

Optionnel : importer l'historique Claude Code existant avec `.venv\Scripts\python.exe cerveau\import_historique.py` (`--evaluer-seulement` pour estimer d'abord le coût).

## Confidentialité

- Les secrets reconnus (clés, jetons, mots de passe) sont masqués avant tout stockage ou envoi (`cerveau/masque.py`) ; ce masquage reste heuristique.
- Le texte des échanges est **envoyé à l'API TypeSafe** (Jev) pour évaluation, et à Claude Haiku pour la rédaction des souvenirs.
- Tout le reste est local : base SQLite et journal dans `data/cerveau/` (ignoré par git), embeddings calculés sur la machine, service limité à `127.0.0.1`.
- Les textes bruts des échanges sont purgés après 90 jours ; seuls les souvenirs rédigés restent.

## Réglages et diagnostic

- Seuils, modèles et chemins : `cerveau/config.py` ; réglages personnels : `cerveau/config_local.py`.
- Bilan de santé : `.venv\Scripts\python.exe cerveau\sante.py --sonde --afficher`.
- Journal : `data/cerveau/cerveau.log` (une ligne JSON par événement).
- `SECOND_CERVEAU_DATA` permet d'utiliser un autre dossier de données (pratique pour tester sans toucher à la vraie base).

## Structure

| Dossier | Contenu |
|---|---|
| `cerveau/` | Hooks, worker, décisions Jev, stockage, embeddings, tiroirs |
| `outils/` | Chaîne d'évaluation : jeu Word annoté à partir de l'historique, classement par Jev |
| `spikes/` | Test de la clé Jev, conversion Word → PDF |
| `docs/` | Notes sur la documentation Jev |
| `exemples/` | Déclaration des hooks pour `~/.claude/settings.json` |
| `assets/` | Illustrations (sources SVG et rendus PNG) |

L'architecture détaillée et les invariants sont décrits dans [`CLAUDE.md`](CLAUDE.md).

## Crédits

- [Kenjaku](https://github.com/tpierrain/kenjaku), de Thomas Pierrain (Apache 2.0) : Raphael en est une adaptation directe (voir [Ce que Raphael doit à Kenjaku](#ce-que-raphael-doit-à-kenjaku)).
- [Jev](https://docs.typesafe.ai) (TypeSafe) pour les décisions, [EmbeddingGemma](https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX) (Google) pour les embeddings.
- *Moi, quand je me réincarne en Slime* (*Tensei Shitara Slime Datta Ken*) est l'œuvre de Fuse. Le nom de Raphael est un hommage de fan ; l'image de Raphael de la section Jev est tirée de l'anime (via le wiki Fandom de la série, droits réservés à leurs détenteurs) ; la bannière et le schéma d'analyse sont des créations originales. Ce projet n'est affilié ni à l'œuvre ni à ses éditeurs.
