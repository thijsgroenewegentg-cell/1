import requests
import webbrowser
from datetime import datetime

def search_web(query: str, max_results: int = 5) -> str:
    """Use DuckDuckGo search (no API key needed)"""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            ddgs_results = list(ddgs.text(query, max_results=max_results))
            for r in ddgs_results:
                results.append(f"- {r['title']}: {r['body']} ({r['href']})")
        if not results:
            return f"No results found for '{query}', Sir."
        return f"Search results for '{query}', Sir:\n" + "\n\n".join(results)
    except ImportError:
        # Fallback: use DuckDuckGo html scraping via requests
        try:
            # Simple fallback
            resp = requests.get(f"https://api.duckduckgo.com/?q={query}&format=json", timeout=10)
            data = resp.json()
            abstract = data.get("AbstractText")
            if abstract:
                return f"DuckDuckGo summary for '{query}': {abstract}"
            
            # Last fallback
            return f"Search module not installed. Install duckduckgo-search: pip install duckduckgo-search. Query was: {query}"
        except Exception as e:
            return f"Search failed: {e}. Query: {query}"
    except Exception as e:
        return f"Web search error, Sir: {e}"

def get_weather(city: str, units: str = "metric") -> str:
    """Get weather via wttr.in (no API key)"""
    try:
        # wttr.in returns nice format
        url = f"https://wttr.in/{city}?format=j1"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "curl"})
        if resp.status_code == 200:
            data = resp.json()
            current = data['current_condition'][0]
            nearest = data['nearest_area'][0]['areaName'][0]['value'] if data.get('nearest_area') else city
            
            temp_c = current['temp_C']
            temp_f = current['temp_F']
            desc = current['weatherDesc'][0]['value']
            humidity = current['humidity']
            wind_kph = current['windspeedKmph']
            feels_c = current['FeelsLikeC']
            feels_f = current['FeelsLikeF']
            
            unit_str = "metric" if units == "metric" else "imperial"
            if units == "imperial":
                temp_display = f"{temp_f}°F (feels like {feels_f}°F)"
            else:
                temp_display = f"{temp_c}°C (feels like {feels_c}°C)"
            
            return f"""Weather in {nearest}, Sir:
- Condition: {desc}
- Temperature: {temp_display}
- Humidity: {humidity}%
- Wind: {wind_kph} km/h
"""
        else:
            # Fallback to formatted text
            text_resp = requests.get(f"https://wttr.in/{city}?format=3", timeout=10)
            return text_resp.text if text_resp.status_code == 200 else f"Could not fetch weather for {city}"
    except Exception as e:
        return f"Weather retrieval failed for {city}, Sir: {e}. Perhaps check the connection?"

def open_website(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    try:
        webbrowser.open(url)
        return f"Opening {url}, Sir."
    except Exception as e:
        return f"Could not open {url}: {e}"
