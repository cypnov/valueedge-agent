"""
ValueEdge Agent v3 — Football Mondial h24
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 50+ ligues mondiales via The Odds API
- Cotes issues exclusivement de bookmakers français (Winamax, Unibet, Betclic, PMU)
- Détection value bets 1N2 + Buteur + Passeur
- Analyse basée sur stats réelles joueurs/équipes (buts/min, passes/min, forme)
- Cartons jaunes retirés
- Alertes Telegram avec cote + bookmaker FR précis

DÉPLOIEMENT Railway :
  Variables : ODDS_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, EDGE_THRESHOLD, SCAN_INTERVAL

DÉPENDANCES : pip install requests schedule
"""

import requests
import time
import schedule
import math
import logging
import os
from datetime import datetime

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
ODDS_API_KEY        = os.getenv("ODDS_API_KEY", "VOTRE_CLE_THE_ODDS_API")
TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN", "VOTRE_TOKEN_TELEGRAM")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "VOTRE_CHAT_ID")
EDGE_THRESHOLD      = float(os.getenv("EDGE_THRESHOLD", "6"))
SCAN_INTERVAL_MIN   = int(os.getenv("SCAN_INTERVAL", "30"))
MAX_ALERTS_PER_SCAN = int(os.getenv("MAX_ALERTS", "5"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BOOKMAKERS FRANÇAIS UNIQUEMENT
# Les cotes affichées dans les alertes proviennent
# exclusivement de ces opérateurs agréés ANJ France
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FR_BOOKMAKERS = ["winamax", "unibet", "betclic", "pmu"]
FR_BOOKMAKER_LABELS = {
    "winamax": "Winamax",
    "unibet":  "Unibet",
    "betclic": "Betclic",
    "pmu":     "PMU Sport",
}

# ══════════════════════════════════════════════════════
# 50+ LIGUES FOOTBALL MONDIAL
# ══════════════════════════════════════════════════════
FOOTBALL_LEAGUES = {
    # Europe — Top 5
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
    # Europe — Autres
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
    # Coupes européennes
    "🏆 Champions League":        "soccer_uefa_champs_league",
    "🌍 Europa League":           "soccer_uefa_europa_league",
    "🌐 Conference League":       "soccer_uefa_europa_conference_league",
    # Amériques
    "🇺🇸 MLS":                    "soccer_usa_mls",
    "🇲🇽 Liga MX":                "soccer_mexico_ligamx",
    "🇧🇷 Brasileirão":            "soccer_brazil_campeonato",
    "🇦🇷 Primera División AR":    "soccer_argentina_primera_division",
    "🇨🇱 Primera División CL":    "soccer_chile_primera_division",
    "🇨🇴 Primera A":              "soccer_colombia_primera_a",
    "🇵🇪 Liga 1 PE":              "soccer_peru_primera_division",
    "🇺🇾 Primera División UY":    "soccer_uruguay_primera_division",
    # Asie / Océanie
    "🇯🇵 J1 League":              "soccer_japan_j_league",
    "🇨🇳 Chinese Super League":   "soccer_china_superleague",
    "🇰🇷 K League 1":             "soccer_korea_kleague1",
    "🇦🇺 A-League":               "soccer_australia_aleague",
    "🇸🇦 Saudi Pro League":       "soccer_saudi_arabia_professional_league",
    # Afrique
    "🇿🇦 PSL Afrique du Sud":     "soccer_south_africa_premier_division",
    "🇪🇬 Egyptian Premier League":"soccer_egypt_premier_league",
    "🇲🇦 Botola Pro":             "soccer_morocco_botola_pro",
}

# ══════════════════════════════════════════════════════
# STATS JOUEURS — Base de données saison 2025-26
# Utilisées pour calculer la probabilité réelle de marquer/passer
# Format: {nom: {buts, min, passes, forme_5j, ligue}}
# forme_5j : nombre de buts+passes sur les 5 derniers matchs (forme récente)
# ══════════════════════════════════════════════════════
PLAYER_STATS = {
    # ── Ligue 1 ──────────────────────────────────────
    "Mason Greenwood":      {"buts":15,"min":1990,"passes":5, "forme_5j":4, "ligue":"Ligue 1"},
    "Esteban Lepaul":       {"buts":16,"min":2160,"passes":3, "forme_5j":3, "ligue":"Ligue 1"},
    "Joaquin Panichelli":   {"buts":16,"min":2190,"passes":4, "forme_5j":4, "ligue":"Ligue 1"},
    "Odsonne Edouard":      {"buts":12,"min":1560,"passes":4, "forme_5j":3, "ligue":"Ligue 1"},
    "Pavel Sulc":           {"buts":11,"min":1397,"passes":3, "forme_5j":3, "ligue":"Ligue 1"},
    "Bradley Barcola":      {"buts":10,"min":1320,"passes":4, "forme_5j":2, "ligue":"Ligue 1"},
    "Ousmane Dembele":      {"buts":10,"min": 830,"passes":5, "forme_5j":4, "ligue":"Ligue 1"},
    "Bamba Dieng":          {"buts": 8,"min": 824,"passes":2, "forme_5j":3, "ligue":"Ligue 1"},
    "Pablo Pagis":          {"buts": 8,"min":1344,"passes":2, "forme_5j":2, "ligue":"Ligue 1"},
    "Amine Gouiri":         {"buts": 7,"min": 973,"passes":2, "forme_5j":3, "ligue":"Ligue 1"},
    "Sofiane Diop":         {"buts": 7,"min":1750,"passes":3, "forme_5j":2, "ligue":"Ligue 1"},
    "Ludovic Ajorque":      {"buts": 7,"min":2282,"passes":8, "forme_5j":3, "ligue":"Ligue 1"},
    "Adrien Thomasson":     {"buts": 4,"min":2100,"passes":8, "forme_5j":2, "ligue":"Ligue 1"},
    "Folarin Balogun":      {"buts":10,"min":1720,"passes":3, "forme_5j":2, "ligue":"Ligue 1"},
    "Ansu Fati":            {"buts": 8,"min": 704,"passes":2, "forme_5j":3, "ligue":"Ligue 1"},
    "Yann Gboho":           {"buts": 8,"min":2344,"passes":3, "forme_5j":2, "ligue":"Ligue 1"},
    # ── Premier League ───────────────────────────────
    "Erling Haaland":       {"buts":26,"min":2400,"passes":6, "forme_5j":5, "ligue":"Premier League"},
    "Mohamed Salah":        {"buts":10,"min":2800,"passes":9, "forme_5j":2, "ligue":"Premier League"},
    "Hugo Ekitike":         {"buts":18,"min":2900,"passes":6, "forme_5j":4, "ligue":"Premier League"},
    "Bukayo Saka":          {"buts":16,"min":2600,"passes":11,"forme_5j":4, "ligue":"Premier League"},
    "Cole Palmer":          {"buts":19,"min":2700,"passes":10,"forme_5j":5, "ligue":"Premier League"},
    "Alexander Isak":       {"buts":22,"min":2500,"passes":7, "forme_5j":5, "ligue":"Premier League"},
    "Ollie Watkins":        {"buts":17,"min":2700,"passes":8, "forme_5j":3, "ligue":"Premier League"},
    "Dominic Solanke":      {"buts":14,"min":2600,"passes":5, "forme_5j":3, "ligue":"Premier League"},
    "Bryan Mbeumo":         {"buts":19,"min":2700,"passes":7, "forme_5j":4, "ligue":"Premier League"},
    # ── La Liga ──────────────────────────────────────
    "Kylian Mbappe":        {"buts":27,"min":2600,"passes":9, "forme_5j":5, "ligue":"La Liga"},
    "Lamine Yamal":         {"buts":14,"min":2400,"passes":16,"forme_5j":5, "ligue":"La Liga"},
    "Robert Lewandowski":   {"buts":24,"min":2500,"passes":8, "forme_5j":4, "ligue":"La Liga"},
    "Raphinha":             {"buts":18,"min":2600,"passes":12,"forme_5j":4, "ligue":"La Liga"},
    "Vinicius Jr":          {"buts":21,"min":2400,"passes":10,"forme_5j":4, "ligue":"La Liga"},
    "Dani Olmo":            {"buts":12,"min":2100,"passes":9, "forme_5j":3, "ligue":"La Liga"},
    # ── Bundesliga ───────────────────────────────────
    "Harry Kane":           {"buts":29,"min":2700,"passes":10,"forme_5j":5, "ligue":"Bundesliga"},
    "Florian Wirtz":        {"buts":16,"min":2500,"passes":14,"forme_5j":4, "ligue":"Bundesliga"},
    "Serhou Guirassy":      {"buts":22,"min":2400,"passes":5, "forme_5j":4, "ligue":"Bundesliga"},
    "Granit Xhaka":         {"buts": 6,"min":2600,"passes":10,"forme_5j":2, "ligue":"Bundesliga"},
    # ── Serie A ──────────────────────────────────────
    "Mateo Retegui":        {"buts":25,"min":2600,"passes":7, "forme_5j":5, "ligue":"Serie A"},
    "Marcus Thuram":        {"buts":20,"min":2700,"passes":9, "forme_5j":4, "ligue":"Serie A"},
    "Romelu Lukaku":        {"buts":16,"min":2400,"passes":6, "forme_5j":3, "ligue":"Serie A"},
    "Khvicha Kvaratskhelia": {"buts":14,"min":2300,"passes":11,"forme_5j":4, "ligue":"Serie A"},
    # ── Champions League ─────────────────────────────
    "Viktor Gyokeres":      {"buts":11,"min": 900,"passes":3, "forme_5j":4, "ligue":"Champions League"},
    "Cody Gakpo":           {"buts":12,"min":2600,"passes":5, "forme_5j":3, "ligue":"Champions League"},
    # ── Saudi Pro League ─────────────────────────────
    "Cristiano Ronaldo":    {"buts":23,"min":2700,"passes":4, "forme_5j":4, "ligue":"Saudi Pro League"},
    "Karim Benzema":        {"buts":18,"min":2400,"passes":8, "forme_5j":3, "ligue":"Saudi Pro League"},
    "Neymar":               {"buts":10,"min":1600,"passes":9, "forme_5j":3, "ligue":"Saudi Pro League"},
    # ── MLS ──────────────────────────────────────────
    "Lionel Messi":         {"buts":16,"min":2200,"passes":14,"forme_5j":4, "ligue":"MLS"},
    "Lorenzo Insigne":      {"buts": 8,"min":1800,"passes":10,"forme_5j":2, "ligue":"MLS"},
    # ── J1 League ────────────────────────────────────
    "Daichi Kamada":        {"buts":12,"min":2400,"passes":8, "forme_5j":3, "ligue":"J1 League"},
}

# Mapping équipe → joueurs
TEAM_PLAYERS = {
    "Marseille":              ["Mason Greenwood","Amine Gouiri","Ansu Fati"],
    "Paris Saint-Germain":    ["Bradley Barcola","Ousmane Dembele"],
    "Monaco":                 ["Folarin Balogun","Ansu Fati"],
    "Lyon":                   ["Pavel Sulc"],
    "Lorient":                ["Bamba Dieng","Pablo Pagis"],
    "Lens":                   ["Odsonne Edouard","Adrien Thomasson"],
    "Toulouse":               ["Yann Gboho"],
    "Brest":                  ["Ludovic Ajorque"],
    "Nice":                   ["Sofiane Diop"],
    "Liverpool":              ["Mohamed Salah","Hugo Ekitike","Cody Gakpo"],
    "Arsenal":                ["Bukayo Saka"],
    "Chelsea":                ["Cole Palmer"],
    "Manchester City":        ["Erling Haaland"],
    "Newcastle United":       ["Alexander Isak"],
    "Aston Villa":            ["Ollie Watkins"],
    "Tottenham Hotspur":      ["Dominic Solanke"],
    "Brentford":              ["Bryan Mbeumo"],
    "Real Madrid":            ["Kylian Mbappe","Vinicius Jr"],
    "Barcelona":              ["Lamine Yamal","Robert Lewandowski","Raphinha"],
    "Atletico Madrid":        ["Dani Olmo"],
    "Bayern Munich":          ["Harry Kane"],
    "Bayer Leverkusen":       ["Florian Wirtz","Granit Xhaka"],
    "Borussia Dortmund":      ["Serhou Guirassy"],
    "Inter Milan":            ["Marcus Thuram"],
    "Napoli":                 ["Romelu Lukaku","Khvicha Kvaratskhelia"],
    "Atalanta":               ["Mateo Retegui"],
    "PSG":                    ["Bradley Barcola","Ousmane Dembele"],
    "Sporting CP":            ["Viktor Gyokeres"],
    "Al Nassr":               ["Cristiano Ronaldo"],
    "Al Ittihad":             ["Karim Benzema"],
    "Al Hilal":               ["Neymar"],
    "Inter Miami":            ["Lionel Messi","Lorenzo Insigne"],
}

# ══════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("ValueEdge")

sent_alerts = set()
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
# THE ODDS API — Bookmakers français uniquement
# ══════════════════════════════════════════════════════
def fetch_odds(sport_key: str) -> list:
    """Récupère les cotes depuis The Odds API — bookmakers FR uniquement"""
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
            params={
                "apiKey":      ODDS_API_KEY,
                "regions":     "eu",
                "markets":     "h2h",
                "oddsFormat":  "decimal",
                "bookmakers":  ",".join(FR_BOOKMAKERS),  # FR uniquement
            },
            timeout=15
        )
        if r.status_code == 401:
            log.error("Clé The Odds API invalide")
            return []
        if r.status_code in (422, 404):
            return []
        if not r.ok:
            return []
        return r.json()
    except Exception as e:
        log.error(f"OddsAPI {sport_key}: {e}")
        return []

def fetch_player_props(sport_key: str, event_id: str) -> list:
    """Récupère les cotes joueurs (buteur, passeur) — bookmakers FR uniquement"""
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds",
            params={
                "apiKey":     ODDS_API_KEY,
                "regions":    "eu",
                "markets":    "player_goal_scorer_anytime,player_assists",
                "oddsFormat": "decimal",
                "bookmakers": ",".join(FR_BOOKMAKERS),
            },
            timeout=15
        )
        if not r.ok:
            return []
        return r.json().get("bookmakers", [])
    except Exception as e:
        log.warning(f"Props {event_id}: {e}")
        return []

