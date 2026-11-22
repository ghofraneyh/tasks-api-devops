import json, logging, time
from flask import Flask, jsonify, request, g
from werkzeug.exceptions import HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

# ---- Logs structurés (JSON) ----
class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"time": self.formatTime(record), "level": record.levelname,
                "message": record.getMessage()}
        data.update(getattr(record, "extra", {}))
        return json.dumps(data)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
log = logging.getLogger("tasks-api")
log.addHandler(handler)
log.setLevel(logging.INFO)

# ---- Tracing (OpenTelemetry, export console) ----
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
tracer = trace.get_tracer("tasks-api")

# ---- Métriques Prometheus ----
REQUESTS = Counter("http_requests_total", "Nombre de requêtes", ["method", "endpoint", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Temps de réponse", ["endpoint"])

app = Flask(__name__)
tasks = {}
counter = {"next_id": 1}


@app.before_request
def start_request():
    g.start = time.time()
    g.span = tracer.start_span(f"{request.method} {request.path}")


@app.after_request
def end_request(resp):
    duration = time.time() - g.start
    endpoint = request.url_rule.rule if request.url_rule else "unknown"
    trace_id = format(g.span.get_span_context().trace_id, "032x")
    REQUESTS.labels(request.method, endpoint, resp.status_code).inc()
    LATENCY.labels(endpoint).observe(duration)
    g.span.set_attribute("http.status_code", resp.status_code)
    g.span.end()
    resp.headers["X-Trace-Id"] = trace_id
    log.info("request", extra={"extra": {
        "method": request.method, "path": request.path, "status": resp.status_code,
        "duration_ms": round(duration * 1000, 2), "trace_id": trace_id}})
    return resp


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    log.error("unhandled error", extra={"extra": {"error": str(e)}})
    return jsonify(error="internal server error"), 500


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.get("/tasks")
def list_tasks():
    return jsonify(list(tasks.values()))


@app.post("/tasks")
def create_task():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify(error="title is required"), 400
    task = {"id": counter["next_id"], "title": title, "done": False}
    tasks[task["id"]] = task
    counter["next_id"] += 1
    return jsonify(task), 201


@app.get("/tasks/<int:task_id>")
def get_task(task_id):
    if task_id not in tasks:
        return jsonify(error="task not found"), 404
    return jsonify(tasks[task_id])


@app.delete("/tasks/<int:task_id>")
def delete_task(task_id):
    if tasks.pop(task_id, None) is None:
        return jsonify(error="task not found"), 404
    return "", 204


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)