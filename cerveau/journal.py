"""Journal JSON lignes : tout ce que font les portes et le worker, pour mesurer et déboguer."""
import json
import time

import config


def log(evenement, **champs):
    try:
        config.assurer_dossier()
        with open(config.JOURNAL, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": round(time.time(), 3), "evt": evenement, **champs},
                                ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass
