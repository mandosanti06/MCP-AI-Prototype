import math
import time
import re
from typing import Any, Dict, Tuple, List, Optional

import requests
from fastapi import FastAPI, Body

app = FastAPI(title="Ops Backend")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "OpsBackend/1.0"})


# -----------------------------
# Helpers (validation / math)
# -----------------------------
def _to_float(x, name: str) -> float:
    try:
        return float(x)
    except Exception:
        raise ValueError(f"{name} must be a number")


def _to_int(x, name: str) -> int:
    try:
        return int(x)
    except Exception:
        raise ValueError(f"{name} must be an integer")


def _validate_latlon(lat: float, lon: float):
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("lat must be in [-90, 90]")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("lon must be in [-180, 180]")


def extract_location(msg: str, payload: Dict[str, Any]) -> str:
    loc = (payload.get("location") or "").strip()
    if loc:
        return loc

    m = re.search(r"\bin\s+([a-zA-ZÀ-ÿ0-9\s,\-\.]{3,})\s*$", msg.strip(), re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return "San Francisco, CA"


# -----------------------------
# "Tools" (your MCP logic) as local functions
# -----------------------------
def geocode_osm(query: str, limit: int = 1) -> Dict[str, Any]:
    if not query or not query.strip():
        return {"error": "query required"}

    limit = max(1, min(5, int(limit)))
    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?q={requests.utils.quote(query)}&format=json&limit={limit}"
    )

    try:
        r = SESSION.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": "request failed", "details": str(e)}

    out = []
    for item in data:
        out.append({
            "display_name": item.get("display_name"),
            "lat": float(item.get("lat")),
            "lon": float(item.get("lon")),
        })
    return {"results": out}


def get_current_weather(lat: float, lon: float) -> Dict[str, Any]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&current_weather=true"
        "&timezone=auto"
    )
    try:
        r = SESSION.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": "request failed", "details": str(e)}
    return data.get("current_weather", {})


def forecast_hourly(lat: float, lon: float, hours: int = 12) -> Dict[str, Any]:
    hours = max(1, min(48, int(hours)))
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,precipitation,cloud_cover,wind_speed_10m"
        "&timezone=auto"
    )
    try:
        r = SESSION.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": "request failed", "details": str(e)}

    hourly = data.get("hourly", {})
    return {
        "time": (hourly.get("time") or [])[:hours],
        "temperature_2m": (hourly.get("temperature_2m") or [])[:hours],
        "cloud_cover": (hourly.get("cloud_cover") or [])[:hours],
        "wind_speed_10m": (hourly.get("wind_speed_10m") or [])[:hours],
        "precipitation": (hourly.get("precipitation") or [])[:hours],
        "timezone": data.get("timezone"),
    }


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> Dict[str, Any]:
    R = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    km = R * c
    return {"distance_km": round(km, 3)}


def eta_minutes(distance_km_val: float, speed_kmh: float) -> Dict[str, Any]:
    if speed_kmh <= 0:
        return {"error": "speed_kmh must be > 0"}
    minutes = (distance_km_val / speed_kmh) * 60.0
    return {"eta_minutes": round(minutes, 2)}


def fuel_required_liters(distance_km_val: float, consumption_l_per_100km: float) -> Dict[str, Any]:
    if consumption_l_per_100km <= 0:
        return {"error": "consumption_l_per_100km must be > 0"}
    liters = (distance_km_val / 100.0) * consumption_l_per_100km
    return {"fuel_needed_liters": round(liters, 2)}


def battery_runtime_minutes(battery_wh: float, load_w: float) -> Dict[str, Any]:
    if load_w <= 0:
        return {"error": "load_w must be > 0"}
    minutes = (battery_wh / load_w) * 60.0
    return {"runtime_minutes": round(minutes, 2)}


def pick_latlon(geo: Dict[str, Any]) -> Tuple[float, float]:
    if "error" in geo:
        raise RuntimeError(str(geo))
    results = geo.get("results") or []
    if not results:
        raise RuntimeError("no geocode results")
    return float(results[0]["lat"]), float(results[0]["lon"])


