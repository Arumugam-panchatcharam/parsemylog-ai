from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os

app = FastAPI(title="Local Llama API", version="1.0")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

class QueryRequest(BaseModel):
    prompt: str
    stream: bool = False

@app.get("/")
def root():
    return {"status": "ok", "message": "Llama API running with local Ollama"}

@app.post("/generate")
def generate_text(req: QueryRequest):
    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": req.prompt},
            timeout=300
        )
        response.raise_for_status()
        data = response.text
        return {"response": data}
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Ollama request failed: {e}")