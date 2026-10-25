"""Refiltrage des pré-annotations avec la grille validée par l'utilisateur (16/10/2026).

Décisions : G = à retenir (mémoire globale), P = à retenir (mémoire du projet indiqué),
R = rejeté, D = doute à faire trancher. Les surlignages verts (rappel) sont conservés.
Les sessions 1 à 10 (jusqu'à S10-T1) reprennent telles quelles les corrections de l'utilisateur.
"""
import json
import re
import sys

BASE = "../data/annotation/"

# Tables d'annotation (données personnelles, non versionnées) : projet de chaque décision P (par index dans
# toutes.json), doutes, rejets, et sessions relues par l'utilisateur (surlignages gardés et rattachés à un projet).
TABLES = json.load(open(BASE + "refiltrer_tables.json", encoding="utf-8"))
PROJETS = TABLES["projets"]
DOUTES = TABLES["doutes"]
REJETS = TABLES["rejets"]
PROJETS_RELUS = TABLES["projets_relus"]
COMMENTES_NON = {tuple(c) for c in TABLES["commentes_non"]}


def num(a):
    s, t = re.match(r"S(\d+)-T(\d+)", a["id"]).groups()
    return int(s), int(t)


def main():
    mine = json.load(open(BASE + "toutes.json", encoding="utf-8"))
    lu = json.load(open(BASE + "lu_utilisateur.json", encoding="utf-8"))
    gardes = {(a["id"], a["role"], a["text"]) for a in lu}
    projet_de = {i: p for p, idx in PROJETS.items() for i in idx}
    out = []
    for i, a in enumerate(mine):
        a = dict(a, index=i)
        if num(a) <= (10, 1):
            relu_garde = (a["id"], a["role"], a["text"]) in gardes and (a["id"], a["text"]) not in COMMENTES_NON
            if not relu_garde:
                a["decision"] = "R"
            else:
                proj = next((p for p, ids in PROJETS_RELUS.items() if a["id"] in ids), None)
                a["decision"] = "V" if a["color"] == "vert" else ("P" if proj else "G")
                if proj:
                    a["projet"] = proj
            a["source"] = "utilisateur"
        elif a["color"] == "vert":
            a["decision"] = "V"
        elif i in DOUTES:
            a["decision"] = "D"
        elif i in REJETS:
            a["decision"] = "R"
        elif i in projet_de:
            a["decision"], a["projet"] = "P", projet_de[i]
        else:
            a["decision"] = "G"
        out.append(a)
    json.dump(out, open(BASE + "decisions.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    from collections import Counter
    print(Counter(a["decision"] for a in out))
    if len(sys.argv) > 1 and sys.argv[1] == "doutes":
        for a in out:
            if a["decision"] == "D":
                print(a["index"], a["id"], a["role"], "|", a["text"])


if __name__ == "__main__":
    main()
