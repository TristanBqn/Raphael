# Notes d'étude — documentation Jev (TypeSafe)

Étudiée le 16/10/2026. Source : https://docs.typesafe.ai (index : https://docs.typesafe.ai/llms.txt).

## L'essentiel

- **Endpoint unique** : `POST https://api.typesafe.ai/v1/systemone`, header `Authorization: Bearer $TYPESAFE_API_KEY`.
- **Requête** : `state` (texte, objet JSON ou tableau) + `questions` (map nommée) + `model`.
- **Trois types de questions texte** :
  - `Noul` : oui/non → probabilité de « oui » (0 à 1). Pas de `confidence` séparée.
  - `Choice` : une option parmi 255 max → `choice`, `probabilities`, `confidence`.
  - `Score` : niveaux ordonnés (2 à 10) → `score` pondéré, `probabilities`, `confidence`.
  - (`Box` existe pour les images, inutile ici.)
- **Toutes les questions d'une requête sont évaluées en parallèle** sur le même état : ajouter des questions ne rallonge presque pas la latence.
- **Modèles** : `jev-1.13.0` (= `jev-latest`) et `jev-1.14.0` (= `jev-preview`, sorti le 14/10/2026). **Épingler la version** quand les seuils sont réglés.
- **Contexte** : 64k tokens par requête, 32k par question.
- **Prix** : 0,042 $ / million de tokens en entrée, sortie gratuite.
- **SDK Python** : `typesafe-sdk` (installé, v0.7.5). Retries automatiques sur 429/5xx.

## Points qui changent notre conception

1. **Le français est moins bien géré que l'anglais.** La doc le dit explicitement. → Écrire les questions (instructions, criteria) **en anglais**, laisser l'état en français, et **tester sur un jeu d'évaluation** avant de faire confiance aux seuils.
2. **Il existe un cookbook « Simple memory system »** très proche de notre porte 2 : une question `Noul` « gate » décide si l'échange contient un fait durable ; seuil de départ 0,5. On s'en inspire directement.
3. **Lecture littérale** : Jev répond à la question écrite, pas à l'intention. Les cas limites doivent être dans les `criteria`.
4. **Pas de calcul, pas de comptage, pas de comparaison de dates** : tout ça reste dans notre code (nos statistiques locales tombent bien).
5. **État trop gros = baisse de précision** : filtrer avant d'envoyer (dernier tour seulement, pas tout le transcript).
6. **Ordre des options d'un Choice** : peut influencer la réponse → tester en réordonnant.
7. **Confidence** : seuils différents selon le risque. Pour « injecter un souvenir » (sans risque) seuil bas ; pour « écrire un souvenir » seuil plus haut.
8. **Les souvenirs peuvent renforcer une erreur** (mise en garde du cookbook) : ne jamais mémoriser la déduction du LLM seule, seulement ce que l'utilisateur ou un résultat d'outil a affirmé.

## Données

- Jev **n'est pas entraîné** sur les requêtes des clients.
- Zéro rétention (ZDR) réservé aux clients entreprise.
- Documents : Data Processing Agreement, Privacy Policy (https://docs.typesafe.ai, page Legal).

## Latence mesurée (PC Windows)

- Démarrage de Python + import du SDK : **~300 ms** à chaque appel de hook.
- + appel Jev (70–500 ms annoncés) → **~0,4 à 0,9 s par porte**. Acceptable ; si c'est trop, un petit service local résident supprimera les 300 ms.
