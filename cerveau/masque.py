"""Masquage des secrets avant tout stockage ou envoi à Jev."""
import re

SECRET_PATTERNS = [
    re.compile(r"apikey_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}"),                                    # jeton de bot Telegram
    re.compile(r"\b[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{20,}"),   # jeton Discord / JWT
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)((?:password|passwd|mot de passe|mdp|secret|token|api[_ -]?key)\s*[:=]\s*)\S+"),
    # « mets le mot de passe XXXX » : mot de passe donné sans séparateur, contenant au moins un chiffre.
    re.compile(r"(?i)((?:password|passwd|mot de passe|mdp)\s+)(?=\S*\d)(\S{8,})"),
    # Longue chaîne mêlant lettres et chiffres, sans séparateur de chemin : probable jeton.
    re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{40,}\b"),
]
SYSTEM_BLOCK = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


CONTROL_CHARS = re.compile("[" + "".join(map(chr, [*range(0, 9), 11, 12, *range(14, 32)])) + "]")


def mask_secrets(text: str) -> str:
    text = CONTROL_CHARS.sub("", text)
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + "[SECRET MASQUÉ]", text)
        else:
            text = pattern.sub("[SECRET MASQUÉ]", text)
    return text