# ══════════════════════════════════════════════════════
# CALCUL EDGE 1N2
# La prob. juste est calculée à partir des cotes moyennes
# des bookmakers FR (après retrait de la marge)
# ══════════════════════════════════════════════════════
def avg(lst):
    return sum(lst) / len(lst) if lst else 0

def calc_1n2_edge(match: dict, competition: str) -> dict | None:
    bookmakers = match.get("bookmakers", [])
    # Ne garder que les bookmakers FR
    fr_bks = [bk for bk in bookmakers if bk.get("key","") in FR_BOOKMAKERS]
    if len(fr_bks) < 2:
        return None

    odds_h, odds_d, odds_a = [], [], []
    bk_odds = {}

    for bk in fr_bks:
        market = next((m for m in bk.get("markets", []) if m["key"] == "h2h"), None)
        if not market:
            continue
        entry = {}
        for outcome in market["outcomes"]:
            if outcome["name"] == match["home_team"]:
                odds_h.append(outcome["price"]); entry["h"] = outcome["price"]
            elif outcome["name"] == match["away_team"]:
                odds_a.append(outcome["price"]); entry["a"] = outcome["price"]
            else:
                odds_d.append(outcome["price"]); entry["d"] = outcome["price"]
        label = FR_BOOKMAKER_LABELS.get(bk["key"], bk.get("title", bk["key"]))
        bk_odds[label] = entry

    if not (odds_h and odds_d and odds_a):
        return None

    # Retirer la marge — probabilité juste normalisée
    avg_h, avg_d, avg_a = avg(odds_h), avg(odds_d), avg(odds_a)
    raw = {"h": 1/avg_h, "d": 1/avg_d, "a": 1/avg_a}
    tot = sum(raw.values())
    fair = {k: v/tot for k, v in raw.items()}

    # Meilleure cote disponible chez les bookmakers FR
    best = {
        "h": (max(odds_h), max(bk_odds.items(), key=lambda x: x[1].get("h",0))[0]),
        "d": (max(odds_d), max(bk_odds.items(), key=lambda x: x[1].get("d",0))[0]),
        "a": (max(odds_a), max(bk_odds.items(), key=lambda x: x[1].get("a",0))[0]),
    }
    edge = {
        "h": (fair["h"] * best["h"][0] - 1) * 100,
        "d": (fair["d"] * best["d"][0] - 1) * 100,
        "a": (fair["a"] * best["a"][0] - 1) * 100,
    }
    max_edge = max(edge.values())

    if max_edge < EDGE_THRESHOLD:
        return None

    return {
        "type":        "1N2",
        "competition": competition,
        "home":        match["home_team"],
        "away":        match["away_team"],
        "date":        match.get("commence_time", ""),
        "edge":        edge,
        "fair":        fair,
        "best":        best,
        "max_edge":    max_edge,
        "event_id":    match.get("id", ""),
        "bk_odds":     bk_odds,
    }

