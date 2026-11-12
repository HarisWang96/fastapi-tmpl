"""Tiny local-only OTLP/HTTP receiver for the production simulation profile."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    requests = 0
    payload_bytes = 0

    def do_POST(self):
        if self.path != "/v1/traces":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        type(self).requests += 1
        type(self).payload_bytes += length
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def do_GET(self):
        if self.path != "/stats":
            self.send_error(404)
            return
        body = f'{{"requests":{type(self).requests},"payload_bytes":{type(self).payload_bytes}}}'.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 4318), Handler).serve_forever()
