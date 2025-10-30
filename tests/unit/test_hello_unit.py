import importlib.util
import pathlib

# Carga el handler sin instalar el paquete (import dinámico desde ruta)
HANDLER_PATH = pathlib.Path(__file__).parents[2] / "lambdas/hello_world/handler.py"
spec = importlib.util.spec_from_file_location("handler", HANDLER_PATH)
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)  # type: ignore


def test_message_default():
    resp = handler.handler({}, None)
    assert resp["ok"] is True
    assert resp["message"].startswith("Hello")


def test_message_name():
    resp = handler.handler({"name": "Camilo"}, None)
    assert resp["message"] == "Hello, Camilo!"
