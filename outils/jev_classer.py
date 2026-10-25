"""Classement zero-shot des souvenirs candidats par Jev, avec la grille validée le 16/10/2026.

Questions et seuils sont regroupés en tête de fichier pour être relus facilement.
Usage : python jev_classer.py <docx pré-annoté>
"""
import asyncio
import json
import sys

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, NoulCriteria

from annotation_docx import HEADING, blocks
from docx import Document

MODEL = "jev-1.13.0"          # version épinglée : les seuils sont réglés pour elle
SEUIL_RETENIR = 0.5           # point de départ conseillé par le cookbook « Simple memory system »
CONCURRENCE = 8
BASE = "../data/annotation/"

QUESTIONS = {
    "retenir": Noul(
        instructions=(
            "Is `candidate` worth saving in the user's long-term memory? Judge only what `candidate` says, "
            "using `paragraph` and `user_request` as context. It is worth saving only if it will still be true "
            "and useful in a future, different conversation."
        ),
        criteria=NoulCriteria(
            true=(
                "Yes: a lasting fact about the user, their computer, accounts, network or servers; a general "
                "preference about how they want answers or work done, valid whatever the topic; a reusable "
                "technical lesson learned from an error; or a lasting decision or rule for one of their projects."
            ),
            false=(
                "No: an instruction only for the current task (for example 'audit your answer', 'do not spawn a "
                "subagent', 'give me a step-by-step list'); something stated in the future tense or as a "
                "hypothesis; an isolated detail that will not be reused (a file name, a version seen in passing); "
                "a temporary status; or the assistant describing its own usual method."
            ),
        ),
    ),
    "portee": Choice(
        instructions="If `candidate` were saved, where would it be useful?",
        criteria={
            "global": "In any conversation, whatever the project: facts about the user or their setup, general preferences, general technical lessons.",
            "projet": "Only when working on the specific project of `project_folder` or named in `paragraph`.",
            "ponctuel": "Nowhere: it only matters for the current task.",
        },
    ),
    "type": Choice(
        instructions="What kind of information is `candidate`?",
        criteria={
            "fait": "A fact about the user, their setup or their tools.",
            "preference": "How the user wants answers or work to be done.",
            "lecon": "A technical lesson or a procedure that works, often learned from a failure.",
            "decision_projet": "A decision, rule or constraint for a project.",
            "aucun": "None of the above.",
        },
    ),
}

# Version 2 : la grille découpée en questions atomiques (motif « composite scoring »), combinées en code.
def _n(q, oui, non):
    return Noul(instructions=q, criteria=NoulCriteria(true=oui, false=non))

QUESTIONS_V2 = {
    "fait": _n("Does `candidate` state a fact about the user's computer, network, accounts, servers, installed tools, or where one of their projects or files is located?",
               "Yes: a concrete fact about their setup or the location of something they own.",
               "No: not about their setup or their files."),
    "preference": _n("Does `candidate` express how the user wants answers or work to be done in general (level of detail, simplicity, tone, scope of changes)?",
                     "Yes: a working or communication preference that could apply to other requests.",
                     "No: not a preference about how answers or work should be done."),
    "lecon": _n("Does `candidate` state a technical lesson: something that does not work, is missing, breaks, or a fix that worked?",
                "Yes: a reusable technical finding, often after an error.",
                "No: no technical finding."),
    "regle_projet": _n("Does `candidate` state a decision, rule or constraint for one of the user's projects?",
                       "Yes: a choice or constraint that the project must keep following.",
                       "No: no lasting project decision."),
    "tache_seule": _n("Is `candidate` an instruction that only concerns the current request, such as asking to check, audit, list, or not to use a tool for this answer?",
                      "Yes: it only tells the assistant what to do right now.",
                      "No: it is not just an instruction for the current request."),
    "futur": _n("Is `candidate` about something that has not happened yet, a plan, or a hypothesis?",
                "Yes: future, plan or hypothesis.",
                "No: it describes something already true."),
    "detail_isole": _n("Is `candidate` an isolated detail unlikely to matter later, such as a version number seen in passing, a temporary status, or the assistant describing what it just did?",
                       "Yes: an isolated or temporary detail.",
                       "No: it could matter later."),
}


def score_v2(n):
    """Utile si l'un des quatre critères positifs est vrai, sauf si un critère d'exclusion l'emporte."""
    positif = max(n["fait"], n["preference"], n["lecon"], n["regle_projet"])
    exclusion = max(n["tache_seule"], n["futur"], n["detail_isole"])
    return positif * (1 - exclusion)


