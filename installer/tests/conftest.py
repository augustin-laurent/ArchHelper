import os

# The catalogs resolve per process from V8_LANG; pin French so every French
# fragment the tests match stays stable regardless of the ambient language.
os.environ.setdefault("V8_LANG", "fr")
