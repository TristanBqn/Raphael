<p align="center">
  <img src="assets/raphael.png" alt="Raphael, Roi de la Sagesse : un slime bleu sur un cercle magique, entouré des messages de son second cerveau (Avis, Rapport, Réponse)" width="100%">
</p>

# Raphael — un second cerveau pour Claude Code

> **《Réponse》** Je retiens ce qui compte dans vos conversations, et je vous le rappelle avant même que vous ne le demandiez.

Raphael donne une mémoire à long terme à [Claude Code](https://claude.com/claude-code). Sa particularité : **la capture et le rappel sont déterministes**. Ce n'est pas le LLM qui décide seul de mémoriser (il oublie, ou retient n'importe quoi) : ce sont des hooks qui capturent chaque échange, et un modèle de décision spécialisé qui tranche.

- **Jev** ([TypeSafe System One](https://docs.typesafe.ai)) prend les décisions typées, avec des probabilités calibrées : faut-il retenir cet échange ? ce message a-t-il besoin de la mémoire ? ce souvenir est-il pertinent ?
- **Claude Haiku** (`claude -p`) rédige les souvenirs en arrière-plan, sans jamais bloquer la conversation.
- **SQLite + FTS5 + EmbeddingGemma-300M** (sur la machine) stockent et retrouvent les souvenirs par les mots et par le sens.
- Les souvenirs sont rangés dans un **arbre de tiroirs** (`toi/…`, `perso/…`, un tiroir par client) et cloisonnés par **univers** (perso, employeur, clients) : un fait d'un client ne ressort jamais chez un autre.

## Pourquoi « Raphael » ?

Dans *Moi, quand je me réincarne en Slime* (*Tensei Shitara Slime Datta Ken*), Raphael, le « Roi de la Sagesse », est la compétence qui vit dans la tête du héros : elle analyse tout ce qui se passe, garde tout en mémoire et répond aussitôt, par de courts messages **《Avis》**, **《Rapport》** ou **《Réponse》**.

C'est exactement le rôle de ce projet auprès de Claude : une voix intérieure qui analyse chaque échange, range ce qui mérite de l'être, et souffle la bonne information au bon moment. Le nom fait aussi écho à [Kenjaku](https://github.com/tpierrain/kenjaku), autre second cerveau pour Claude, baptisé d'après un personnage de *Jujutsu Kaisen* : à chacun son personnage d'anime.

## Raphael et Kenjaku : deux philosophies

[**Kenjaku**](https://github.com/tpierrain/kenjaku), de Thomas Pierrain, est un excellent second cerveau, et Raphael lui doit plusieurs idées. Les deux projets ne répondent pourtant pas au même besoin.

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

**Ce que Raphael reprend de Kenjaku**, réécrit en Python et adapté à SQLite :

- les **univers** : un périmètre par employeur, client ou sphère de vie, pour qu'un souvenir ne déborde pas de son contexte ;
- la **discipline d'affirmation** : l'absence d'un souvenir ne prouve pas l'absence du fait (« je n'ai pas trouvé » plutôt que « ça n'existe pas ») ;
- les **paliers de source**, devenus la **fiabilité** de chaque souvenir : *dit par vous*, *constaté* par un résultat, ou *déduit* ;
- le **bilan de santé** déterministe affiché au démarrage de chaque session ;
- le choix d'**EmbeddingGemma** en local (ONNX quantifié) pour la recherche par le sens.

**Lequel choisir ?** Kenjaku si vous voulez un cerveau de travail qui digère vos outils et répond avec ses sources. Raphael si vous voulez que Claude Code se souvienne de vous d'une session à l'autre, sans y penser. Les deux peuvent cohabiter : ajoutez le dossier de Kenjaku à `EXCLUSIONS` dans `cerveau/config_local.py` pour que les deux cerveaux ne se superposent pas.

## Fonctionnement

```
Message de l'utilisateur ──► porte 1 (UserPromptSubmit)
                              · masque les secrets, enregistre l'échange
                              · ouvre les tiroirs utiles, recherche hybride
                              · Jev trie → souvenirs injectés dans le contexte
Réponse de Claude ─────────► porte 2 (Stop)
                              · complète l'échange, réveille le worker
Worker (arrière-plan) ─────► Jev évalue l'échange (retenir / attendre / rejeter)
                              · Haiku rédige les souvenirs par lots
                              · calcul des vecteurs, rangement dans les tiroirs
Fin de session ────────────► force la décision sur les échanges en attente
```

Dans Claude Code, Raphael se manifeste ainsi :

```
🧠 Cerveau Jev · 142 souvenirs · univers perso · ✅ en forme

🧠 Capitalisé :
  · Le NAS de l'utilisateur est un Synology installé au bureau.
🔎 1 souvenir(s) injecté(s) (réponds « faux 2 » ou « inutile » pour corriger) :
  [1] Le NAS de l'utilisateur est un Synology installé au bureau.
```

Répondre `faux 2` désactive aussitôt le souvenir n° 2 ; `inutile` le note comme tel (désactivé au bout de 3). Une demande explicite (« retiens que… », « souviens-toi… ») est toujours mémorisée. Coût mesuré : environ 0,65 s par message pour la porte 1, et quelques centimes de Jev pour des centaines d'échanges.

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
| `assets/` | Illustration (source SVG et rendu PNG) |

L'architecture détaillée et les invariants sont décrits dans [`CLAUDE.md`](CLAUDE.md).

## Crédits

- [Kenjaku](https://github.com/tpierrain/kenjaku), de Thomas Pierrain (Apache 2.0), pour les idées citées plus haut. Aucun code n'en est repris.
- [Jev](https://docs.typesafe.ai) (TypeSafe) pour les décisions, [EmbeddingGemma](https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX) (Google) pour les embeddings.
- *Moi, quand je me réincarne en Slime* (*Tensei Shitara Slime Datta Ken*) est l'œuvre de Fuse. Le nom de Raphael est un hommage de fan ; l'illustration est une création originale, et ce projet n'est affilié ni à l'œuvre ni à ses éditeurs.
