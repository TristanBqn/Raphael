"""Modèle de réglages personnels : copier en config_local.py (non versionné). Surcharge les valeurs de config.py."""

PRENOM = "Camille"                # nommé dans les consignes du rédacteur et à l'injection (« dit par Camille »)
SPHERE_PERSO = "ses projets personnels et ses loisirs"

# Motif cherché dans le chemin du dossier de travail (minuscules, séparateurs « \ ») → univers
UNIVERS = [
    ("onedrive - mon employeur", "Employeur"),
    ("\\client-a", "ClientA"),
]

# Question Jev de classer_univers.py (en anglais : Jev gère mieux l'anglais)
UNIVERS_JEV = {
    "instructions": "Which sphere of Camille's life does `memory` belong to?",
    "criteria": {
        "commun": "About Camille themselves whatever the context: their computers, network, accounts, servers, "
                  "tools, or general preferences on how answers and work should be done.",
        "perso": "Their personal sphere: side projects, hobbies, their personal life.",
        "Employeur": "Their employer: internal projects, colleagues, clients and audits.",
        "ClientA": "The client A: their projects and tools.",
    },
}
