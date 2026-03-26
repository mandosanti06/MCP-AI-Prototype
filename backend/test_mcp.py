
from mcp_client import call_tool

print(call_tool("geo_geocode_city", {
    "query": "Mayaguez",
    "limit": 1
}))