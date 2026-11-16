"""Exporte les conditions mesurées de l'étude en JSON, sur la sortie standard.

Sert de référence à check_engines.mjs : les moteurs JavaScript doivent retrouver
les mêmes coefficients que le Python sur ces données-là.

    python tests/dump_reference_data.py > reference.json
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.fit_pretrained import FEATURES, TARGETS, load_titanium  # noqa: E402

df = load_titanium()
out = {"features": FEATURES, "X": df[FEATURES].to_numpy(float).tolist()}
for target in TARGETS:
    out[target] = df[target].to_numpy(float).tolist()
print(json.dumps(out))