# -----------------------------
# Main chat handler (like yours)
# -----------------------------
def route_tools(msg: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    msg_l = msg.lower()
    location = extract_location(msg, payload)
    calls: List[Dict[str, Any]] = []

    if any(k in msg_l for k in ["weather", "rain", "wind", "forecast", "temp", "temperature"]):
        hours = 48 if "tomorrow" in msg_l else 24
        calls.append({"tool": "weather", "args": {"query": location, "hours": hours}})

    if any(k in msg_l for k in ["distance", "how far", "km between"]):
        a = payload.get("a")
        b = payload.get("b")
        if a and b:
            calls.append({"tool": "distance", "args": {"a": a, "b": b}})
        else:
            calls.append({"tool": "help", "args": {"hint": "Send payload.a and payload.b as {lat,lon} for distance."}})

    if any(k in msg_l for k in ["eta", "arrival", "how long", "travel time"]):
        if payload.get("distance_km") is not None and payload.get("speed_kmh") is not None:
            calls.append({"tool": "eta", "args": {"distance_km": payload["distance_km"], "speed_kmh": payload["speed_kmh"]}})
        else:
            calls.append({"tool": "help", "args": {"hint": "Send payload.distance_km and payload.speed_kmh for ETA."}})

    if any(k in msg_l for k in ["fuel", "liters", "l/100", "consumption"]):
        if payload.get("distance_km") is not None and payload.get("consumption_l_per_100km") is not None:
            calls.append({"tool": "fuel", "args": {"distance_km": payload["distance_km"], "consumption_l_per_100km": payload["consumption_l_per_100km"]}})
        else:
            calls.append({"tool": "help", "args": {"hint": "Send payload.distance_km and payload.consumption_l_per_100km for fuel."}})

    if any(k in msg_l for k in ["battery", "runtime", "wh", "watts"]):
        if payload.get("battery_wh") is not None and payload.get("load_w") is not None:
            calls.append({"tool": "battery", "args": {"battery_wh": payload["battery_wh"], "load_w": payload["load_w"]}})
        else:
            calls.append({"tool": "help", "args": {"hint": "Send payload.battery_wh and payload.load_w for runtime."}})

    if not calls:
        calls.append({"tool": "help", "args": {"hint": "Try: 'weather tomorrow in <city>' or provide payload for distance/eta/fuel/battery."}})
    return calls


def execute_tool_calls(tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    tools_used = []
    structured: Dict[str, Any] = {}
    errors: List[str] = []

    for call in tool_calls:
        tool = call["tool"]
        args = call.get("args", {})
        tools_used.append(tool)

        try:
            if tool == "weather":
                geo = geocode_osm(args["query"])
                lat, lon = pick_latlon(geo)
                structured["geo"] = geo
                structured["current_weather"] = get_current_weather(lat, lon)
                structured["weather"] = forecast_hourly(lat, lon, args.get("hours", 24))

            elif tool == "distance":
                a = args["a"]; b = args["b"]
                lat1 = _to_float(a["lat"], "a.lat"); lon1 = _to_float(a["lon"], "a.lon")
                lat2 = _to_float(b["lat"], "b.lat"); lon2 = _to_float(b["lon"], "b.lon")
                _validate_latlon(lat1, lon1); _validate_latlon(lat2, lon2)
                structured["distance"] = distance_km(lat1, lon1, lat2, lon2)

            elif tool == "eta":
                structured["eta"] = eta_minutes(_to_float(args["distance_km"], "distance_km"),
                                                _to_float(args["speed_kmh"], "speed_kmh"))

            elif tool == "fuel":
                structured["fuel"] = fuel_required_liters(_to_float(args["distance_km"], "distance_km"),
                                                          _to_float(args["consumption_l_per_100km"], "consumption"))

            elif tool == "battery":
                structured["battery"] = battery_runtime_minutes(_to_float(args["battery_wh"], "battery_wh"),
                                                                _to_float(args["load_w"], "load_w"))

            elif tool == "help":
                structured["help"] = {"message": args.get("hint", "")}

        except Exception as e:
            errors.append(f"{tool} failed: {e}")

    return {"tools_used": tools_used, "structured": structured, "errors": errors}


# -----------------------------
# Answer composer
# -----------------------------
def _summarize_weather(hourly: list, loc: str) -> str:
    """Build a human-readable weather summary from hourly forecast data."""
    if not hourly:
        return f"No weather data available for {loc}."

    temps_c = [h["temp_c"] for h in hourly if h.get("temp_c") is not None]
    temps_f = [h["temp_f"] for h in hourly if h.get("temp_f") is not None]
    winds = [h["wind_kmh"] for h in hourly if h.get("wind_kmh") is not None]
    clouds = [h["cloud_cover_pct"] for h in hourly if h.get("cloud_cover_pct") is not None]
    precip = [h["precip_mm"] for h in hourly if h.get("precip_mm") is not None]

    # Current conditions (first hour)
    now = hourly[0]
    parts = [f"🌍 Weather for {loc}:"]
    parts.append(f"Currently {now.get('temp_c', '?')}°C / {now.get('temp_f', '?')}°F"
                 f" with {now.get('cloud_cover_pct', '?')}% cloud cover"
                 f" and wind at {now.get('wind_kmh', '?')} km/h.")

    # Ranges over the forecast period
    if temps_c:
        parts.append(f"📊 {len(hourly)}h forecast — "
                     f"Temp: {min(temps_c)}°C–{max(temps_c)}°C "
                     f"({min(temps_f):.0f}°F–{max(temps_f):.0f}°F).")
    if winds:
        parts.append(f"💨 Wind: {min(winds)}–{max(winds)} km/h.")
    if precip:
        total_precip = sum(precip)
        if total_precip > 0:
            parts.append(f"🌧️ Expected precipitation: {total_precip:.1f} mm total.")
        else:
            parts.append("☀️ No precipitation expected.")
    if clouds:
        avg_cloud = sum(clouds) / len(clouds)
        if avg_cloud > 75:
            parts.append("☁️ Mostly cloudy skies.")
        elif avg_cloud > 40:
            parts.append("⛅ Partly cloudy skies.")
        else:
            parts.append("🌤️ Mostly clear skies.")

    return " ".join(parts)


def compose_answer(msg: str, payload: Dict[str, Any], result: Dict[str, Any]) -> str:
    s = result["structured"]
    parts: List[str] = []
    loc = (payload.get("location") or "").strip() or extract_location(msg, payload)

    if "current_weather" in s and isinstance(s["current_weather"], dict) and "temperature" in s["current_weather"]:
        cw = s["current_weather"]
        parts.append(f"Current weather for {loc}: {cw.get('temperature')}°C, wind {cw.get('windspeed')} km/h.")

    if "weather" in s:
        w = s["weather"]
        times = w.get("time") or []
        temps = w.get("temperature_2m") or []
        if times and temps:
            parts.append(f"Next hour: {times[0]} temp {temps[0]}°C.")
        else:
            parts.append(f"Forecast for {loc} retrieved.")

    if "distance" in s:
        parts.append(f"Distance: {s['distance'].get('distance_km')} km.")

    if "eta" in s:
        parts.append(f"ETA: {s['eta'].get('eta_minutes')} minutes.")

    if "fuel" in s:
        parts.append(f"Fuel needed: {s['fuel'].get('fuel_needed_liters')} L.")
        hourly = w.get("hourly", [])
        parts.append(_summarize_weather(hourly, loc))

    if "battery" in s:
        parts.append(f"Runtime: {s['battery'].get('runtime_minutes')} minutes.")
    if "windows" in s and s["windows"]:
        wins = s["windows"]
        best = wins[0]
        t = best.get("time") or best.get("start") or "unknown time"
        score = best.get("score")
        parts.append(f"🚀 Best launch window: {t}" + (f" (score {score}/100)." if score is not None else "."))
        if len(wins) > 1:
            parts.append(f"Found {len(wins)} suitable window(s) total.")

    if "help" in s:
        parts.append(s["help"]["message"])

    if result.get("errors"):
        parts.append(f"⚠️ Errors: {', '.join(result['errors'])}")

    return " ".join(parts) if parts else "Request processed."


def _resp(request_id: str, answer: str, start_time: float, tools_used=None, structured=None, errors=None):
    return {
        "request_id": request_id,
        "answer": answer,
        "tools_used": tools_used or [],
        "structured": structured or {},
        "errors": errors or [],
        "timing_ms": int((time.time() - start_time) * 1000),
    }


@app.post("/chat")
def chat(payload: Dict[str, Any] = Body(...)):
    start_time = time.time()
    request_id = str(payload.get("request_id") or "req-1")
    msg = (payload.get("message") or "").strip()
    if not msg:
        return _resp(request_id, "Invalid request.", start_time, errors=["message is required"])

    tool_calls = route_tools(msg, payload)
    result = execute_tool_calls(tool_calls)
    answer = compose_answer(msg, payload, result)

    return _resp(
        request_id,
        answer=answer,
        start_time=start_time,
        tools_used=result["tools_used"],
        structured=result["structured"],
        errors=result["errors"],
    )