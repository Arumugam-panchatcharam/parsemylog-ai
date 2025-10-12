import requests
from .celery_app import celery
import os

LLAMA_API_URL = os.environ.get("LLAMA_API_URL", "http://localhost:41030/query")

@celery.task(bind=True)
def process_llama_query(self, embed_templates, max_tokens=256):
    prompt_parts = []
    prompt_parts = [
            {
                "LOG_FILENAME": r.get("filename", "-"),
                "LOG_TEMPLATE": r.get("template", ""),
                "LOG_FREQUENCY": r.get("frequency", "-"),
            }
            for r in embed_templates
        ]
    prompt = (
        "You are an assistant that summarizes RDK log groups.\n"
        "For each LOG_TEMPLATES and LOG_FREQUENCY block below, provide a short summary of what these logs indicate, probable causes, and suggested next steps.\n\n"
        + "\n\n".join(prompt_parts)
        + "\n\nRespond clearly and label each summary with the LOG_FILENAME it corresponds to."
    )
    try:
        resp = requests.post(LLAMA_API_URL, json={"prompt": prompt, "max_tokens": max_tokens})
        resp.raise_for_status()
        return {"state": "done", "result": resp.json().get("response")}
    except Exception as e:
        return {"state": "error", "message": str(e)}

