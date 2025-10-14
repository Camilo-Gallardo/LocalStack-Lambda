import os


def handler(event, context):
    name = (event or {}).get("name", "world")
    stage = os.getenv("STAGE", "local")
    return {
   	"ok": True,
    	"message": f"Hello, {name}!",
    	"stage": stage,
    }