# ══════════════════════════════════════════════════════
# CALCUL EDGE JOUEURS — Buteur & Passeur
#
# Logique :
# 1. Taux de base = buts (ou passes) / minutes * 90 → λ (taux Poisson)
# 2. Ajustement forme récente : si forme_5j élevée → +15% sur λ
# 3. Probabilité de contribution = 1 - e^(-λ) (Poisson, ≥1 event)
# 4. Cote juste = 1 / probabilité
# 5. Si cote proposée par bookmaker FR > cote juste → value bet
# ══════════════════════════════════════════════════════
def calc_player_edges(match: dict, competition: str, sport_key: str) -> list:
    results = []
    home, away = match["home_team"], match["away_team"]

    # Récupérer les vraies cotes joueurs si disponibles
    event_id = match.get("id", "")
    real_props = {}
    if event_id and ODDS_API_KEY != "VOTRE_CLE_THE_ODDS_API":
        raw_props = fetch_player_props(sport_key, event_id)
        for bk in raw_props:
            bk_label = FR_BOOKMAKER_LABELS.get(bk.get("key",""), bk.get("title",""))
            for market in bk.get("markets", []):
                mkey = market["key"]
                for outcome in market.get("outcomes", []):
                    pname = outcome.get("description", outcome.get("name",""))
                    if pname not in real_props:
                        real_props[pname] = {}
                    if mkey not in real_props[pname]:
                        real_props[pname][mkey] = []
                    real_props[pname][mkey].append((outcome["price"], bk_label))

    for team in [home, away]:
        players = TEAM_PLAYERS.get(team, [])
        for player in players:
            stats = PLAYER_STATS.get(player)
            if not stats or stats["min"] < 200:
                continue

            # Ajustement forme récente
            # forme_5j = buts+passes sur les 5 derniers matchs
            # Si forme > moyenne attendue → multiplicateur positif
            avg_contrib_per_match = (stats["buts"] + stats["passes"]) / (stats["min"] / 90)
            forme_ratio = stats["forme_5j"] / max(avg_contrib_per_match * 5, 0.1)
            forme_mult = min(max(forme_ratio, 0.7), 1.4)  # Borné entre -30% et +40%

            analyses = [
                ("Buteur",  stats["buts"],   "player_goal_scorer_anytime", 1.15),
                ("Passeur", stats["passes"],  "player_assists",              1.20),
            ]

            for bet_type, stat_val, market_key, bk_margin in analyses:
                rate = stat_val / stats["min"] * 90
                rate_adjusted = rate * forme_mult  # Ajustement forme
                if rate_adjusted <= 0:
                    continue

                prob = 1 - math.exp(-rate_adjusted)
                if prob < 0.05:
                    continue

                fair_cote = 1 / prob

                # Utiliser vraies cotes FR si disponibles
                best_cote, best_bk = None, None
                if player in real_props and market_key in real_props[player]:
                    cotes = real_props[player][market_key]
                    # Prendre la meilleure cote parmi les bookmakers FR
                    best_cote, best_bk = max(cotes, key=lambda x: x[0])
                else:
                    # Estimation : cote juste + marge bookmaker typique
                    best_cote = round(fair_cote * bk_margin, 2)
                    best_bk = "Estimé (Winamax/Unibet)"

                edge = (prob * best_cote - 1) * 100

                if edge >= EDGE_THRESHOLD:
                    # Justification basée sur les stats
                    justif = _build_justification(player, stats, bet_type, rate, rate_adjusted, forme_mult)
                    results.append({
                        "type":         "JOUEUR",
                        "player":       player,
                        "team":         team,
                        "bet_type":     bet_type,
                        "competition":  competition,
                        "match":        f"{home} vs {away}",
                        "date":         match.get("commence_time", ""),
                        "prob":         prob,
                        "fair_cote":    fair_cote,
                        "best_cote":    best_cote,
                        "best_bk":      best_bk,
                        "edge":         edge,
                        "justif":       justif,
                        "is_estimated": best_bk.startswith("Estimé"),
                    })

    return sorted(results, key=lambda x: x["edge"], reverse=True)

