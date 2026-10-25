"""Lance le worker en arrière-plan sans bloquer le hook ni ouvrir de fenêtre."""
import os
import subprocess

import config

CREATE_BREAKAWAY_FROM_JOB = 0x01000000   # sortir du job de Claude Code, qui tue ses enfants à la fermeture


def lancer_worker(forcer=False):
    _lancer("worker.py", ["--forcer"] if forcer else [])


def lancer_service():
    _lancer("service_embeddings.py")


def _lancer(script, extra=()):
    env = dict(os.environ, **{config.GARDE: "1"})
    # CREATE_NO_WINDOW plutôt que DETACHED_PROCESS : console invisible héritée par claude.CMD, donc pas de fenêtre.
    drapeaux = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    args = [config.PYTHON, os.path.join(os.path.dirname(os.path.abspath(__file__)), script), *extra]
    config.assurer_dossier()
    options = dict(env=env, close_fds=True, cwd=config.DONNEES,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        subprocess.Popen(args, creationflags=drapeaux | CREATE_BREAKAWAY_FROM_JOB, **options)
    except OSError:
        subprocess.Popen(args, creationflags=drapeaux, **options)
