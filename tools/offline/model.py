"""Maintainer entry point for the shared standalone manifest contract."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "qbox_manifest_contract", Path(__file__).resolve().parents[2] /
    "packaging/offline/checks/manifest.py")
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)
# Preserve the complete existing contract, including internal validation helpers.
globals().update({name: value for name, value in vars(_contract).items()
                  if not name.startswith("__")})
