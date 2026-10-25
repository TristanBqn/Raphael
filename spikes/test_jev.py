"""Spike : vérifie la clé API Jev et mesure la latence réelle d'un appel."""
import time

t0 = time.perf_counter()
from typesafe_sdk import Choice, Noul, TypeSafeClient
t1 = time.perf_counter()

with TypeSafeClient() as client:
    for i in range(3):
        a = time.perf_counter()
        r = client.system_one(
            state={"message": "Mon NAS est un Synology installé au bureau, retiens-le."},
            questions={
                "fact": Noul(instructions="Does `message` state a lasting fact about the user?"),
                "kind": Choice(
                    instructions="What kind of memory is in `message`?",
                    criteria={"fact": None, "preference": None, "procedure": None, "none": None},
                ),
            },
        )
        b = time.perf_counter()
        kind = r.choices["kind"]
        print(f"appel {i + 1}: {int((b - a) * 1000)} ms | modèle {r.model} | "
              f"fait={r.nouls['fact'].noul:.2f} | type={kind.choice} ({kind.confidence:.2f}) | "
              f"tokens={r.usage.input_tokens}")
print(f"import SDK : {int((t1 - t0) * 1000)} ms")