def contextes(docx_path):
    """(id, rôle) -> (dossier du projet, demande de l'utilisateur du tour, paragraphes)."""
    doc = Document(docx_path)
    projet, ctx, demande = "", {}, {}
    for kind, key, p in blocks(doc):
        if kind == "heading":
            projet = p.text.split(" — ")[-1]
        elif kind == "content":
            entry = ctx.setdefault(key, {"projet": projet, "paras": []})
            entry["paras"].append(p.text)
            if key[1] == "Toi":
                demande.setdefault(key[0], [])
                demande[key[0]].append(p.text)
    return ctx, demande


def etat(item, ctx, demande):
    entry = ctx.get((item["id"], item["role"]), {"projet": "", "paras": []})
    para = next((t for t in entry["paras"] if item["text"] in t), item["text"])
    return {
        "project_folder": entry["projet"],
        "speaker": "user" if item["role"] == "Toi" else "assistant",
        "user_request": " ".join(demande.get(item["id"], []))[:700],
        "paragraph": para[:900],
        "candidate": item["text"],
    }


async def classer(items, ctx, demande):
    sem = asyncio.Semaphore(CONCURRENCE)
    async with AsyncTypeSafeClient(model=MODEL) as client:
        async def un(item):
            async with sem:
                st = etat(item, ctx, demande)
                r = await client.system_one(state=st, questions=QUESTIONS)
                r2 = await client.system_one(state=st, questions=QUESTIONS_V2)
                n2 = {k: v.noul for k, v in r2.nouls.items()}
                return dict(item, jev_v2=n2, jev_v2_score=score_v2(n2),
                            jev_retenir=r.nouls["retenir"].noul,
                            jev_portee=r.choices["portee"].choice,
                            jev_portee_conf=r.choices["portee"].confidence,
                            jev_type=r.choices["type"].choice,
                            jev_tokens=r.usage.input_tokens + r2.usage.input_tokens)
        return await asyncio.gather(*(un(i) for i in items))


def evaluer(res, cle="jev_retenir"):
    print(f"\n=== {cle} ===")
    relus = [r for r in res if r.get("source") == "utilisateur" and r["color"] == "jaune"]
    print(f"\nRéférence utilisateur : {len(relus)} surlignages jaunes relus (sessions relues)")
    pos = [r[cle] for r in relus if r["decision"] != "R"]; neg = [r[cle] for r in relus if r["decision"] == "R"]
    auc = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))
    print(f"  AUC {auc:.2f} | garder tout = {len(pos) / len(relus):.0%}")
    for seuil in (0.1, 0.2, 0.3, 0.4, 0.5):
        vp = sum(1 for r in relus if r[cle] >= seuil and r["decision"] != "R")
        fp = sum(1 for r in relus if r[cle] >= seuil and r["decision"] == "R")
        fn = sum(1 for r in relus if r[cle] < seuil and r["decision"] != "R")
        vn = sum(1 for r in relus if r[cle] < seuil and r["decision"] == "R")
        print(f"  seuil {seuil}: exactitude {(vp + vn) / len(relus):.0%} | gardés à tort {fp} | rejetés à tort {fn}")
    autres = [r for r in res if r.get("source") != "utilisateur" and r["decision"] in ("G", "P", "R")]
    acc = sum(1 for r in autres if (r[cle] >= SEUIL_RETENIR) == (r["decision"] != "R")) / len(autres)
    print(f"Accord avec mes pré-annotations (autres sessions, hors doutes) : {acc:.0%} sur {len(autres)}")
    gp = [r for r in autres if r["decision"] in ("G", "P")]
    acc_p = sum(1 for r in gp if (r["jev_portee"] == "projet") == (r["decision"] == "P")) / len(gp)
    print(f"Accord sur la portée globale/projet : {acc_p:.0%} sur {len(gp)}")
    print(f"Tokens d'entrée : {sum(r['jev_tokens'] for r in res):,} (≈ {sum(r['jev_tokens'] for r in res) * 0.042 / 1e6:.4f} $)")


def main():
    docx_path = sys.argv[1]
    items = [i for i in json.load(open(BASE + "decisions.json", encoding="utf-8")) if i["color"] == "jaune"]
    ctx, demande = contextes(docx_path)
    res = asyncio.run(classer(items, ctx, demande))
    json.dump(res, open(BASE + "jev_resultats.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    evaluer(res)
    evaluer(res, "jev_v2_score")


if __name__ == "__main__":
    main()
