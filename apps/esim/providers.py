"""eSIM provider adapters. Pick one with ESIM_PROVIDER in .env (sandbox | airalo).

The Airalo adapter follows the Partner API v2 flow (token → packages → orders → usage); confirm
field names against https://developers.partners.airalo.com when partner access is granted.
"""
import logging
import secrets
import time
from dataclasses import dataclass

import requests
from django.conf import settings

log = logging.getLogger("vipi")


class ProviderError(Exception):
    pass


@dataclass
class ProvisionResult:
    provider_order_id: str
    iccid: str
    lpa: str
    data_total_mb: int


@dataclass
class Usage:
    data_total_mb: int
    data_used_mb: int
    status: str = ""  # provider's own status text, e.g. "ACTIVE", "EXPIRED"


class SandboxProvider:
    """Fake eSIMs for development and tests — never installs on a real phone."""
    name = "sandbox"

    def create_order(self, bundle, reference) -> ProvisionResult:
        code = secrets.token_hex(8).upper()
        mb = int(float(bundle.data_gb) * 1024)
        return ProvisionResult(f"SBX-{reference}", "8925400000" + str(int(time.time() * 1000))[-10:],
                               f"LPA:1$smdp.sandbox.vipi.test${code}", mb)

    def get_usage(self, order) -> Usage:
        # Pretend a little data was used since provisioning.
        used = min(order.data_total_mb, order.data_used_mb + 37)
        return Usage(order.data_total_mb, used, "ACTIVE")


class AiraloProvider:
    name = "airalo"

    def __init__(self):
        self.base = settings.ESIM["AIRALO_BASE_URL"].rstrip("/")
        self._token = None
        self._token_expiry = 0

    def _auth(self):
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        cfg = settings.ESIM
        if not (cfg["AIRALO_CLIENT_ID"] and cfg["AIRALO_CLIENT_SECRET"]):
            raise ProviderError("Airalo credentials are not configured.")
        r = requests.post(f"{self.base}/v2/token", data={
            "client_id": cfg["AIRALO_CLIENT_ID"], "client_secret": cfg["AIRALO_CLIENT_SECRET"],
            "grant_type": "client_credentials"}, headers={"Accept": "application/json"}, timeout=20)
        if r.status_code != 200:
            raise ProviderError(f"Airalo auth failed ({r.status_code}).")
        data = r.json().get("data", {})
        self._token = data.get("access_token")
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _headers(self):
        return {"Authorization": f"Bearer {self._auth()}", "Accept": "application/json"}

    def create_order(self, bundle, reference) -> ProvisionResult:
        r = requests.post(f"{self.base}/v2/orders", headers=self._headers(), timeout=45, data={
            "quantity": 1, "package_id": bundle.provider_package_id, "type": "sim",
            "description": f"Vipi! {reference}"})
        if r.status_code not in (200, 201):
            raise ProviderError(f"Airalo order failed ({r.status_code}): {r.text[:160]}")
        data = r.json().get("data", {})
        sims = data.get("sims") or []
        if not sims:
            raise ProviderError("Airalo returned no eSIM.")
        sim = sims[0]
        lpa = sim.get("qrcode") or ""
        if not lpa.startswith("LPA:") and sim.get("lpa") and sim.get("matching_id"):
            lpa = f"LPA:1${sim['lpa']}${sim['matching_id']}"
        mb = int(float(bundle.data_gb) * 1024)
        return ProvisionResult(str(data.get("id", "")), str(sim.get("iccid", "")), lpa, mb)

    def get_usage(self, order) -> Usage:
        r = requests.get(f"{self.base}/v2/sims/{order.iccid}/usage", headers=self._headers(), timeout=20)
        if r.status_code != 200:
            raise ProviderError(f"Airalo usage failed ({r.status_code}).")
        d = r.json().get("data", {})
        total = int(d.get("total", order.data_total_mb) or 0)
        remaining = int(d.get("remaining", total) or 0)
        return Usage(total, max(0, total - remaining), str(d.get("status", "")))


_PROVIDERS = {"sandbox": SandboxProvider, "airalo": AiraloProvider}


def get_provider(name=None):
    name = name or settings.ESIM["PROVIDER"]
    try:
        return _PROVIDERS[name]()
    except KeyError as e:
        raise ProviderError(f"Unknown eSIM provider '{name}'.") from e
