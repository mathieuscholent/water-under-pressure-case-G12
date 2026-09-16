"""Vercel serverless entry point for the pricing engine."""

import json
from http.server import BaseHTTPRequestHandler

from pricing_engine import (PricingConfig, calculate_price, optimize_revenue_target,
                            compare_scenarios, fetch_eea_scarcity, model_assumptions)
from live_data import live_country_payload


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
            config = PricingConfig(**config_values)
            result = (optimize_revenue_target(inputs, config) if inputs.get("mode") == "revenue_target"
                      else compare_scenarios(inputs, config) if inputs.get("mode") == "scenario_comparison"
                      else calculate_price(inputs, config))
            self._send(200, result)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            self._send(400, {"error": str(error)})

    def do_GET(self) -> None:  # noqa: N802
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(self.path).query)
        if query.get("mode") == ["assumptions"]:
            self._send(200, model_assumptions())
            return
        if query.get("mode") == ["countries"]:
            self._send(200, live_country_payload())
            return
        if "geography" in query:
            try:
                year = int(query["year"][0]) if "year" in query else None
                self._send(200, fetch_eea_scarcity(query["geography"][0], year))
            except (OSError, ValueError) as error:
                self._send(400, {"error": str(error)})
            return
        self._send(200, {"service": "water-pricing-engine", "status": "ok", "scarcity_endpoint": "/api/?geography=Germany"})
