import sys
import asyncio
import math
import logging
from fastmcp import FastMCP

# --- stderr only (stdio-safe) ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("offline-mcp")

mcp = FastMCP("OfflineOps-MCP")


def _to_float(x, name: str) -> float:
    try:
        return float(x)
    except Exception:
        raise ValueError(f"{name} must be a number")


def _validate_latlon(lat: float, lon: float):
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("lat must be in [-90, 90]")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("lon must be in [-180, 180]")


@mcp.tool()
def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (km) between two coordinates (Haversine)."""
    try:
        lat1 = _to_float(lat1, "lat1")
        lon1 = _to_float(lon1, "lon1")
        lat2 = _to_float(lat2, "lat2")
        lon2 = _to_float(lon2, "lon2")
        _validate_latlon(lat1, lon1)
        _validate_latlon(lat2, lon2)
    except Exception as e:
        return {"error": str(e)}

    R = 6371.0088  # km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    km = R * c

    return {
        "distance_km": round(km, 3),
        "from": {"lat": lat1, "lon": lon1},
        "to": {"lat": lat2, "lon": lon2},
    }


@mcp.tool()
def eta_minutes(distance_km, speed_kmh):
    """ETA in minutes given distance (km) and speed (km/h)."""
    try:
        d = _to_float(distance_km, "distance_km")
        v = _to_float(speed_kmh, "speed_kmh")
    except Exception as e:
        return {"error": str(e)}

    if d < 0:
        return {"error": "distance_km must be >= 0"}
    if v <= 0:
        return {"error": "speed_kmh must be > 0"}

    minutes = (d / v) * 60.0
    return {"distance_km": d, "speed_kmh": v, "eta_minutes": round(minutes, 2)}


@mcp.tool()
def fuel_required_liters(distance_km, consumption_l_per_100km):
    """Fuel needed (liters) for distance, given consumption in L/100km."""
    try:
        d = _to_float(distance_km, "distance_km")
        c = _to_float(consumption_l_per_100km, "consumption_l_per_100km")
    except Exception as e:
        return {"error": str(e)}

    if d < 0:
        return {"error": "distance_km must be >= 0"}
    if c <= 0:
        return {"error": "consumption_l_per_100km must be > 0"}

    liters = (d / 100.0) * c
    return {
        "distance_km": d,
        "consumption_l_per_100km": c,
        "fuel_needed_liters": round(liters, 2),
    }


@mcp.tool()
def battery_runtime_minutes(battery_wh, load_w):
    """Runtime in minutes given battery capacity (Wh) and average load (W)."""
    try:
        b = _to_float(battery_wh, "battery_wh")
        p = _to_float(load_w, "load_w")
    except Exception as e:
        return {"error": str(e)}

    if b <= 0:
        return {"error": "battery_wh must be > 0"}
    if p <= 0:
        return {"error": "load_w must be > 0"}

    minutes = (b / p) * 60.0
    return {"battery_wh": b, "load_w": p, "runtime_minutes": round(minutes, 2)}

@mcp.tool()
def get_current_weather(lat, lon):
    """Current weather from Open-Meteo (no API key)."""
    import requests

    try:
        lat = float(lat)
        lon = float(lon)
    except Exception as e:
        return {"error": "bad lat/lon"}

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&current_weather=true"
    )

    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": "request failed", "details": str(e)}

    return data.get("current_weather", {})

@mcp.tool()
def forecast_hourly(lat, lon, hours: int = 12):
    """Hourly weather forecast for next hours."""
    import requests

    try:
        lat = float(lat)
        lon = float(lon)
        hours = int(hours)
    except:
        return {"error": "invalid args"}

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,precipitation,cloudcover,windspeed_10m"
        "&timezone=auto"
    )

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": "request failed", "details": str(e)}

    # slice to requested hours
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])[:hours]
    temps = hourly.get("temperature_2m", [])[:hours]

    return {"time": times, "temperature_2m": temps}

@mcp.tool()
def geocode_osm(query: str, limit: int = 1):
    """OpenStreetMap geocoding (public)."""
    import requests

    if not query:
        return {"error": "query required"}

    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?q={requests.utils.quote(query)}"
        f"&format=json&limit={limit}"
    )

    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "MCP/1.0"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": "request failed", "details": str(e)}

    out = []
    for item in data:
        out.append({
            "display_name": item.get("display_name"),
            "lat": item.get("lat"),
            "lon": item.get("lon"),
        })

    return {"results": out}


if __name__ == "__main__":
    log.info("Starting OfflineOps-MCP (stdio)...")
    log.info("Python: %s", sys.executable)
    asyncio.run(mcp.run_stdio_async())