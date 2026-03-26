from flask import Flask, jsonify, request
from flask_cors import CORS
import uuid, time

from service import handle_chat
app = Flask(__name__)
CORS(app)

@app.get("/")
def home():
    return jsonify({"endpoints": ["/health", "/chat"]})

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/chat")
def chat():
    request_id = str(uuid.uuid4())
    start = time.time()

    payload = request.get_json(silent=True) or {}
    resp, status = handle_chat(payload, request_id=request_id, start_time=start)
    return jsonify(resp), status

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)