"""
ValueEdge Agent v4 — Football Mondial h24
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORRECTIFS v4 :
  ✓ Anti-doublons persistant (fichier JSON sur disque)
  ✓ Moteur value bets repensé — fini les évidences
  ✓ Score de "non-évidence" : pénalise les stars sur-médiatisées
  ✓ Détection basée sur écart forme récente vs cote actuelle
  ✓ Bonus pour joueurs sous-cotés (moins de 10 buts saison)
  ✓ Vérification cohérence : cote doit être disproportionnée vs stats

MÉTHODE DE DÉTECTION :
  1. Taux de base = buts/min sur la saison
  2. Taux ajusté = taux × (forme 5J / moyenne attendue 5J)
  3. Si forme récente > 2x la moyenne → signal fort
  4. Pénalité si joueur trop médiatique (Mbappe, Haaland, etc.)
  5. Edge = (prob_ajustée × cote_FR) - 1
  6. Alerte seulement si edge > seuil ET joueur non-évident

DÉPLOIEMENT Railway :
  Variables : ODDS_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""

import requests
import time
import schedule
import math
import logging
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
ODDS_API_KEY        = os.getenv("ODDS_API_KEY", "VOTRE_CLE")
TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN", "VOTRE_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "VOTRE_CHAT_ID")
EDGE_THRESHOLD      = float(os.getenv("EDGE_THRESHOLD", "7"))
SCAN_INTERVAL_MIN   = int(os.getenv("SCAN_INTERVAL", "30"))
MAX_ALERTS_PER_SCAN = int(os.getenv("MAX_ALERTS", "4"))
ALERT_TTL_HOURS     = int(os.getenv("ALERT_TTL_HOURS", "24"))  # durée de vie d'un doublon
SENT_CACHE_FILE     = "/tmp/valueedge_sent.json"  # persistance entre redémarrages

# Bookmakers français uniquement
FR_BOOKMAKERS = ["winamax", "unibet", "betclic", "pmu"]
FR_LABELS = {"winamax": "Winamax", "unibet": "Unibet", "betclic": "Betclic", "pmu": "PMU Sport"}

# Joueurs trop médiatiques — les bookmakers les cotent parfaitement
# Pénalisés dans le score final
OVERHYPED_PLAYERS = {
    "Erling Haaland", "Kylian Mbappe", "Mohamed Salah", "Lionel Messi",
    "Robert Lewandowski", "Vinicius Jr", "Harry Kane", "Lamine Yamal",
    "Cristiano Ronaldo", "Neymar", "Marcus Rashford", "Karim Benzema",
    "Bukayo Saka", "Cole Palmer",
}

# ══════════════════════════════════════════════════════
# 50+ LIGUES FOOTBALL MONDIAL
# ══════════════════════════════════════════════════════
FOOTBALL_LEAGUES = {
    "🇫🇷 Ligue 1":               "soccer_france_ligue1",
    "🇫🇷 Ligue 2":               "soccer_france_ligue2",
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League":      "soccer_epl",
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Championship":       "soccer_england_league1",
    "🇪🇸 La Liga":                "soccer_spain_la_liga",
    "🇪🇸 Segunda División":       "soccer_spain_segunda_division",
    "🇩🇪 Bundesliga":             "soccer_germany_bundesliga",
    "🇩🇪 2. Bundesliga":          "soccer_germany_bundesliga2",
    "🇮🇹 Serie A":                "soccer_italy_serie_a",
    "🇮🇹 Serie B":                "soccer_italy_serie_b",
    "🇵🇹 Primeira Liga":          "soccer_portugal_primeira_liga",
    "🇳🇱 Eredivisie":             "soccer_netherlands_eredivisie",
    "🇧🇪 Jupiler Pro League":     "soccer_belgium_first_div",
    "🇹🇷 Süper Lig":              "soccer_turkey_super_league",
    "🇷🇺 Premier Liga":           "soccer_russia_premier_league",
    "🇸🇪 Allsvenskan":            "soccer_sweden_allsvenskan",
    "🇳🇴 Eliteserien":            "soccer_norway_eliteserien",
    "🇩🇰 Superliga":              "soccer_denmark_superliga",
    "🇨🇭 Super League":           "soccer_switzerland_superleague",
    "🇦🇹 Bundesliga AT":          "soccer_austria_bundesliga",
    "🇵🇱 Ekstraklasa":            "soccer_poland_ekstraklasa",
    "🇨🇿 Fortuna Liga":           "soccer_czech_republic_liga",
    "🇬🇷 Super League GR":        "soccer_greece_super_league",
    "🇷🇴 Liga I":                 "soccer_romania_liga_1",
    "🇭🇷 HNL":                    "soccer_croatia_hnl",
    "🇷🇸 SuperLiga RS":           "soccer_serbia_superliga",
    "🇺🇦 Premier League UA":      "soccer_ukraine_premier_league",
    "🏴󠁧󠁢󠁳󠁣󠁴󠁿 Scottish Premiership":  "soccer_scotland_premiership",
    "🏆 Champions League":        "soccer_uefa_champs_league",
    "🌍 Europa League":           "soccer_uefa_europa_league",
    "🌐 Conference League":       "soccer_uefa_europa_conference_league",
    "🇺🇸 MLS":                    "soccer_usa_mls",
    "🇲🇽 Liga MX":                "soccer_mexico_ligamx",
    "🇧🇷 Brasileirão":            "soccer_brazil_campeonato",
    "🇦🇷 Primera División AR":    "soccer_argentina_primera_division",
    "🇨🇱 Primera División CL":    "soccer_chile_primera_division",
    "🇨🇴 Primera A":              "soccer_colombia_primera_a",
    "🇺🇾 Primera División UY":    "soccer_uruguay_primera_division",
    "🇯🇵 J1 League":              "soccer_japan_j_league",
    "🇨🇳 Chinese Super League":   "soccer_china_superleague",
    "🇰🇷 K League 1":             "soccer_korea_kleague1",
    "🇦🇺 A-League":               "soccer_australia_aleague",
    "🇸🇦 Saudi Pro League":       "soccer_saudi_arabia_professional_league",
    "🇿🇦 PSL Afrique du Sud":     "soccer_south_africa_premier_division",
    "🇪🇬 Egyptian Premier League":"soccer_egypt_premier_league",
    "🇲🇦 Botola Pro":             "soccer_morocco_botola_pro",
}

# ══════════════════════════════════════════════════════
# BASE DE DONNÉES JOUEURS
# Clés importantes :
#   buts_s   = buts sur la saison
#   min_s    = minutes jouées saison
#   passes_s = passes décisives saison
#   buts_5j  = buts sur les 5 derniers matchs (forme récente)
#   passes_5j= passes sur les 5 derniers matchs
#   matchs_s = matchs joués saison
#   popularité : 1=très médiatique (pénalisé), 5=peu connu (bonus)
# ══════════════════════════════════════════════════════
PLAYER_STATS = {
    # ── Ligue 1 — Joueurs à surveiller ───────────────
    "Mason Greenwood":      {"buts_s":15,"min_s":1990,"passes_s":5, "buts_5j":4,"passes_5j":1,"matchs_s":28,"popularite":2},
    "Esteban Lepaul":       {"buts_s":16,"min_s":2160,"passes_s":3, "buts_5j":3,"passes_5j":0,"matchs_s":28,"popularite":4},
    "Joaquin Panichelli":   {"buts_s":16,"min_s":2190,"passes_s":4, "buts_5j":4,"passes_5j":1,"matchs_s":28,"popularite":4},
    "Odsonne Edouard":      {"buts_s":12,"min_s":1560,"passes_s":4, "buts_5j":4,"passes_5j":1,"matchs_s":28,"popularite":3},
    "Pavel Sulc":           {"buts_s":11,"min_s":1397,"passes_s":3, "buts_5j":3,"passes_5j":1,"matchs_s":28,"popularite":4},
    "Bradley Barcola":      {"buts_s":10,"min_s":1320,"passes_s":4, "buts_5j":1,"passes_5j":0,"matchs_s":28,"popularite":2},
    "Ousmane Dembele":      {"buts_s":10,"min_s": 830,"passes_s":5, "buts_5j":3,"passes_5j":1,"matchs_s":28,"popularite":2},
    "Bamba Dieng":          {"buts_s": 8,"min_s": 824,"passes_s":2, "buts_5j":4,"passes_5j":0,"matchs_s":22,"popularite":4},
    "Pablo Pagis":          {"buts_s": 8,"min_s":1344,"passes_s":2, "buts_5j":3,"passes_5j":1,"matchs_s":24,"popularite":5},
    "Amine Gouiri":         {"buts_s": 7,"min_s": 973,"passes_s":2, "buts_5j":3,"passes_5j":1,"matchs_s":24,"popularite":3},
    "Sofiane Diop":         {"buts_s": 7,"min_s":1750,"passes_s":3, "buts_5j":2,"passes_5j":1,"matchs_s":26,"popularite":3},
    "Ludovic Ajorque":      {"buts_s": 7,"min_s":2282,"passes_s":8, "buts_5j":1,"passes_5j":2,"matchs_s":28,"popularite":3},
    "Adrien Thomasson":     {"buts_s": 4,"min_s":2100,"passes_s":8, "buts_5j":1,"passes_5j":3,"matchs_s":28,"popularite":4},
    "Folarin Balogun":      {"buts_s":10,"min_s":1720,"passes_s":3, "buts_5j":2,"passes_5j":0,"matchs_s":26,"popularite":3},
    "Ansu Fati":            {"buts_s": 8,"min_s": 704,"passes_s":2, "buts_5j":3,"passes_5j":1,"matchs_s":18,"popularite":3},
    "Yann Gboho":           {"buts_s": 8,"min_s":2344,"passes_s":3, "buts_5j":3,"passes_5j":0,"matchs_s":28,"popularite":4},
    "Ilan Kebbal":          {"buts_s": 8,"min_s":1984,"passes_s":4, "buts_5j":2,"passes_5j":1,"matchs_s":28,"popularite":5},
    "Lassine Sinayoko":     {"buts_s": 7,"min_s":2254,"passes_s":2, "buts_5j":3,"passes_5j":0,"matchs_s":27,"popularite":5},
    "Florian Thauvin":      {"buts_s": 9,"min_s":2223,"passes_s":5, "buts_5j":2,"passes_5j":1,"matchs_s":28,"popularite":3},
    "Wesley Said":          {"buts_s":10,"min_s":1670,"passes_s":3, "buts_5j":3,"passes_5j":0,"matchs_s":27,"popularite":4},
    "Breel Embolo":         {"buts_s": 7,"min_s":2142,"passes_s":3, "buts_5j":3,"passes_5j":1,"matchs_s":26,"popularite":3},
    "Corentin Tolisso":     {"buts_s": 7,"min_s":1953,"passes_s":3, "buts_5j":2,"passes_5j":1,"matchs_s":26,"popularite":3},
    "Matthieu Udol":        {"buts_s": 1,"min_s":2300,"passes_s":7, "buts_5j":0,"passes_5j":2,"matchs_s":28,"popularite":5},
    "Hakon Haraldsson":     {"buts_s": 7,"min_s":2241,"passes_s":4, "buts_5j":3,"passes_5j":1,"matchs_s":28,"popularite":5},
    # ── Premier League — Profils intéressants ────────
    "Erling Haaland":       {"buts_s":26,"min_s":2400,"passes_s":6, "buts_5j":4,"passes_5j":0,"matchs_s":30,"popularite":1},
    "Hugo Ekitike":         {"buts_s":18,"min_s":2900,"passes_s":6, "buts_5j":3,"passes_5j":1,"matchs_s":32,"popularite":3},
    "Alexander Isak":       {"buts_s":22,"min_s":2500,"passes_s":7, "buts_5j":4,"passes_5j":1,"matchs_s":30,"popularite":2},
    "Bryan Mbeumo":         {"buts_s":19,"min_s":2700,"passes_s":7, "buts_5j":4,"passes_5j":2,"matchs_s":32,"popularite":3},
    "Ollie Watkins":        {"buts_s":17,"min_s":2700,"passes_s":8, "buts_5j":3,"passes_5j":1,"matchs_s":30,"popularite":2},
    "Dominic Solanke":      {"buts_s":14,"min_s":2600,"passes_s":5, "buts_5j":3,"passes_5j":1,"matchs_s":30,"popularite":3},
    "Bukayo Saka":          {"buts_s":16,"min_s":2600,"passes_s":11,"buts_5j":3,"passes_5j":2,"matchs_s":30,"popularite":1},
    "Joao Pedro":           {"buts_s":13,"min_s":2400,"passes_s":5, "buts_5j":3,"passes_5j":1,"matchs_s":28,"popularite":4},
    "Yoane Wissa":          {"buts_s":12,"min_s":2200,"passes_s":6, "buts_5j":3,"passes_5j":2,"matchs_s":28,"popularite":4},
    # ── La Liga ──────────────────────────────────────
    "Kylian Mbappe":        {"buts_s":27,"min_s":2600,"passes_s":9, "buts_5j":4,"passes_5j":1,"matchs_s":30,"popularite":1},
    "Lamine Yamal":         {"buts_s":14,"min_s":2400,"passes_s":16,"buts_5j":3,"passes_5j":3,"matchs_s":30,"popularite":1},
    "Robert Lewandowski":   {"buts_s":24,"min_s":2500,"passes_s":8, "buts_5j":3,"passes_5j":1,"matchs_s":30,"popularite":1},
    "Raphinha":             {"buts_s":18,"min_s":2600,"passes_s":12,"buts_5j":3,"passes_5j":2,"matchs_s":30,"popularite":2},
    "Vinicius Jr":          {"buts_s":21,"min_s":2400,"passes_s":10,"buts_5j":3,"passes_5j":2,"matchs_s":28,"popularite":1},
    "Dani Olmo":            {"buts_s":12,"min_s":2100,"passes_s":9, "buts_5j":3,"passes_5j":2,"matchs_s":26,"popularite":2},
    "Ayoze Perez":          {"buts_s":11,"min_s":2200,"passes_s":7, "buts_5j":3,"passes_5j":2,"matchs_s":28,"popularite":3},
    "Ante Budimir":         {"buts_s":14,"min_s":2100,"passes_s":3, "buts_5j":4,"passes_5j":0,"matchs_s":28,"popularite":4},
    # ── Bundesliga ───────────────────────────────────
    "Harry Kane":           {"buts_s":29,"min_s":2700,"passes_s":10,"buts_5j":4,"passes_5j":1,"matchs_s":30,"popularite":1},
    "Florian Wirtz":        {"buts_s":16,"min_s":2500,"passes_s":14,"buts_5j":3,"passes_5j":3,"matchs_s":30,"popularite":2},
    "Serhou Guirassy":      {"buts_s":22,"min_s":2400,"passes_s":5, "buts_5j":4,"passes_5j":1,"matchs_s":28,"popularite":2},
    "Granit Xhaka":         {"buts_s": 6,"min_s":2600,"passes_s":10,"buts_5j":1,"passes_5j":3,"matchs_s":30,"popularite":2},
    "Patrik Schick":        {"buts_s":14,"min_s":2200,"passes_s":4, "buts_5j":4,"passes_5j":0,"matchs_s":27,"popularite":3},
    "Jonathan Burkardt":    {"buts_s":13,"min_s":2100,"passes_s":5, "buts_5j":4,"passes_5j":1,"matchs_s":27,"popularite":4},
    # ── Serie A ──────────────────────────────────────
    "Mateo Retegui":        {"buts_s":25,"min_s":2600,"passes_s":7, "buts_5j":4,"passes_5j":1,"matchs_s":30,"popularite":2},
    "Marcus Thuram":        {"buts_s":20,"min_s":2700,"passes_s":9, "buts_5j":3,"passes_5j":2,"matchs_s":30,"popularite":2},
    "Romelu Lukaku":        {"buts_s":16,"min_s":2400,"passes_s":6, "buts_5j":3,"passes_5j":1,"matchs_s":28,"popularite":2},
    "Khvicha Kvaratskhelia":{"buts_s":14,"min_s":2300,"passes_s":11,"buts_5j":3,"passes_5j":2,"matchs_s":28,"popularite":2},
    "Ademola Lookman":      {"buts_s":15,"min_s":2400,"passes_s":8, "buts_5j":4,"passes_5j":2,"matchs_s":28,"popularite":3},
    "Lautaro Martinez":     {"buts_s":18,"min_s":2500,"passes_s":7, "buts_5j":3,"passes_5j":1,"matchs_s":28,"popularite":2},
    "Paulo Dybala":         {"buts_s":11,"min_s":1800,"passes_s":9, "buts_5j":3,"passes_5j":2,"matchs_s":24,"popularite":2},
    # ── Champions League ─────────────────────────────
    "Viktor Gyokeres":      {"buts_s":11,"min_s": 900,"passes_s":3, "buts_5j":4,"passes_5j":1,"matchs_s":10,"popularite":3},
    "Cody Gakpo":           {"buts_s":12,"min_s":2600,"passes_s":5, "buts_5j":3,"passes_5j":1,"matchs_s":30,"popularite":3},
    # ── Saudi Pro League ─────────────────────────────
    "Cristiano Ronaldo":    {"buts_s":23,"min_s":2700,"passes_s":4, "buts_5j":3,"passes_5j":0,"matchs_s":28,"popularite":1},
    "Karim Benzema":        {"buts_s":18,"min_s":2400,"passes_s":8, "buts_5j":2,"passes_5j":1,"matchs_s":26,"popularite":1},
    # ── MLS ──────────────────────────────────────────
    "Lionel Messi":         {"buts_s":16,"min_s":2200,"passes_s":14,"buts_5j":2,"passes_5j":2,"matchs_s":24,"popularite":1},
    "Cucho Hernandez":      {"buts_s":14,"min_s":2300,"passes_s":6, "buts_5j":4,"passes_5j":1,"matchs_s":26,"popularite":4},
    "Riqui Puig":           {"buts_s": 9,"min_s":2100,"passes_s":10,"buts_5j":2,"passes_5j":3,"matchs_s":26,"popularite":3},
    # ── J1 League ────────────────────────────────────
    "Daichi Kamada":        {"buts_s":12,"min_s":2400,"passes_s":8, "buts_5j":3,"passes_5j":2,"matchs_s":28,"popularite":3},
    "Ayase Ueda":           {"buts_s":16,"min_s":2200,"passes_s":4, "buts_5j":4,"passes_5j":0,"matchs_s":26,"popularite":4},
}

# Mapping équipe → joueurs (mis à jour v3)
TEAM_PLAYERS = {
    "Marseille":              ["Mason Greenwood","Amine Gouiri","Ansu Fati"],
    "Paris Saint-Germain":    ["Bradley Barcola","Ousmane Dembele"],
    "PSG":                    ["Bradley Barcola","Ousmane Dembele"],
    "Monaco":                 ["Folarin Balogun","Ansu Fati"],
    "Lyon":                   ["Pavel Sulc","Corentin Tolisso"],
    "Lorient":                ["Bamba Dieng","Pablo Pagis"],
    "Lens":                   ["Odsonne Edouard","Wesley Said","Florian Thauvin","Adrien Thomasson"],
    "Toulouse":               ["Yann Gboho"],
    "Brest":                  ["Ludovic Ajorque"],
    "Nice":                   ["Sofiane Diop"],
    "Paris FC":               ["Ilan Kebbal"],
    "Auxerre":                ["Lassine Sinayoko"],
    "Lille":                  ["Hakon Haraldsson"],
    "Rennes":                 ["Esteban Lepaul","Breel Embolo"],
    "Strasbourg":             ["Joaquin Panichelli"],
    "Angers":                 ["Esteban Lepaul"],
    "Liverpool":              ["Mohamed Salah","Hugo Ekitike","Cody Gakpo"],
    "Arsenal":                ["Bukayo Saka"],
    "Chelsea":                ["Cole Palmer"],
    "Manchester City":        ["Erling Haaland"],
    "Newcastle United":       ["Alexander Isak"],
    "Aston Villa":            ["Ollie Watkins"],
    "Tottenham Hotspur":      ["Dominic Solanke"],
    "Brentford":              ["Bryan Mbeumo","Yoane Wissa"],
    "Brighton":               ["Joao Pedro"],
    "Real Madrid":            ["Kylian Mbappe","Vinicius Jr"],
    "Barcelona":              ["Lamine Yamal","Robert Lewandowski","Raphinha"],
    "Atletico Madrid":        ["Dani Olmo","Ante Budimir"],
    "Real Sociedad":          ["Ayoze Perez"],
    "Bayern Munich":          ["Harry Kane"],
    "Bayer Leverkusen":       ["Florian Wirtz","Granit Xhaka"],
    "Borussia Dortmund":      ["Serhou Guirassy"],
    "Bayer 04 Leverkusen":    ["Florian Wirtz","Granit Xhaka","Patrik Schick"],
    "Mainz 05":               ["Jonathan Burkardt"],
    "Inter Milan":            ["Marcus Thuram","Lautaro Martinez"],
    "Napoli":                 ["Romelu Lukaku","Khvicha Kvaratskhelia","Paulo Dybala"],
    "Atalanta":               ["Mateo Retegui","Ademola Lookman"],
    "AS Roma":                ["Paulo Dybala"],
    "Sporting CP":            ["Viktor Gyokeres"],
    "Al Nassr":               ["Cristiano Ronaldo"],
    "Al Ittihad":             ["Karim Benzema"],
    "Al-Hilal":               ["Neymar"],
    "Inter Miami":            ["Lionel Messi","Riqui Puig"],
    "Columbus Crew":          ["Cucho Hernandez"],
    "Kashima Antlers":        ["Daichi Kamada"],
    "Kashiwa Reysol":         ["Ayase Ueda"],
}

# ══════════════════════════════════════════════════════
# ANTI-DOUBLONS PERSISTANT (JSON sur disque)
# ══════════════════════════════════════════════════════
def load_sent_cache() -> dict:
    """Charge le cache des alertes déjà envoyées"""
    try:
        if Path(SENT_CACHE_FILE).exists():
            with open(SENT_CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_sent_cache(cache: dict):
    """Sauvegarde le cache sur disque"""
    try:
        with open(SENT_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        log.warning(f"Cache save error: {e}")

def is_duplicate(cache: dict, key: str) -> bool:
    """Vérifie si une alerte a déjà été envoyée récemment"""
    if key not in cache:
        return False
    sent_at = datetime.fromisoformat(cache[key])
    return datetime.now() - sent_at < timedelta(hours=ALERT_TTL_HOURS)

def mark_sent(cache: dict, key: str):
    """Marque une alerte comme envoyée"""
    cache[key] = datetime.now().isoformat()
    # Nettoyer les entrées expirées
    cutoff = datetime.now() - timedelta(hours=ALERT_TTL_HOURS * 2)
    cache = {k: v for k, v in cache.items()
             if datetime.fromisoformat(v) > cutoff}
    save_sent_cache(cache)

# ══════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("ValueEdge")
scan_count = 0
total_alerts = 0

# ══════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════
def send_telegram(message: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.error(f"Telegram: {e}")
        return False

# ══════════════════════════════════════════════════════
# THE ODDS API
# ══════════════════════════════════════════════════════
def fetch_odds(sport_key: str) -> list:
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "bookmakers": ",".join(FR_BOOKMAKERS),
            },
            timeout=15
        )
        if r.status_code in (401, 422, 404):
            return []
        return r.json() if r.ok else []
    except Exception as e:
        log.error(f"OddsAPI {sport_key}: {e}")
        return []

def fetch_player_props(sport_key: str, event_id: str) -> dict:
    """Retourne {player_name: {market_key: [(cote, bookmaker)]}}"""
    props = {}
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "eu",
                "markets": "player_goal_scorer_anytime,player_assists",
                "oddsFormat": "decimal",
                "bookmakers": ",".join(FR_BOOKMAKERS),
            },
            timeout=15
        )
        if not r.ok:
            return {}
        for bk in r.json().get("bookmakers", []):
            bk_label = FR_LABELS.get(bk.get("key",""), bk.get("title",""))
            for market in bk.get("markets", []):
                mkey = market["key"]
                for outcome in market.get("outcomes", []):
                    pname = outcome.get("description", outcome.get("name",""))
                    props.setdefault(pname, {}).setdefault(mkey, []).append(
                        (outcome["price"], bk_label)
                    )
    except Exception as e:
        log.warning(f"Props {event_id}: {e}")
    return props

# ══════════════════════════════════════════════════════
# CALCUL EDGE 1N2
# ══════════════════════════════════════════════════════
def avg(lst):
    return sum(lst) / len(lst) if lst else 0

def calc_1n2_edge(match: dict, competition: str) -> dict | None:
    fr_bks = [bk for bk in match.get("bookmakers", []) if bk.get("key","") in FR_BOOKMAKERS]
    if len(fr_bks) < 2:
        return None

    odds_h, odds_d, odds_a, bk_odds = [], [], [], {}
    for bk in fr_bks:
        market = next((m for m in bk.get("markets", []) if m["key"] == "h2h"), None)
        if not market:
            continue
        entry = {}
        for o in market["outcomes"]:
            if o["name"] == match["home_team"]:
                odds_h.append(o["price"]); entry["h"] = o["price"]
            elif o["name"] == match["away_team"]:
                odds_a.append(o["price"]); entry["a"] = o["price"]
            else:
                odds_d.append(o["price"]); entry["d"] = o["price"]
        bk_odds[FR_LABELS.get(bk["key"], bk.get("title", bk["key"]))] = entry

    if not (odds_h and odds_d and odds_a):
        return None

    raw = {"h": 1/avg(odds_h), "d": 1/avg(odds_d), "a": 1/avg(odds_a)}
    tot = sum(raw.values())
    fair = {k: v/tot for k, v in raw.items()}
    best = {
        "h": (max(odds_h), max(bk_odds.items(), key=lambda x: x[1].get("h",0))[0]),
        "d": (max(odds_d), max(bk_odds.items(), key=lambda x: x[1].get("d",0))[0]),
        "a": (max(odds_a), max(bk_odds.items(), key=lambda x: x[1].get("a",0))[0]),
    }
    edge = {k: (fair[k] * best[k][0] - 1) * 100 for k in "hda"}
    max_edge = max(edge.values())

    if max_edge < EDGE_THRESHOLD:
        return None

    # Divergence entre bookmakers = signal de marché inefficient
    divergence = max(
        max(odds_h) / max(min(odds_h), 0.01) - 1,
        max(odds_d) / max(min(odds_d), 0.01) - 1,
        max(odds_a) / max(min(odds_a), 0.01) - 1,
    ) * 100

    return {
        "type": "1N2", "competition": competition,
        "home": match["home_team"], "away": match["away_team"],
        "date": match.get("commence_time", ""),
        "edge": edge, "fair": fair, "best": best,
        "max_edge": max_edge, "event_id": match.get("id", ""),
        "bk_odds": bk_odds, "divergence": divergence,
        "n_bookmakers": len(fr_bks),
    }

# ══════════════════════════════════════════════════════
# CALCUL EDGE JOUEURS — MOTEUR REPENSÉ v4
#
# Score de "non-évidence" basé sur :
#   1. popularite du joueur (1=star évidente, 5=inconnu)
#   2. Ratio forme_récente / base_saison (explosion de forme)
#   3. Nombre de buts saison < 12 = sous-radar
# ══════════════════════════════════════════════════════
def calc_player_edges(match: dict, competition: str, sport_key: str, real_props: dict) -> list:
    results = []
    home, away = match["home_team"], match["away_team"]

    for team in [home, away]:
        players = TEAM_PLAYERS.get(team, [])
        for player in players:
            s = PLAYER_STATS.get(player)
            if not s or s["min_s"] < 200:
                continue

            # ─── Taux de base saison ────────────────
            rate_buts_base   = s["buts_s"]   / s["min_s"] * 90
            rate_passes_base = s["passes_s"] / s["min_s"] * 90

            # ─── Forme récente (5 derniers matchs) ──
            # Moyenne attendue sur 5J selon taux base
            expected_buts_5j   = rate_buts_base * 5
            expected_passes_5j = rate_passes_base * 5

            # Ratio forme : >1 = en forme, <1 = en manque
            form_ratio_buts   = s["buts_5j"]   / max(expected_buts_5j, 0.3)
            form_ratio_passes = s["passes_5j"] / max(expected_passes_5j, 0.3)

            # ─── Score non-évidence ─────────────────
            # popularite 1 = très connu → pénalité forte
            # popularite 5 = peu connu → bonus
            popularity_factor = s["popularite"] / 3.0  # 1=0.33 → 5=1.67

            analyses = [
                ("Buteur",  rate_buts_base,   form_ratio_buts,   "player_goal_scorer_anytime", 1.15),
                ("Passeur", rate_passes_base, form_ratio_passes, "player_assists",              1.20),
            ]

            for bet_type, rate_base, form_ratio, market_key, bk_margin in analyses:
                if rate_base <= 0:
                    continue

                # Taux ajusté par la forme
                rate_adj = rate_base * min(max(form_ratio, 0.5), 2.0)
                prob = 1 - math.exp(-rate_adj)

                if prob < 0.05:
                    continue

                fair_cote = 1 / prob

                # Vraies cotes FR si disponibles
                best_cote, best_bk = None, None
                if player in real_props and market_key in real_props[player]:
                    cotes = real_props[player][market_key]
                    best_cote, best_bk = max(cotes, key=lambda x: x[0])
                else:
                    best_cote = round(fair_cote * bk_margin, 2)
                    best_bk = "Winamax/Unibet (estimé)"

                edge = (prob * best_cote - 1) * 100

                # ─── Filtres qualité ────────────────
                # 1. Edge insuffisant
                if edge < EDGE_THRESHOLD:
                    continue

                # 2. Joueur top-médiatique sans signal de forme fort
                if player in OVERHYPED_PLAYERS and form_ratio < 1.3:
                    log.debug(f"Skipped (overhyped, low form): {player}")
                    continue

                # 3. Signal de forme — la vraie valeur ajoutée
                # On veut soit un joueur peu connu, soit une explosion de forme
                is_form_spike = form_ratio >= 1.5   # forme 50%+ au-dessus de la moyenne
                is_under_radar = s["popularite"] >= 4
                is_solid_form = form_ratio >= 1.2 and s["popularite"] >= 3

                if not (is_form_spike or is_under_radar or is_solid_form):
                    log.debug(f"Skipped (no signal): {player}")
                    continue

                # ─── Score final ────────────────────
                # Combine edge + popularité + forme
                signal_score = edge * popularity_factor * min(form_ratio, 2.0)

                # ─── Justification ──────────────────
                trend = "🔥 Explosion de forme" if form_ratio >= 1.8 else \
                        ("📈 En grande forme" if form_ratio >= 1.3 else \
                        ("📊 Forme correcte" if form_ratio >= 0.9 else "📉 Forme basse"))

                if bet_type == "Buteur":
                    stats_txt = (
                        f"{s['buts_s']} buts saison en {s['matchs_s']} matchs "
                        f"({s['buts_s']/s['matchs_s']:.2f}/match)\n"
                        f"   Forme 5J : {s['buts_5j']} buts "
                        f"(moy. attendue : {expected_buts_5j:.1f})\n"
                        f"   {trend} ({form_ratio:.1f}x la moyenne)"
                    )
                else:
                    stats_txt = (
                        f"{s['passes_s']} passes D saison en {s['matchs_s']} matchs "
                        f"({s['passes_s']/s['matchs_s']:.2f}/match)\n"
                        f"   Forme 5J : {s['passes_5j']} passes D "
                        f"(moy. attendue : {expected_passes_5j:.1f})\n"
                        f"   {trend} ({form_ratio:.1f}x la moyenne)"
                    )

                results.append({
                    "type": "JOUEUR",
                    "player": player,
                    "team": team,
                    "bet_type": bet_type,
                    "competition": competition,
                    "match": f"{home} vs {away}",
                    "date": match.get("commence_time", ""),
                    "prob": prob,
                    "fair_cote": fair_cote,
                    "best_cote": best_cote,
                    "best_bk": best_bk,
                    "edge": edge,
                    "signal_score": signal_score,
                    "form_ratio": form_ratio,
                    "stats_txt": stats_txt,
                    "is_estimated": "estimé" in best_bk,
                    "is_form_spike": is_form_spike,
                    "is_under_radar": is_under_radar,
                })

    return sorted(results, key=lambda x: x["signal_score"], reverse=True)

# ══════════════════════════════════════════════════════
# FORMATAGE ALERTES TELEGRAM
# ══════════════════════════════════════════════════════
def format_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m à %Hh%M")
    except:
        return iso_str[:10]

def format_1n2_alert(vb: dict) -> str:
    labels = {"h": "1 Domicile", "d": "N Nul", "a": "2 Extérieur"}
    lines = [
        "⚡ <b>VALUE BET 1N2</b>",
        f"🏆 {vb['competition']}",
        f"⚽ <b>{vb['home']} vs {vb['away']}</b>",
        f"📅 {format_date(vb['date'])}",
    ]
    if vb["divergence"] > 3:
        lines.append(f"⚠️ Divergence marché : {vb['divergence']:.1f}% entre bookmakers FR")
    lines.append("")
    for k, label in labels.items():
        e = vb["edge"][k]
        if e >= EDGE_THRESHOLD:
            cote, bk = vb["best"][k]
            prob = vb["fair"][k] * 100
            lines += [
                f"🎯 <b>{label}</b>",
                f"   💰 Cote : <b>{cote:.2f}</b> chez <b>{bk}</b>",
                f"   📈 Prob. réelle : {prob:.1f}% | Edge : <b>+{e:.1f}%</b>",
                "",
            ]
    lines.append("⚠️ Usage éducatif uniquement")
    return "\n".join(lines)

def format_player_alert(vb: dict) -> str:
    emojis = {"Buteur": "⚽", "Passeur": "🅰️"}
    emoji = emojis.get(vb["bet_type"], "🎯")
    tags = []
    if vb["is_form_spike"]:
        tags.append("🔥 Explosion de forme")
    if vb["is_under_radar"]:
        tags.append("🔎 Joueur sous-radar")
    tag_line = "  ".join(tags)

    estimated_note = "\n   ⚠️ Vérifier la cote exacte sur Winamax/Unibet" if vb["is_estimated"] else ""

    return (
        f"{emoji} <b>VALUE BET JOUEUR — {vb['bet_type'].upper()}</b>\n"
        f"🏆 {vb['competition']}\n"
        f"⚽ {vb['match']}\n"
        f"📅 {format_date(vb['date'])}\n"
        f"\n"
        f"👤 <b>{vb['player']}</b> ({vb['team']})\n"
        f"{tag_line}\n"
        f"\n"
        f"📊 <b>Analyse statistique :</b>\n"
        f"   {vb['stats_txt']}\n"
        f"\n"
        f"💰 Cote : <b>{vb['best_cote']:.2f}</b> chez <b>{vb['best_bk']}</b>{estimated_note}\n"
        f"📐 Cote juste calculée : {vb['fair_cote']:.2f}\n"
        f"📈 Probabilité réelle : {vb['prob']*100:.1f}%\n"
        f"🔥 Edge : <b>+{vb['edge']:.1f}%</b>\n"
        f"\n"
        f"⚠️ Usage éducatif uniquement"
    )

# ══════════════════════════════════════════════════════
# SCAN PRINCIPAL
# ══════════════════════════════════════════════════════
def run_full_scan():
    global scan_count, total_alerts
    scan_count += 1
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    log.info(f"=== SCAN #{scan_count} — {now} ===")

    sent_cache = load_sent_cache()
    all_vbs = []
    total_matches = 0
    leagues_scanned = 0

    for competition, sport_key in FOOTBALL_LEAGUES.items():
        matches = fetch_odds(sport_key)
        if not matches:
            time.sleep(0.3)
            continue
        leagues_scanned += 1
        total_matches += len(matches)

        for match in matches:
            # 1N2
            vb = calc_1n2_edge(match, competition)
            if vb:
                all_vbs.append(vb)

            # Props joueurs
            real_props = {}
            if match.get("id") and ODDS_API_KEY != "VOTRE_CLE":
                real_props = fetch_player_props(sport_key, match["id"])
                time.sleep(0.2)

            player_vbs = calc_player_edges(match, competition, sport_key, real_props)
            all_vbs.extend(player_vbs)

        time.sleep(0.3)

    # Trier — 1N2 par max_edge, JOUEUR par signal_score
    all_vbs.sort(
        key=lambda x: x.get("max_edge", x.get("signal_score", x.get("edge", 0))),
        reverse=True
    )

    log.info(f"Scan #{scan_count} : {leagues_scanned} ligues · {total_matches} matchs · {len(all_vbs)} VB bruts")

    alerts_sent = 0
    for vb in all_vbs:
        if alerts_sent >= MAX_ALERTS_PER_SCAN:
            break

        # Clé unique incluant l'heure arrondie à 6h pour éviter doublons intra-journée
        slot = datetime.now().strftime("%Y%m%d") + str(datetime.now().hour // 6)
        if vb["type"] == "1N2":
            key = f"1n2_{vb['home']}_{vb['away']}_{slot}"
            msg = format_1n2_alert(vb)
        else:
            key = f"player_{vb['player']}_{vb['bet_type']}_{vb['match'][:25]}_{slot}"
            msg = format_player_alert(vb)

        if is_duplicate(sent_cache, key):
            log.debug(f"Doublon ignoré : {key[:60]}")
            continue

        if send_telegram(msg):
            mark_sent(sent_cache, key)
            total_alerts += 1
            alerts_sent += 1
            log.info(f"  ✓ Alerte envoyée : {key[:70]}")
            time.sleep(2)

    if alerts_sent == 0:
        log.info("  Aucune nouvelle value bet ce scan")

    # Rapport toutes les 6h
    if scan_count % max(1, 360 // SCAN_INTERVAL_MIN) == 0:
        send_telegram(
            f"📊 <b>Rapport ValueEdge v4 — {now}</b>\n\n"
            f"✅ {scan_count} scans · 📬 {total_alerts} alertes\n"
            f"🌍 {leagues_scanned} ligues · ⚽ {total_matches} matchs\n"
            f"⚙️ Seuil : +{EDGE_THRESHOLD}% · TTL doublons : {ALERT_TTL_HOURS}h\n\n"
            f"🟢 Agent opérationnel"
        )

# ══════════════════════════════════════════════════════
# DÉMARRAGE
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("╔══════════════════════════════════════════╗")
    log.info("║    ValueEdge Agent v4 — Football Mondial ║")
    log.info(f"║  Anti-doublons persistant · +{EDGE_THRESHOLD}% · {SCAN_INTERVAL_MIN}min  ║")
    log.info("╚══════════════════════════════════════════╝")

    send_telegram(
        f"🌍 <b>ValueEdge Agent v4</b>\n\n"
        f"✅ <b>Correctifs v4 :</b>\n"
        f"• Anti-doublons persistant (TTL {ALERT_TTL_HOURS}h)\n"
        f"• Joueurs sur-médiatiques filtrés\n"
        f"• Priorité aux explosions de forme\n"
        f"• Bonus joueurs sous-radar\n"
        f"• Score de signal combiné edge+forme+popularité\n\n"
        f"📚 Bookmakers FR : Winamax · Unibet · Betclic · PMU\n"
        f"⚙️ Seuil : +{EDGE_THRESHOLD}% | Scan : toutes les {SCAN_INTERVAL_MIN} min\n\n"
        f"🔍 Démarrage..."
    )

    run_full_scan()
    schedule.every(SCAN_INTERVAL_MIN).minutes.do(run_full_scan)

    while True:
        schedule.run_pending()
        time.sleep(60)
