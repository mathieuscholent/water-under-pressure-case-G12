"""Vercel serverless entry point for the pricing engine."""

import json
from http.server import BaseHTTPRequestHandler

from pricing_engine import PricingConfig, calculate_price, optimize_revenue_target


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        try:
            length = int(self.headers.get("Content-Length", "0"))
            inputs = json.loads(self.rfile.read(length))
            config_values = inputs.pop("config", {})
            result = (optimize_revenue_target(inputs, PricingConfig(**config_values))
                      if inputs.get("mode") == "revenue_target" else calculate_price(inputs, PricingConfig(**config_values)))
            self._send(200, result)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            self._send(400, {"error": str(error)})

    def do_GET(self) -> None:  # noqa: N802
        self._send(200, {"service": "water-pricing-engine", "status": "ok"})
