"""EmbeddingGemma-300M (ONNX q8) : vecteurs de sens pour les souvenirs et les requêtes.

Deux façons de l'utiliser : dans le processus (worker, service) ou via le service local (porte 1), qui évite de
recharger le modèle à chaque message.
"""
import json
import os
import urllib.request

import numpy as np

import config

_session = None
_tokenizer = None


def _charger():
    global _session, _tokenizer
    if _session is None:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        _session = ort.InferenceSession(os.path.join(config.MODELE_EMBEDDINGS, "onnx", "model_quantized.onnx"),
                                        providers=["CPUExecutionProvider"])
        _tokenizer = Tokenizer.from_file(os.path.join(config.MODELE_EMBEDDINGS, "tokenizer.json"))
        _tokenizer.enable_truncation(max_length=512)
    return _session, _tokenizer


def calculer(textes, mode):
    """Vecteurs normalisés (float32, 768). `mode` : 'requete' ou 'document' (préfixes de tâche du modèle)."""
    session, tok = _charger()
    prefixe = config.PREFIXE_REQUETE if mode == "requete" else config.PREFIXE_DOCUMENT
    enc = tok.encode_batch([prefixe + t for t in textes])
    longueur = max(len(e.ids) for e in enc)
    ids = np.array([e.ids + [0] * (longueur - len(e.ids)) for e in enc], dtype=np.int64)
    masque = np.array([e.attention_mask + [0] * (longueur - len(e.ids)) for e in enc], dtype=np.int64)
    vecteurs = session.run(["sentence_embedding"], {"input_ids": ids, "attention_mask": masque})[0]
    vecteurs = vecteurs / np.linalg.norm(vecteurs, axis=1, keepdims=True)
    return vecteurs.astype(np.float32)


def via_service(textes, mode):
    """Demande les vecteurs au service local ; None s'il ne répond pas (le lancer, puis calculer sur place)."""
    corps = json.dumps({"textes": textes, "mode": mode}).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{config.PORT_EMBEDDINGS}/embed", data=corps,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=config.DELAI_SERVICE) as r:
            return np.array(json.loads(r.read())["vecteurs"], dtype=np.float32)
    except OSError:
        return None


def vecteur_requete(texte):
    v = via_service([texte], "requete")
    if v is None:
        from lanceur import lancer_service
        lancer_service()
        v = calculer([texte], "requete")
    return v[0]


def vers_blob(v):
    return np.asarray(v, dtype=np.float32).tobytes()


def depuis_blob(b):
    return np.frombuffer(b, dtype=np.float32)
