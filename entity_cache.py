import os
import time
import requests
import threading
import difflib
import logging
import re  # Required for dynamic text normalization

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_DURATION_SECONDS = 3600  # 60 minutes
last_fetch_time = 0

# The RAM Dictionary
ram_dictionary = {
    "branch": [],
    "brand": [],
    "category": [],
    "item": [],
    "state": [],
    "size": [],
    "color": [],
    "account": [],
    "vendor": [],
    "customer": []
}
def fetch_data_from_hana(query: str):
    """Helper to run a raw query and return a list of strings."""
    url = os.getenv("COMPANY_API_URL")
    #api_key = os.getenv("COMPANY_API_KEY")

    headers = {
        "QIKCHAT-API-KEY": "COMPANY_API_URL",
        "Content-Type": "text/plain"
    }
    try:
        response = requests.post(
            url,
            headers=headers,
            data=query.encode("utf-8"),
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
        
        data_list = data if isinstance(data, list) else data.get("value", data.get("results", []))
        return [str(list(row.values())[0]) for row in data_list if row and list(row.values())[0]]
    except Exception as e:
        logger.error(f"Cache Fetch Error: {e}")
        return []


def refresh_ram_dictionary():
    """Fetches unique values from SAP HANA and updates the dictionary."""
    global last_fetch_time, ram_dictionary
    
    logger.info("🔄 Refreshing SAP Entity Dictionary in background...")
    
    branches = fetch_data_from_hana('SELECT DISTINCT "WhsName" FROM "OWHS"')
    brands = fetch_data_from_hana('SELECT DISTINCT "U_Brand" FROM "OITB"')
    categories = fetch_data_from_hana('SELECT DISTINCT "U_GProp" FROM "OITB"')
    items = fetch_data_from_hana('SELECT DISTINCT "ItemName" FROM "OITM"')
    states = fetch_data_from_hana('SELECT DISTINCT "Location" FROM "OLCT"')
    sizes = fetch_data_from_hana('SELECT DISTINCT "U_SIZE" FROM "OITM"')
    colors = fetch_data_from_hana('SELECT DISTINCT "U_COLOR" FROM "OITM"')
    accounts = fetch_data_from_hana('SELECT DISTINCT "AcctName" FROM "OACT"')
    vendors = fetch_data_from_hana('SELECT DISTINCT "CardName" FROM "OCRD" WHERE "CardType" = \'S\'')
    customers = fetch_data_from_hana('SELECT DISTINCT "CardName" FROM "OCRD" WHERE "CardType" = \'C\'')
    
    ram_dictionary["branch"] = branches
    ram_dictionary["brand"] = brands
    ram_dictionary["category"] = categories
    ram_dictionary["item"] = items
    ram_dictionary["size"] = sizes
    ram_dictionary["state"] = states
    ram_dictionary["color"] = colors
    ram_dictionary["account"] = accounts
    ram_dictionary["vendor"] = vendors
    ram_dictionary["customer"] = customers

    last_fetch_time = time.time()
    logger.info("✅ SAP Entity Dictionary updated successfully.")
    
def ensure_cache_is_fresh():
    if time.time() - last_fetch_time > CACHE_DURATION_SECONDS:
        thread = threading.Thread(target=refresh_ram_dictionary)
        thread.start()

def smart_spell_check(entity_type: str, search_terms: list):
    """Uses dynamic Normalization against a list of AI-generated synonyms."""
    ensure_cache_is_fresh()
    
    entity_list = ram_dictionary.get(entity_type.lower(), [])
    print(f"--- 🔍 DICTIONARY DEBUG: Checking {search_terms} against {len(entity_list)} {entity_type}s ---")
    
    if not entity_list:
        return {"error": f"No data found for {entity_type}. (The RAM cache is empty!)"}
    
    def clean_text(text):
        """Removes all non-alphanumeric characters to create a pure comparison string."""
        return re.sub(r'[^a-z0-9]', '', text.lower())
        
    clean_to_original = {clean_text(item): item for item in entity_list}
    
    best_matches = []
            
   # Check every synonym Claude generated
    for term in search_terms:
        clean_search = clean_text(term)
        
        # 1. Exact case-insensitive match (highly likely if Claude guesses the abbreviation)
        if clean_search in clean_to_original:
            print(f"EXACT MATCH for '{term}' -> '{term}'")
            return {"status": "exact_match", "match": clean_to_original[clean_search]}
            
        # 2. Fuzzy Matching fallback
        close_clean_matches = difflib.get_close_matches(
            clean_search, 
            list(clean_to_original.keys()), 
            n=4, 
            cutoff=0.70
        )
        for m in close_clean_matches:
            best_matches.append(clean_to_original[m])
            
    # Deduplicate the results
    best_matches = list(set(best_matches))
    
    if len(best_matches) == 1:
        return {"status": "corrected", "match": best_matches[0]}
    elif len(best_matches) > 1:
        return {"status": "ambiguous", "options": best_matches}
    else:
        print(f"{search_terms} FAILED. SAP RAM cache sample: {entity_list[:5]}")
        return {"status": "not_found", "message": f"None of these terms {search_terms} matched."}