"""Ce qui n'est pas un message de l'utilisateur : messages d'agents, notifications, contenus de skills, etc.

Partagé par la porte 1 (capture en direct) et l'import de l'historique.
"""
import re

BRUIT = re.compile(r"^(Base directory for this skill|Another Claude session|<task-notification>|<teammate-message|"
                   r"<agent-message|Stop hook feedback|This session is being continued|<bash-|<local-command|"
                   r"<command-|Caveat:|\[Image|\[Request interrupted|Context Usage|/compact|:exit)", re.S)
OBJECTIF = re.compile(r'^A session-scoped Stop hook is now active with condition: "(.*?)"\. Briefly acknowledge', re.S)


def message_utilisateur(texte):
    """Le texte réellement écrit par l'utilisateur, ou None si le message n'en contient pas."""
    m = OBJECTIF.match(texte)
    if m:
        return m.group(1)          # un /goal : on garde l'objectif exprimé par l'utilisateur
    if BRUIT.match(texte.lstrip()):
        return None
    return texte
