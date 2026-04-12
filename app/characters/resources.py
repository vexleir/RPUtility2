from __future__ import annotations


DEFAULT_CURRENCIES = {
    "cp": 0,
    "sp": 0,
    "gp": 0,
}

_CURRENCY_CP_VALUES = {
    "cp": 1,
    "sp": 10,
    "gp": 100,
}


def normalize_currencies(wallet: dict[str, int] | None) -> dict[str, int]:
    normalized = dict(DEFAULT_CURRENCIES)
    for key, value in (wallet or {}).items():
        normalized[str(key).lower()] = max(0, int(value or 0))
    return normalized


def adjust_currency(wallet: dict[str, int] | None, denomination: str, delta: int) -> dict[str, int]:
    normalized = normalize_currencies(wallet)
    key = denomination.strip().lower()
    normalized[key] = max(0, int(normalized.get(key, 0)) + int(delta))
    return normalized


def total_currency_value_cp(wallet: dict[str, int] | None) -> int:
    normalized = normalize_currencies(wallet)
    total = 0
    for key, value in normalized.items():
        total += int(value) * _CURRENCY_CP_VALUES.get(key, 0)
    return total


def normalize_resource_pools(pools: dict[str, dict] | None) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for raw_name, raw_data in (pools or {}).items():
        name = str(raw_name).strip().lower()
        if not name:
            continue
        data = raw_data or {}
        maximum = max(0, int(data.get("max", 0) or 0))
        current = max(0, min(int(data.get("current", maximum) or 0), maximum))
        normalized[name] = {
            "current": current,
            "max": maximum,
            "restores_on": str(data.get("restores_on", "") or ""),
        }
    return normalized


def consume_resource(pools: dict[str, dict] | None, resource_name: str, amount: int = 1) -> tuple[dict[str, dict], dict]:
    normalized = normalize_resource_pools(pools)
    key = resource_name.strip().lower()
    if key not in normalized:
        raise ValueError(f"Unknown resource pool: {resource_name}")
    if amount < 0:
        raise ValueError("Resource consumption amount must be non-negative")
    pool = dict(normalized[key])
    if pool["current"] < amount:
        raise ValueError(f"Not enough {resource_name} remaining")
    pool["current"] -= amount
    normalized[key] = pool
    return normalized, pool


def restore_resource_pools(
    pools: dict[str, dict] | None,
    *,
    rest_type: str,
) -> tuple[dict[str, dict], list[dict]]:
    normalized = normalize_resource_pools(pools)
    rest_key = str(rest_type or "").strip().lower()
    restored: list[dict] = []
    for name, pool in normalized.items():
        restores_on = str(pool.get("restores_on", "") or "").strip().lower()
        if not restores_on:
            continue
        if restores_on != rest_key and not (rest_key == "long_rest" and restores_on == "short_rest"):
            continue
        current = int(pool.get("current", 0) or 0)
        maximum = int(pool.get("max", 0) or 0)
        if current >= maximum:
            continue
        pool["current"] = maximum
        normalized[name] = pool
        restored.append({
            "resource": name,
            "from": current,
            "to": maximum,
            "restores_on": restores_on,
        })
    return normalized, restored
