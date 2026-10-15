from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HOST = os.getenv("CALLBACK_TEST_HOST", "0.0.0.0")
PORT = int(os.getenv("CALLBACK_TEST_PORT", "18080"))
LOG_PATH = Path(
    os.getenv("CALLBACK_TEST_LOG", "callback-test.jsonl")
)

EXPECTED_FIELDS = {
    "job_id",
    "job_status",
    "result_path",
    "model_type",
    "message",
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("callback-test-server")


class CallbackHandler(BaseHTTPRequestHandler):
    server_version = "CallbackTestServer/1.0"

    def _send_json(
        self,
        status_code: int,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(404, {"message": "Not found"})
            return

        self._send_json(200, {"status": "UP"})

    def do_POST(self) -> None:
        if self.path != "/api/model/callback":
            self._send_json(404, {"message": "Not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))

            if content_length <= 0 or content_length > 1024 * 1024:
                raise ValueError("Invalid Content-Length")

            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))

            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")

            received_fields = set(payload)
            missing_fields = EXPECTED_FIELDS - received_fields
            extra_fields = received_fields - EXPECTED_FIELDS

            if missing_fields:
                names = ", ".join(sorted(missing_fields))
                raise ValueError(f"Missing fields: {names}")

            if extra_fields:
                names = ", ".join(sorted(extra_fields))
                raise ValueError(f"Unexpected fields: {names}")

        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(
                400,
                {
                    "accepted": False,
                    "message": str(exc),
                },
            )
            return

        received_at = datetime.now(timezone.utc).isoformat()
        log_record = {
            "received_at": received_at,
            "client": self.client_address[0],
            "payload": payload,
        }

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(
                json.dumps(log_record, ensure_ascii=False) + "\n"
            )

        logger.info(
            "Callback received: %s",
            json.dumps(payload, ensure_ascii=False),
        )

        self._send_json(
            200,
            {
                "accepted": True,
                "receivedAt": received_at,
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        logger.info(
            "%s %s",
            self.client_address[0],
            format % args,
        )


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), CallbackHandler)

    logger.info(
        "Callback test server listening on http://%s:%s",
        HOST,
        PORT,
    )
    logger.info("Health endpoint: /health")
    logger.info("Callback endpoint: /api/model/callback")
    logger.info("Log file: %s", LOG_PATH.resolve())

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()


