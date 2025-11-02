from flask import Flask, jsonify, request
from flask_cors import CORS
import requests, threading, time, orjson
from functools import lru_cache
import gzip

app = Flask(__name__)
CORS(app)

BASE_URL = "https://iptv-org.github.io/api"
DATA = {"channels": [], "streams": [], "streams_idx": {}, "logos_idx": {}, "countries": []}
SEARCH_INDEX = {}
COUNTRY_INDEX = {}
CATEGORY_INDEX = {}
LAST_UPDATE = 0
CACHE_DURATION = 3600 * 3

def fetch_all_data():
    global DATA, SEARCH_INDEX, COUNTRY_INDEX, CATEGORY_INDEX, LAST_UPDATE
    print("[INFO] Refreshing IPTV data...")
    urls = {
        "channels": f"{BASE_URL}/channels.json",
        "streams": f"{BASE_URL}/streams.json",
        "logos": f"{BASE_URL}/logos.json",
        "countries": f"{BASE_URL}/countries.json",
    }

    temp_data = {}
    try:
        # Parallel fetch with sessions (reuse connections)
        session = requests.Session()
        session.headers.update({'Accept-Encoding': 'gzip, deflate'})
        
        for key, url in urls.items():
            r = session.get(url, timeout=20)
            r.raise_for_status()
            temp_data[key] = r.json()
    except Exception as e:
        print(f"[ERROR] Data fetch failed: {e}")
        return

    # Build indexed structures for O(1) lookups
    streams_idx = {}
    for s in temp_data["streams"]:
        ch_id = s.get("channel")
        if ch_id not in streams_idx:
            streams_idx[ch_id] = []
        streams_idx[ch_id].append({
            "url": s["url"],
            "title": s.get("title"),
            "quality": s.get("quality"),
            "referrer": s.get("referrer"),
            "user_agent": s.get("user_agent"),
        })

    logos_idx = {}
    for l in temp_data["logos"]:
        ch_id = l.get("channel")
        if ch_id and ch_id not in logos_idx:
            logos_idx[ch_id] = l["url"]

    # Build optimized search index with pre-computed data
    search_idx = {}
    country_idx = {}
    category_idx = {}
    
    for ch in temp_data["channels"]:
        ch_id = ch["id"]
        name_lower = ch["name"].lower()
        
        # Pre-combine channel data for instant retrieval
        combined = {
            "id": ch_id,
            "name": ch["name"],
            "alt_names": ch.get("alt_names", []),
            "country": ch.get("country"),
            "network": ch.get("network"),
            "categories": ch.get("categories", []),
            "logo": logos_idx.get(ch_id),
            "streams": streams_idx.get(ch_id, []),
            "website": ch.get("website"),
            "is_nsfw": ch.get("is_nsfw", False),
            "launched": ch.get("launched"),
            "created_by": "https://t.me/zerodevbro",
        }
        
        search_idx[ch_id] = {
            "name": name_lower,
            "alt": [a.lower() for a in ch.get("alt_names", [])],
            "data": combined  # Store pre-combined data
        }
        
        # Country index
        country = ch.get("country")
        if country:
            if country not in country_idx:
                country_idx[country] = []
            country_idx[country].append(combined)
        
        # Category index
        for cat in ch.get("categories", []):
            if cat not in category_idx:
                category_idx[cat] = 0
            category_idx[cat] += 1

    # Atomic update
    DATA = {
        "channels": temp_data["channels"],
        "streams": temp_data["streams"],
        "streams_idx": streams_idx,
        "logos_idx": logos_idx,
        "countries": temp_data["countries"]
    }
    SEARCH_INDEX = search_idx
    COUNTRY_INDEX = country_idx
    CATEGORY_INDEX = category_idx
    LAST_UPDATE = time.time()
    print("[INFO] IPTV data updated successfully.")

def auto_refresh():
    while True:
        time.sleep(CACHE_DURATION)
        fetch_all_data()

threading.Thread(target=fetch_all_data, daemon=True).start()
threading.Thread(target=auto_refresh, daemon=True).start()

@app.route("/")
def home():
    return jsonify({
        "message": "🚀 IPTV Search API (Optimized for Koyeb)",
        "created_by": "https://t.me/zerodevbro",
        "uptime": f"{round((time.time() - LAST_UPDATE)/60, 1)} min since last data refresh",
        "endpoints": {
            "/api/search?q=<name>": "Search channels by name",
            "/api/country/<code>": "Get all channels by country",
            "/api/countries": "List all countries",
            "/api/channel/<id>": "Get channel details"
        }
    })

@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify({"error": "Missing ?q=", "created_by": "https://t.me/zerodevbro"}), 400

    results = []
    for ch_id, ch in SEARCH_INDEX.items():
        if q in ch["name"] or any(q in alt for alt in ch["alt"]):
            results.append(ch["data"])  # Direct retrieval, no combine needed
            if len(results) >= 50:
                break

    return app.response_class(
        response=orjson.dumps({
            "query": q,
            "results": len(results),
            "channels": results,
            "created_by": "https://t.me/zerodevbro"
        }),
        status=200,
        mimetype="application/json"
    )

@app.route("/api/countries")
def list_countries():
    counts = {code: len(channels) for code, channels in COUNTRY_INDEX.items()}
    
    countries = [
        {
            "code": c["code"],
            "name": c["name"],
            "flag": c.get("flag"),
            "channel_count": counts.get(c["code"], 0)
        }
        for c in DATA["countries"]
        if counts.get(c["code"], 0) > 0
    ]
    
    countries.sort(key=lambda x: x["channel_count"], reverse=True)
    return app.response_class(
        response=orjson.dumps({
            "total": len(countries),
            "countries": countries,
            "created_by": "https://t.me/zerodevbro"
        }),
        status=200,
        mimetype="application/json"
    )

@app.route("/api/country/<code>")
def by_country(code):
    code = code.upper()
    channels = COUNTRY_INDEX.get(code, [])[:50]  # Direct index lookup
    
    if not channels:
        return jsonify({"error": f"No channels found for {code}"}), 404
    
    return app.response_class(
        response=orjson.dumps({
            "country": code,
            "total": len(channels),
            "channels": channels,
            "created_by": "https://t.me/zerodevbro"
        }),
        status=200,
        mimetype="application/json"
    )

@app.route("/api/channel/<ch_id>")
def channel(ch_id):
    ch = SEARCH_INDEX.get(ch_id)
    if not ch:
        return jsonify({"error": "Channel not found"}), 404
    
    return app.response_class(
        response=orjson.dumps({
            "channel": ch["data"],
            "created_by": "https://t.me/zerodevbro"
        }),
        status=200,
        mimetype="application/json"
    )

@app.route("/api/categories")
def categories():
    result = [{"name": k, "count": v} for k, v in sorted(CATEGORY_INDEX.items(), key=lambda x: x[1], reverse=True)]
    return app.response_class(
        response=orjson.dumps({
            "total": len(result),
            "categories": result,
            "created_by": "https://t.me/zerodevbro"
        }),
        status=200,
        mimetype="application/json"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
