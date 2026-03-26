from fastmcp import FastMCP
import requests
import asyncio
import sys

mcp = FastMCP("Horizon-MCP")


def _to_float(x, name: str):
    try:
        return float(x)
    except Exception:
        raise ValueError(f"{name} must be a number")


def _to_int(x, name: str):
    try:
        return int(x)
    except Exception:
        raise ValueError(f"{name} must be an integer")


@mcp.tool()
def geo_geocode_city(query: str, limit: int = 1):
    """Convert a place name into latitude/longitude using Open-Meteo Geocoding API."""
    if not query or not str(query).strip():
        return {"error": "query is required"}

    try:
        limit = _to_int(limit, "limit")
    except ValueError as e:
        return {"error": str(e)}

    if limit <= 0:
        limit = 1
    if limit > 5:
        limit = 5

    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={requests.utils.quote(str(query))}&count={limit}&language=en&format=json"
    )

    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return {"error": "Geocoding API request failed", "details": str(e)}

    results = data.get("results") or []
    out = []
    for item in results:
        out.append({
            "name": item.get("name"),
            "country": item.get("country"),
            "admin1": item.get("admin1"),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
            "timezone": item.get("timezone"),
            "population": item.get("population"),
        })

    return {"query": str(query), "count": len(out), "results": out}


@mcp.tool()
def weather_get_forecast(lat, lon, hours: int = 24):
    """
    Hourly forecast via Open-Meteo.
    Returns temp in Celsius and Fahrenheit.
    """
    try:
        lat = _to_float(lat, "lat")
        lon = _to_float(lon, "lon")
        hours = _to_int(hours, "hours")
    except ValueError as e:
        return {"error": str(e)}

    if hours <= 0:
        return {"error": "hours must be greater than 0"}

    # Keep payload small & avoid timeouts in LM Studio
    if hours > 24:
        hours = 24

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,cloud_cover,wind_speed_10m,precipitation"
        "&timezone=auto"
    )

    try:
        response = requests.get(url, timeout=12)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return {"error": "Weather API request failed", "details": str(e)}

    hourly = data.get("hourly", {})
    times = (hourly.get("time") or [])[:hours]
    temps = (hourly.get("temperature_2m") or [])[:hours]
    clouds = (hourly.get("cloud_cover") or [])[:hours]
    winds = (hourly.get("wind_speed_10m") or [])[:hours]
    prec = (hourly.get("precipitation") or [])[:hours]

    output = []
    for i in range(len(times)):
        temp_c = temps[i] if i < len(temps) else None
        temp_f = (temp_c * 9 / 5) + 32 if temp_c is not None else None

        output.append({
            "time": times[i],
            "temp_c": round(temp_c, 2) if temp_c is not None else None,
            "temp_f": round(temp_f, 2) if temp_f is not None else None,
            "cloud_cover_pct": clouds[i] if i < len(clouds) else None,
            "wind_kmh": winds[i] if i < len(winds) else None,
            "precip_mm": prec[i] if i < len(prec) else None,
            "server_signature": "v6-stdio-safe"
        })

    return {"lat": lat, "lon": lon, "hours": hours, "hourly": output}


@mcp.tool()
def mission_recommend_windows(
    query: str,
    hours_ahead: int = 12,
    max_cloud_pct: int = 30,
    max_wind_kmh: float = 20.0
):
    """
    Recommend good time windows (top 10) using:
    geocode -> weather -> scoring by low clouds & low wind.
    """
    if not query or not str(query).strip():
        return {"error": "query is required"}

    try:
        hours_ahead = _to_int(hours_ahead, "hours_ahead")
        max_cloud_pct = _to_int(max_cloud_pct, "max_cloud_pct")
        max_wind_kmh = _to_float(max_wind_kmh, "max_wind_kmh")
    except ValueError as e:
        return {"error": str(e)}

    if hours_ahead <= 0:
        return {"error": "hours_ahead must be > 0"}
    if hours_ahead > 24:
        hours_ahead = 24  # keep payload small

    if max_cloud_pct < 0:
        max_cloud_pct = 0
    if max_cloud_pct > 100:
        max_cloud_pct = 100

    geo = geo_geocode_city(str(query), limit=1)
    if "error" in geo:
        return geo
    if geo.get("count", 0) == 0:
        return {"error": f"No geocoding results for '{query}'"}

    loc = geo["results"][0]
    lat = loc["latitude"]
    lon = loc["longitude"]

    wx = weather_get_forecast(lat, lon, hours=hours_ahead)
    if "error" in wx:
        return wx

    windows = []
    for h in wx["hourly"]:
        cloud = h.get("cloud_cover_pct")
        wind = h.get("wind_kmh")
        if cloud is None or wind is None:
            continue

        ok = (cloud <= max_cloud_pct) and (wind <= max_wind_kmh)
        score = max(0.0, 100.0 - cloud - (2.0 * wind))

        if ok:
            windows.append({
                "time": h["time"],
                "score": round(score, 2),
                "cloud_cover_pct": cloud,
                "wind_kmh": wind,
                "temp_c": h.get("temp_c"),
                "temp_f": h.get("temp_f"),
                "reason": f"cloud<= {max_cloud_pct}% and wind<= {max_wind_kmh} km/h"
            })

    windows.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query": str(query),
        "resolved_location": loc,
        "constraints": {
            "hours_ahead": hours_ahead,
            "max_cloud_pct": max_cloud_pct,
            "max_wind_kmh": max_wind_kmh
        },
        "recommended_windows": windows[:10],
        "total_candidates": len(windows),
        "server_signature": "v6-stdio-safe"
    }


if __name__ == "__main__":
    # IMPORTANT: print to stderr only (stdout must stay clean for MCP stdio)
    print("Starting MCP server (stdio)...", file=sys.stderr)
    asyncio.run(mcp.run_stdio_async())