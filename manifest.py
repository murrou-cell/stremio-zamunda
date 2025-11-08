manifest = {
    "id": "org.zamunda.addon",
    "version": "1.0.1",
    "name": "Stremio Zamunda",
    "description": "Streams movies by scraping torrents from Zamunda.",
    "logo": "https://github.com/murrou-cell/zamunda-api/blob/main/logo/logo.jpg?raw=true",
    "resources": ["stream"], 
    "types": ["movie", "series"], 
    "idPrefixes": ["tt"], 
    "catalogs": [],
    "behaviorHints": {
        "configurable": True, 
        "configurationRequired": True,
    }
}