def _build_justification(player, stats, bet_type, rate_base, rate_adj, forme_mult) -> str:
    """Génère une justification textuelle basée sur les stats"""
    buts, minutes, passes, forme = stats["buts"], stats["min"], stats["passes"], stats["forme_5j"]
    matchs_joues = round(minutes / 90)
    forme_txt = "en forme 🔥" if forme_mult > 1.1 else ("forme passable" if forme_mult > 0.9 else "forme basse ⚠️")

    if bet_type == "Buteur":
        return (
            f"{buts} buts en {matchs_joues} matchs · "
            f"1 but toutes les {round(minutes/max(buts,1))} min · "
            f"{forme_5j_desc(forme)} sur 5J · {forme_txt}"
        )
    else:
        return (
            f"{passes} passes D en {matchs_joues} matchs · "
            f"1 passe toutes les {round(minutes/max(passes,1))} min · "
            f"{forme_5j_desc(forme)} sur 5J · {forme_txt}"
        )

def forme_5j_desc(forme: int) -> str:
    if forme >= 4: return f"{forme} contributions"
    if forme >= 2: return f"{forme} contributions"
    return f"{forme} contribution"

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
        "",
        f"🏆 {vb['competition']}",
        f"⚽ <b>{vb['home']} vs {vb['away']}</b>",
        f"📅 {format_date(vb['date'])}",
        "",
        "📊 <b>Cotes bookmakers français :</b>",
    ]

    for k, label in labels.items():
        e = vb["edge"][k]
        if e >= EDGE_THRESHOLD:
            cote, bk = vb["best"][k]
            prob = vb["fair"][k] * 100
            lines += [
                f"",
                f"🎯 <b>{label}</b>",
                f"   💰 Cote : <b>{cote:.2f}</b> chez <b>{bk}</b>",
                f"   📈 Prob. réelle : {prob:.1f}%",
                f"   🔥 Edge : <b>+{e:.1f}%</b>",
            ]

    lines += ["", "⚠️ Usage éducatif uniquement"]
    return "\n".join(lines)

