# ---------- LLaMA Summarizer ----------
import os
import requests

class LLaMASummarizer:
    def __init__(self, server_url=None):
        self.server_url = server_url or os.environ.get("LLAMA_SERVER_URL", "http://localhost:41030/completion")

    def summarize(self, embed_templates, max_tokens=256):
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
        resp = requests.post(self.server_url, json={"prompt": prompt, "max_tokens": max_tokens})
        if resp.status_code == 200:
            return resp.json().get("content", resp.text)
        return f"Error calling LLaMA server: {resp.status_code} {resp.text}"