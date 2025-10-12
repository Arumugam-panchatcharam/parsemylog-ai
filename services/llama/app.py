from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

OLLAMA_HOST = "http://host.docker.internal:11434"  # local Ollama daemon
MODEL = os.getenv("LLAMA_MODEL", "llama3")

@app.route("/query", methods=["POST"])
def query_model():
    data = request.get_json()
    prompt = data.get("prompt", "")
    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": MODEL, "prompt": prompt},
            timeout=120
        )
        response.raise_for_status()
        content = response.json()
        text = content.get("response", "")
        return jsonify({"response": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
