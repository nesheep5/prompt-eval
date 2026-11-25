"""在庫 API の入口。設定を読み、ハンドラを登録して起動する。"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from settings import load_settings
from storage import Storage


def make_handler(storage: Storage):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/items":
                self.send_error(404)
                return
            body = json.dumps(storage.items()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    settings = load_settings("config/settings.yaml")
    storage = Storage(settings["storage"]["path"])
    server = HTTPServer(("", settings["server"]["port"]), make_handler(storage))
    server.timeout = settings["server"]["request_timeout_seconds"]
    server.serve_forever()


if __name__ == "__main__":
    main()
