"""Compare l'environnement Python actif aux versions EXACTES de Backend_AgentIA/requirements.txt.
Usage (venv activé) : python ..\\scripts\\verifier_versions.py"""
import re
import sys
from importlib import metadata
from pathlib import Path

req = Path(__file__).resolve().parent.parent / "Backend_AgentIA" / "requirements.txt"
norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()
attendu = {}
for ligne in req.read_text(encoding="utf-8").splitlines():
    m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;#]+)", ligne.strip())
    if m:
        attendu[norm(m.group(1))] = m.group(2)
installe = {norm(d.metadata["Name"]): d.version for d in metadata.distributions()}

print(f"Python {sys.version.split()[0]} (référence : 3.13.x)")
ecarts = [(n, v, installe.get(n)) for n, v in sorted(attendu.items()) if installe.get(n) != v]
for n, voulu, actuel in ecarts:
    print(f"  ÉCART  {n}: requirements={voulu}  installé={actuel or 'ABSENT'}")
if ecarts or not sys.version.startswith("3.13"):
    print("-> Corrigez avec : pip install -r Backend_AgentIA\\requirements.txt")
    sys.exit(1)
print(f"OK : {len(attendu)} paquets identiques aux versions de référence.")
