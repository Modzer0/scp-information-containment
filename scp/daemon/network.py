from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkTier:
    tier: str
    name: str
    bandwidth_mbps: int
    latency_p50_ms: int
    latency_p99_ms: int
    monthly_cost_usd: int
    is_commercial: bool          # True = third-party provider can see traffic metadata
    description: str

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "name": self.name,
            "bandwidth_mbps": self.bandwidth_mbps,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "monthly_cost_usd": self.monthly_cost_usd,
            "is_commercial": self.is_commercial,
            "description": self.description,
        }


TIERS: dict[str, NetworkTier] = {}


def _add(t: NetworkTier) -> None:
    TIERS[t.tier] = t


_add(NetworkTier(
    "dialup", "Dial-up / 4G fallback",
    bandwidth_mbps=5, latency_p50_ms=80, latency_p99_ms=250,
    monthly_cost_usd=50, is_commercial=True,
    description="Last-resort fallback. High latency, low bandwidth.",
))
_add(NetworkTier(
    "lte", "4G LTE",
    bandwidth_mbps=50, latency_p50_ms=40, latency_p99_ms=120,
    monthly_cost_usd=400, is_commercial=True,
    description="Mobile-grade link; OK for rural with no fiber.",
))
_add(NetworkTier(
    "dsl", "DSL / cable",
    bandwidth_mbps=200, latency_p50_ms=25, latency_p99_ms=80,
    monthly_cost_usd=800, is_commercial=True,
    description="Urban residential/business cable. Reliable, mid-tier.",
))
_add(NetworkTier(
    "business_fiber", "Business fiber",
    bandwidth_mbps=1_000, latency_p50_ms=5, latency_p99_ms=15,
    monthly_cost_usd=3_500, is_commercial=True,
    description="Gigabit fiber to an office / DC. Bootstrap default.",
))
_add(NetworkTier(
    "dark_fiber", "Dark fiber / metro-E",
    bandwidth_mbps=40_000, latency_p50_ms=2, latency_p99_ms=8,
    monthly_cost_usd=25_000, is_commercial=True,
    description="40 Gbps leased dark fiber. Conduit is still third-party.",
))
_add(NetworkTier(
    "starstream", "Starstream LEO satcom",
    bandwidth_mbps=200, latency_p50_ms=40, latency_p99_ms=70,
    monthly_cost_usd=1_200, is_commercial=True,
    description="LEO satellite link; global coverage incl. maritime.",
))
_add(NetworkTier(
    "geo_sat", "GEO satellite",
    bandwidth_mbps=30, latency_p50_ms=550, latency_p99_ms=700,
    monthly_cost_usd=2_000, is_commercial=True,
    description="Geostationary satcom; last-resort for extreme remote.",
))
_add(NetworkTier(
    "private_sat", "Private satcom (owned)",
    bandwidth_mbps=150, latency_p50_ms=30, latency_p99_ms=60,
    monthly_cost_usd=0, is_commercial=False,
    description="Routed through your own comms satellite + ground station. No provider metadata.",
))


# Encryption tiers (set per-site via site_encryption SKUs)
ENCRYPTION_LEVELS = ["none", "software", "hardware", "type1"]


def encryption_rank(level: str) -> int:
    try:
        return ENCRYPTION_LEVELS.index(level)
    except ValueError:
        return 0


# Minimum encryption required by item class when handling over a commercial link
MIN_ENCRYPTION_FOR_CLASS = {
    "Safe": "software",
    "Euclid": "hardware",
    "Keter": "type1",
}


def list_tiers() -> list[NetworkTier]:
    return sorted(TIERS.values(), key=lambda t: t.bandwidth_mbps)


def get(tier: str) -> NetworkTier | None:
    return TIERS.get(tier)


# Latency bands that gate what a site can do
def supports_realtime_memetic(tier_data: dict) -> bool:
    """Real-time memetic containment needs p99 < 50 ms."""
    return int(tier_data.get("latency_p99_ms", 1000)) < 50


def supports_cloud_ai(tier_data: dict) -> bool:
    """Cloud TPU rental needs >= 1 Gbps and p50 < 30 ms."""
    return (
        int(tier_data.get("bandwidth_mbps", 0)) >= 1_000
        and int(tier_data.get("latency_p50_ms", 1000)) < 30
    )
