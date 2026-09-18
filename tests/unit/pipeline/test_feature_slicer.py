import importlib.util
from pathlib import Path

_target_file = Path(__file__).resolve().parent.parent / "data_processing" / "test_slicer.py"
_spec = importlib.util.spec_from_file_location("test_slicer_canonical", _target_file)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

TestFeatureSlicerCore = _mod.TestFeatureSlicerCore
