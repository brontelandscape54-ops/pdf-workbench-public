import importlib


def test_application_startup_module_imports() -> None:
    module = importlib.import_module("pdf_workbench.__main__")
    assert callable(module.main)