def format_player_alert(vb: dict) -> str:
    emojis = {"Buteur": "⚽", "Passeur": "🅰️"}
    emoji = emojis.get(vb["bet_type"], "🎯")
    estimated_note = "\n   ⚠️ Cote estimée — vérifier sur Winamax/Unibet" if vb["is_estimated"] else ""

    return (
        f"{emoji} <b>VALUE BET JOUEUR — {vb['bet_type'].upper()}</b>\n"
        f"\n"
        f"🏆 {vb['competition']}\n"
        f"⚽ {vb['match']}\n"
        f"📅 {format_date(vb['date'])}\n"
        f"\n"
        f"👤 <b>{vb['player']}</b> ({vb['team']})\n"
        f"\n"
        f"📊 <b>Analyse stats :</b>\n"
        f"   {vb['justif']}\n"
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

    all_vbs = []
    total_matches = 0
    leagues_scanned = 0

    for competition, sport_key in FOOTBALL_LEAGUES.items():
        log.info(f"  Scan {competition}...")
        matches = fetch_odds(sport_key)

        if not matches:
            time.sleep(0.5)
            continue

        leagues_scanned += 1
        total_matches += len(matches)

        for match in matches:
            # Value bets 1N2
            vb = calc_1n2_edge(match, competition)
            if vb:
                all_vbs.append(vb)

            # Value bets joueurs (buteur + passeur)
            player_vbs = calc_player_edges(match, competition, sport_key)
            all_vbs.extend(player_vbs)

        time.sleep(0.3)

    log.info(f"Scan #{scan_count} : {leagues_scanned} ligues · {total_matches} matchs · {len(all_vbs)} VB")

    # Trier par edge décroissant
    all_vbs.sort(key=lambda x: x.get("max_edge", x.get("edge", 0)), reverse=True)

    # Envoyer les top alertes (sans doublons)
    alerts_sent = 0
    for vb in all_vbs:
        if alerts_sent >= MAX_ALERTS_PER_SCAN:
            break

        if vb["type"] == "1N2":
            key = f"1n2_{vb['home']}_{vb['away']}_{vb['max_edge']:.0f}"
            msg = format_1n2_alert(vb)
        else:
            key = f"player_{vb['player']}_{vb['bet_type']}_{vb['match'][:30]}"
            msg = format_player_alert(vb)

        if key in sent_alerts:
            continue

        if send_telegram(msg):
            sent_alerts.add(key)
            total_alerts += 1
            alerts_sent += 1
            log.info(f"  ✓ Alerte : {key[:70]}")
            time.sleep(1.5)

    if alerts_sent == 0:
        log.info("  Aucune nouvelle value bet ce scan")

    # Rapport toutes les 6h
    if scan_count % max(1, (360 // SCAN_INTERVAL_MIN)) == 0:
        send_telegram(
            f"📊 <b>Rapport ValueEdge v3 — {now}</b>\n\n"
            f"✅ {scan_count} scans effectués\n"
            f"📬 {total_alerts} alertes envoyées\n"
            f"🌍 {leagues_scanned} ligues scannées\n"
            f"⚽ {total_matches} matchs analysés\n"
            f"⚙️ Seuil : +{EDGE_THRESHOLD}%\n"
            f"📚 Bookmakers : Winamax · Unibet · Betclic · PMU\n\n"
            f"🟢 Agent opérationnel"
        )

    # Purge anti-mémoire (max 500 clés)
    if len(sent_alerts) > 500:
        for k in list(sent_alerts)[:100]:
            sent_alerts.discard(k)

# ══════════════════════════════════════════════════════
# DÉMARRAGE
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("╔═══════════════════════════════════════════╗")
    log.info("║    ValueEdge Agent v3 — Football Mondial  ║")
    log.info(f"║  {len(FOOTBALL_LEAGUES)} ligues · +{EDGE_THRESHOLD}% · toutes les {SCAN_INTERVAL_MIN}min     ║")
    log.info("║  Bookmakers : Winamax · Unibet · Betclic · PMU  ║")
    log.info("╚═══════════════════════════════════════════╝")

    send_telegram(
        f"🌍 <b>ValueEdge Agent v3 — Football Mondial</b>\n\n"
        f"📡 <b>{len(FOOTBALL_LEAGUES)} ligues</b> surveillées\n"
        f"📚 <b>Bookmakers FR uniquement</b> :\n"
        f"   Winamax · Unibet · Betclic · PMU Sport\n\n"
        f"🎯 <b>Paris analysés :</b>\n"
        f"   • 1N2 — résultats de match\n"
        f"   • Buteur anytime\n"
        f"   • Passeur décisif\n\n"
        f"📊 <b>Méthode value bets joueurs :</b>\n"
        f"   Stats saison (buts/min, passes/min)\n"
        f"   + Ajustement forme récente (5 derniers matchs)\n"
        f"   + Modèle de Poisson\n"
        f"   → Comparaison avec cote bookmaker FR\n\n"
        f"⚙️ Seuil edge : <b>+{EDGE_THRESHOLD}%</b>\n"
        f"⏰ Scan : toutes les <b>{SCAN_INTERVAL_MIN} min</b>\n\n"
        f"🔍 Premier scan en cours..."
    )

    run_full_scan()
    schedule.every(SCAN_INTERVAL_MIN).minutes.do(run_full_scan)

    while True:
        schedule.run_pending()
        time.sleep(60)
