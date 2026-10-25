"""Vue condensée d'une session exportée, pour la pré-annotation.

Messages de l'utilisateur en entier (plafonnés), réponses de Claude réduites à leurs premières
lignes et aux lignes qui signalent un échec, une correction ou une décision.
Usage : python vue_condensee.py S11.txt [S12.txt ...]
"""
import re
import sys

KEYWORDS = re.compile(r"(?i)erreur|faux|corrig|oubli|je m'étais|attention|leçon|bloqu|échou|cass|"
                      r"ne fonctionne|n'existe pas|impossible|décid|retenu|choisi|important|toujours|jamais|"
                      r"préf|règle|limite|manque|il faut|ne pas|à éviter")
HEAD_LINES = 4
LINE_CAP = 260
USER_CAP = 2500

for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as fh:
        blocks = re.split(r"\n(?=\[S\d+-T\d+ (?:Toi|Claude)\])", fh.read())
    print(blocks[0].splitlines()[0])
    for b in blocks[1:]:
        lines = b.strip().split("\n")
        header, body = lines[0], lines[1:]
        if "Toi]" in header:
            text = "\n".join(body)
            # Messages d'agents et contenus de skills : pas écrits par l'utilisateur, on abrège.
            agent = re.match(r"(Another Claude session|Base directory for this skill|<task-notification>)", text)
            cap = 300 if agent else USER_CAP
            print(header + "\n" + text[:cap] + (" […]" if len(text) > cap else ""))
        else:
            kept = [l for i, l in enumerate(body) if i < HEAD_LINES or KEYWORDS.search(l)]
            print(header + f"  ({len(body)} lignes, {len(kept)} montrées)")
            for l in kept:
                print(l[:LINE_CAP])
        print()
