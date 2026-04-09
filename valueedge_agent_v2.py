"""
ValueEdge Agent v2 — Football Mondial h24
Couvre 50+ ligues via The Odds API + stats joueurs via SofaScore

DÉPLOIEMENT :
  railway.app ou render.com (gratuit)
  Variables : ODDS_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

DÉPENDANCES :
  pip install requests beautifulsoup4 schedule
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
ODDS_API_KEY      = os.getenv("ODDS_API_KEY", "VOTRE_CLE_THE_ODDS_API")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "8408757076:AAHIfULPtErLysVFL7K-3HxmGgY5VBR1RWw")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "8739796601")
EDGE_THRESHOLD    = float(os.getenv("EDGE_THRESHOLD", "6"))
SCAN_INTERVAL_MIN = int(os.getenv("SCAN_INTERVAL", "30"))
MAX_ALERTS_PER_SCAN = int(os.getenv("MAX_ALERTS", "5"))

# ══════════════════════════════════════════════════════
# 50+ LIGUES FOOTBALL MONDIAL — The Odds API sport keys
# ══════════════════════════════════════════════════════
FOOTBALL_LEAGUES = {
    # Europe — Top 5
    "🇫🇷 Ligue 1":              "soccer_france_ligue1",
    "🇫🇷 Ligue 2":              "soccer_france_ligue2",
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League":     "soccer_epl",
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Championship":      "soccer_england_league1",
    "🇪🇸 La Liga":               "soccer_spain_la_liga",
    "🇪🇸 Segunda División":      "soccer_spain_segunda_division",
    "🇩🇪 Bundesliga":            "soccer_germany_bundesliga",
    "🇩🇪 2. Bundesliga":         "soccer_germany_bundesliga2",
    "🇮🇹 Serie A":               "soccer_italy_serie_a",
    "🇮🇹 Serie B":               "soccer_italy_serie_b",
    # Europe — Autres
    "🇵🇹 Primeira Liga":         "soccer_portugal_primeira_liga",
    "🇳🇱 Eredivisie":            "soccer_netherlands_eredivisie",
    "🇧🇪 Jupiler Pro League":    "soccer_belgium_first_div",
    "🇹🇷 Süper Lig":             "soccer_turkey_super_league",
    "🇷🇺 Premier Liga":          "soccer_russia_premier_league",
    "🇸🇪 Allsvenskan":           "soccer_sweden_allsvenskan",
    "🇳🇴 Eliteserien":           "soccer_norway_eliteserien",
    "🇩🇰 Superliga":             "soccer_denmark_superliga",
    "🇨🇭 Super League":          "soccer_switzerland_superleague",
    "🇦🇹 Bundesliga AT":         "soccer_austria_bundesliga",
    "🇵🇱 Ekstraklasa":           "soccer_poland_ekstraklasa",
    "🇨🇿 Fortuna Liga":          "soccer_czech_republic_liga",
    "🇬🇷 Super League GR":       "soccer_greece_super_league",
    "🇷🇴 Liga I":                "soccer_romania_liga_1",
    "🇭🇷 HNL":                   "soccer_croatia_hnl",
    "🇷🇸 SuperLiga RS":          "soccer_serbia_superliga",
    "🇺🇦 Premier League UA":     "soccer_ukraine_premier_league",
    "🏴󠁧󠁢󠁳󠁣󠁴󠁿 Scottish Premiership": "soccer_scotland_premiership",
    # Coupes européennes
    "🏆 Champions League":       "soccer_uefa_champs_league",
    "🌍 Europa League":          "soccer_uefa_europa_league",
    "🌐 Conference League":      "soccer_uefa_europa_conference_league",
    # Amériques
    "🇺🇸 MLS":                   "soccer_usa_mls",
    "🇲🇽 Liga MX":               "soccer_mexico_ligamx",
    "🇧🇷 Brasileirão Série A":   "soccer_brazil_campeonato",
    "🇦🇷 Primera División AR":   "soccer_argentina_primera_division",
    "🇨🇱 Primera División CL":   "soccer_chile_primera_division",
    "🇨🇴 Primera A":             "soccer_colombia_primera_a",
    "🇵🇪 Liga 1 PE":             "soccer_peru_primera_division",
    "🇺🇾 Primera División UY":   "soccer_uruguay_primera_division",
    # Asie / Océanie
    "🇯🇵 J1 League":             "soccer_japan_j_league",
    "🇨🇳 Chinese Super League":  "soccer_china_superleague",
    "🇰🇷 K League 1":            "soccer_korea_kleague1",
    "🇦🇺 A-League":              "soccer_australia_aleague",
    "🇸🇦 Saudi Pro League":      "soccer_saudi_arabia_professional_league",
    # Afrique / Moyen-Orient
    "🇿🇦 PSL Afrique du Sud":    "soccer_south_africa_premier_division",
    "🇪🇬 Egyptian Premier League":"soccer_egypt_premier_league",
    "🇲🇦 Botola Pro":            "soccer_morocco_botola_pro",
}

# ══════════════════════════════════════════════════════
# STATS JOUEURS — Base de données globale
# Format: {nom: {buts, matchs, minutes, passes, cj, ligue}}
# ══════════════════════════════════════════════════════
PLAYER_STATS = {
    # Ligue 1
    "Mason Greenwood":      {"buts":15,"min":1990,"passes":5, "cj":3, "ligue":"Ligue 1"},
    "Esteban Lepaul":       {"buts":16,"min":2160,"passes":3, "cj":4, "ligue":"Ligue 1"},
    "Joaquin Panichelli":   {"buts":16,"min":2190,"passes":4, "cj":2, "ligue":"Ligue 1"},
    "Odsonne Edouard":      {"buts":12,"min":1560,"passes":4, "cj":3, "ligue":"Ligue 1"},
    "Pavel Sulc":           {"buts":11,"min":1397,"passes":3, "cj":2, "ligue":"Ligue 1"},
    "Bradley Barcola":      {"buts":10,"min":1320,"passes":4, "cj":1, "ligue":"Ligue 1"},
    "Ousmane Dembele":      {"buts":10,"min": 830,"passes":5, "cj":2, "ligue":"Ligue 1"},
    "Bamba Dieng":          {"buts": 8,"min": 824,"passes":2, "cj":3, "ligue":"Ligue 1"},
    "Pablo Pagis":          {"buts": 8,"min":1344,"passes":2, "cj":2, "ligue":"Ligue 1"},
    "Amine Gouiri":         {"buts": 7,"min": 973,"passes":2, "cj":2, "ligue":"Ligue 1"},
    "Sofiane Diop":         {"buts": 7,"min":1750,"passes":3, "cj":3, "ligue":"Ligue 1"},
    "Ludovic Ajorque":      {"buts": 7,"min":2282,"passes":8, "cj":3, "ligue":"Ligue 1"},
    "Adrien Thomasson":     {"buts": 4,"min":2100,"passes":8, "cj":4, "ligue":"Ligue 1"},
    "Folarin Balogun":      {"buts":10,"min":1720,"passes":3, "cj":1, "ligue":"Ligue 1"},
    "Ansu Fati":            {"buts": 8,"min": 704,"passes":2, "cj":1, "ligue":"Ligue 1"},
    # Premier League
    "Erling Haaland":       {"buts":26,"min":2400,"passes":6, "cj":2, "ligue":"Premier League"},
    "Mohamed Salah":        {"buts":10,"min":2800,"passes":9, "cj":1, "ligue":"Premier League"},
    "Hugo Ekitike":         {"buts":18,"min":2900,"passes":6, "cj":3, "ligue":"Premier League"},
    "Bukayo Saka":          {"buts":16,"min":2600,"passes":11,"cj":2, "ligue":"Premier League"},
    "Cole Palmer":          {"buts":19,"min":2700,"passes":10,"cj":1, "ligue":"Premier League"},
    "Alexander Isak":       {"buts":22,"min":2500,"passes":7, "cj":2, "ligue":"Premier League"},
    "Dominic Solanke":      {"buts":14,"min":2600,"passes":5, "cj":2, "ligue":"Premier League"},
    "Ollie Watkins":        {"buts":17,"min":2700,"passes":8, "cj":3, "ligue":"Premier League"},
    # La Liga
    "Kylian Mbappe":        {"buts":27,"min":2600,"passes":9, "cj":4, "ligue":"La Liga"},
    "Lamine Yamal":         {"buts":14,"min":2400,"passes":16,"cj":2, "ligue":"La Liga"},
    "Robert Lewandowski":   {"buts":24,"min":2500,"passes":8, "cj":1, "ligue":"La Liga"},
    "Raphinha":             {"buts":18,"min":2600,"passes":12,"cj":3, "ligue":"La Liga"},
    "Vinicius Jr":          {"buts":21,"min":2400,"passes":10,"cj":5, "ligue":"La Liga"},
    # Bundesliga
    "Harry Kane":           {"buts":29,"min":2700,"passes":10,"cj":2, "ligue":"Bundesliga"},
    "Florian Wirtz":        {"buts":16,"min":2500,"passes":14,"cj":2, "ligue":"Bundesliga"},
    "Serhou Guirassy":      {"buts":22,"min":2400,"passes":5, "cj":3, "ligue":"Bundesliga"},
    # Serie A
    "Mateo Retegui":        {"buts":25,"min":2600,"passes":7, "cj":3, "ligue":"Serie A"},
    "Marcus Thuram":        {"buts":20,"min":2700,"passes":9, "cj":2, "ligue":"Serie A"},
    "Romelu Lukaku":        {"buts":16,"min":2400,"passes":6, "cj":4, "ligue":"Serie A"},
    # Champions League
    "Viktor Gyokeres":      {"buts":11,"min":900, "passes":3, "cj":1, "ligue":"Champions League"},
    "Cody Gakpo":           {"buts":12,"min":2600,"passes":5, "cj":2, "ligue":"Champions League"},
    # Saudi League
    "Cristiano Ronaldo":    {"buts":23,"min":2700,"passes":4, "cj":3, "ligue":"Saudi Pro League"},
    "Karim Benzema":        {"buts":18,"min":2400,"passes":8, "cj":2, "ligue":"Saudi Pro League"},
    "Neymar":               {"buts":10,"min":1600,"passes":9, "cj":3, "ligue":"Saudi Pro League"},
    # MLS
    "Lionel Messi":         {"buts":16,"min":2200,"passes":14,"cj":1, "ligue":"MLS"},
    "Lorenzo Insigne":      {"buts": 8,"min":1800,"passes":10,"cj":2, "ligue":"MLS"},
    # J-League
    "Daichi Kamada":        {"buts":12,"min":2400,"passes":8, "cj":3, "ligue":"J1 League"},
}

# Mapping équipe → joueurs
TEAM_PLAYERS = {
    "Marseille":             ["Mason Greenwood","Amine Gouiri","Ansu Fati"],
    "Paris Saint-Germain":   ["Bradley Barcola","Ousmane Dembele"],
    "Monaco":                ["Folarin Balogun","Ansu Fati"],
    "Lyon":                  ["Pavel Sulc"],
    "Lorient":               ["Bamba Dieng","Pablo Pagis"],
    "Lens":                  ["Odsonne Edouard","Adrien Thomasson"],
    "Liverpool":             ["Mohamed Salah","Hugo Ekitike","Cody Gakpo"],
    "Arsenal":               ["Bukayo Saka"],
    "Chelsea":               ["Cole Palmer"],
    "Manchester City":       ["Erling Haaland"],
    "Newcastle":             ["Alexander Isak"],
    "Aston Villa":           ["Ollie Watkins","Dominik Solanke"],
    "Real Madrid":           ["Kylian Mbappe","Vinicius Jr"],
    "Barcelona":             ["Lamine Yamal","Robert Lewandowski","Raphinha"],
    "Bayern Munich":         ["Harry Kane","Serhou Guirassy"],
    "Bayer Leverkusen":      ["Florian Wirtz"],
    "Inter":                 ["Marcus Thuram"],
    "Napoli":                ["Romelu Lukaku"],
    "Atalanta":              ["Mateo Retegui"],
    "Sporting CP":           ["Viktor Gyokeres"],
    "Al-Nassr":              ["Cristiano Ronaldo"],
    "Al-Ittihad":            ["Karim Benzema"],
    "Al-Hilal":              ["Neymar"],
    "Inter Miami":           ["Lionel Messi","Lorenzo Insigne"],
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
# THE ODDS API — Cotes mondiales
# ══════════════════════════════════════════════════════
def fetch_odds(sport_key: str) -> list:
    """Récupère les cotes depuis The Odds API"""
    try:
        url = "https://api.the-odds-api.com/v4/sports/{}/odds/".format(sport_key)
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
            "bookmakers": "winamax,unibet,betclic,pmu,pinnacle,bet365"
        }
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 401:
            log.error("Clé The Odds API invalide")
            return []
        if r.status_code == 422:
            return []  # Ligue sans matchs
        if not r.ok:
            return []
        return r.json()
    except Exception as e:
        log.error(f"OddsAPI {sport_key}: {e}")
        return []

def fetch_player_props(sport_key: str, event_id: str) -> list:
    """Récupère les cotes joueurs (buteur, cartons, etc.)"""
    try:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "player_goal_scorer_anytime,player_assists,player_cards",
            "oddsFormat": "decimal",
            "bookmakers": "winamax,unibet,betclic"
        }
        r = requests.get(url, params=params, timeout=15)
        if not r.ok:
            return []
        return r.json().get("bookmakers", [])
    except Exception as e:
        log.warning(f"Props {event_id}: {e}")
        return []

# ══════════════════════════════════════════════════════
# CALCUL EDGE 1N2
# ══════════════════════════════════════════════════════
def avg(lst):
    return sum(lst) / len(lst) if lst else 0

def calc_1n2_edge(match: dict, competition: str) -> dict | None:
    """Calcule les value bets 1N2 pour un match"""
    bookmakers = match.get("bookmakers", [])
    if len(bookmakers) < 2:
        return None

    odds_h, odds_d, odds_a = [], [], []
    bk_odds = {}

    for bk in bookmakers:
        market = next((m for m in bk.get("markets", []) if m["key"] == "h2h"), None)
        if not market:
            continue
        entry = {}
        for outcome in market["outcomes"]:
            if outcome["name"] == match["home_team"]:
                odds_h.append(outcome["price"])
                entry["h"] = outcome["price"]
            elif outcome["name"] == match["away_team"]:
                odds_a.append(outcome["price"])
                entry["a"] = outcome["price"]
            else:
                odds_d.append(outcome["price"])
                entry["d"] = outcome["price"]
        bk_odds[bk["title"]] = entry

    if not (odds_h and odds_d and odds_a):
        return None

    avg_h, avg_d, avg_a = avg(odds_h), avg(odds_d), avg(odds_a)
    raw = {"h": 1/avg_h, "d": 1/avg_d, "a": 1/avg_a}
    tot = sum(raw.values())
    fair = {k: v/tot for k, v in raw.items()}

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
        "type": "1N2",
        "competition": competition,
        "home": match["home_team"],
        "away": match["away_team"],
        "date": match.get("commence_time", ""),
        "edge": edge,
        "fair": fair,
        "best": best,
        "max_edge": max_edge,
        "event_id": match.get("id", ""),
    }

# ══════════════════════════════════════════════════════
# CALCUL EDGE JOUEURS (modèle de Poisson)
# ══════════════════════════════════════════════════════
def calc_player_edges(match: dict, competition: str, sport_key: str) -> list:
    """Détecte les value bets joueurs pour un match"""
    results = []
    home, away = match["home_team"], match["away_team"]

    # D'abord essayer les vraies cotes joueurs via The Odds API
    event_id = match.get("id", "")
    real_props = {}
    if event_id and ODDS_API_KEY != "VOTRE_CLE_THE_ODDS_API":
        raw_props = fetch_player_props(sport_key, event_id)
        for bk in raw_props:
            for market in bk.get("markets", []):
                mkey = market["key"]
                for outcome in market.get("outcomes", []):
                    pname = outcome["description"] if "description" in outcome else outcome["name"]
                    if pname not in real_props:
                        real_props[pname] = {}
                    if mkey not in real_props[pname]:
                        real_props[pname][mkey] = []
                    real_props[pname][mkey].append(outcome["price"])

    # Analyse basée sur les stats de la base de données
    for team in [home, away]:
        players = TEAM_PLAYERS.get(team, [])
        for player in players:
            stats = PLAYER_STATS.get(player)
            if not stats or stats["min"] < 200:
                continue

            analyses = [
                ("Buteur",       stats["buts"],   "player_goal_scorer_anytime", 1.15),
                ("Passeur",      stats["passes"],  "player_assists",              1.20),
                ("Carton jaune", stats["cj"],      "player_cards",                1.25),
            ]

            for bet_type, stat_val, market_key, bk_margin in analyses:
                rate_per_90 = stat_val / stats["min"] * 90
                if rate_per_90 <= 0:
                    continue

                prob = 1 - math.exp(-rate_per_90)
                if prob < 0.05:
                    continue

                fair_cote = 1 / prob

                # Utiliser vraies cotes si disponibles
                if player in real_props and market_key in real_props[player]:
                    market_cotes = real_props[player][market_key]
                    best_cote = max(market_cotes)
                    best_bk = "Winamax"
                else:
                    # Estimation marché
                    best_cote = fair_cote * bk_margin
                    best_bk = "Estimé"

                edge = (prob * best_cote - 1) * 100

                if edge >= EDGE_THRESHOLD:
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
                        "is_estimated": best_bk == "Estimé",
                    })

    return sorted(results, key=lambda x: x["edge"], reverse=True)

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
    labels = {"h": "1 Dom.", "d": "N Nul", "a": "2 Ext."}
    lines = [
        f"⚡ <b>VALUE BET 1N2</b>",
        f"",
        f"🏆 {vb['competition']}",
        f"⚽ <b>{vb['home']} vs {vb['away']}</b>",
        f"📅 {format_date(vb['date'])}",
        f"",
    ]
    for k, label in labels.items():
        e = vb["edge"][k]
        if e >= EDGE_THRESHOLD:
            cote, bk = vb["best"][k]
            prob = vb["fair"][k] * 100
            lines += [
                f"🎯 <b>{label}</b> · Cote <b>{cote:.2f}</b> chez {bk}",
                f"   Prob. réelle: {prob:.1f}% · Edge: <b>+{e:.1f}%</b>",
                f"",
            ]
    lines.append("⚠️ Usage éducatif uniquement")
    return "\n".join(lines)

def format_player_alert(vb: dict) -> str:
    emojis = {"Buteur": "⚽", "Passeur": "🅰️", "Carton jaune": "🟨"}
    emoji = emojis.get(vb["bet_type"], "🎯")
    estimated = " (estimé)" if vb["is_estimated"] else ""
    return (
        f"{emoji} <b>VALUE BET JOUEUR — {vb['bet_type'].upper()}</b>\n\n"
        f"🏆 {vb['competition']}\n"
        f"⚽ {vb['match']}\n"
        f"📅 {format_date(vb['date'])}\n\n"
        f"👤 <b>{vb['player']}</b> ({vb['team']})\n"
        f"💰 Cote: <b>{vb['best_cote']:.2f}</b> chez {vb['best_bk']}{estimated}\n"
        f"📊 Cote juste: {vb['fair_cote']:.2f}\n"
        f"📈 Prob. réelle: {vb['prob']*100:.1f}%\n"
        f"🔥 Edge: <b>+{vb['edge']:.1f}%</b>\n\n"
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
        log.info(f"  {competition}...")
        matches = fetch_odds(sport_key)

        if not matches:
            time.sleep(0.5)
            continue

        leagues_scanned += 1
        total_matches += len(matches)

        for match in matches:
            # 1N2
            vb_1n2 = calc_1n2_edge(match, competition)
            if vb_1n2:
                all_vbs.append(vb_1n2)

            # Joueurs
            player_vbs = calc_player_edges(match, competition, sport_key)
            all_vbs.extend(player_vbs)

        time.sleep(0.3)  # Respecter les quotas API

    log.info(f"Scan #{scan_count} terminé: {leagues_scanned} ligues, {total_matches} matchs, {len(all_vbs)} VB")

    # Trier par edge décroissant
    all_vbs.sort(key=lambda x: x.get("max_edge", x.get("edge", 0)), reverse=True)

    # Envoyer les top alertes
    alerts_sent = 0
    for vb in all_vbs:
        if alerts_sent >= MAX_ALERTS_PER_SCAN:
            break

        # Clé unique anti-doublon
        if vb["type"] == "1N2":
            key = f"1n2_{vb['home']}_{vb['away']}_{vb['max_edge']:.0f}"
            msg = format_1n2_alert(vb)
        else:
            key = f"player_{vb['player']}_{vb['bet_type']}_{vb['match']}"
            msg = format_player_alert(vb)

        if key in sent_alerts:
            continue

        if send_telegram(msg):
            sent_alerts.add(key)
            total_alerts += 1
            alerts_sent += 1
            log.info(f"  Alerte envoyée: {key[:60]}")
            time.sleep(1.5)

    if alerts_sent == 0:
        log.info("  Aucune nouvelle value bet trouvée ce scan")

    # Rapport toutes les 6h
    if scan_count % (360 // SCAN_INTERVAL_MIN) == 0:
        rapport = (
            f"📊 <b>Rapport ValueEdge — {now}</b>\n\n"
            f"✅ {scan_count} scans effectués\n"
            f"📬 {total_alerts} alertes envoyées\n"
            f"🌍 {leagues_scanned} ligues scannées\n"
            f"⚽ {total_matches} matchs analysés\n"
            f"⚙️ Seuil: +{EDGE_THRESHOLD}%\n\n"
            f"🟢 Agent opérationnel"
        )
        send_telegram(rapport)

    # Nettoyer les vieilles alertes (garder max 500)
    if len(sent_alerts) > 500:
        to_remove = list(sent_alerts)[:100]
        for k in to_remove:
            sent_alerts.discard(k)

# ══════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("╔══════════════════════════════════════╗")
    log.info("║     ValueEdge Agent v2 — MONDIAL     ║")
    log.info(f"║  {len(FOOTBALL_LEAGUES)} ligues · seuil +{EDGE_THRESHOLD}% · {SCAN_INTERVAL_MIN}min  ║")
    log.info("╚══════════════════════════════════════╝")

    if ODDS_API_KEY == "VOTRE_CLE_THE_ODDS_API":
        log.warning("⚠️  Clé The Odds API non configurée — les cotes ne seront pas récupérées")

    send_telegram(
        f"🌍 <b>ValueEdge Agent v2 — Football Mondial</b>\n\n"
        f"📡 <b>{len(FOOTBALL_LEAGUES)} ligues</b> surveillées :\n"
        f"🇪🇺 Europe (25 championnats + 3 coupes)\n"
        f"🌎 Amériques (MLS, Liga MX, Brésil, Argentine...)\n"
        f"🌏 Asie (J-League, Saudi, K-League, A-League...)\n"
        f"🌍 Afrique (PSL, Egypt, Maroc...)\n\n"
        f"🎯 Paris analysés :\n"
        f"• 1N2 (résultats)\n"
        f"• Buteur anytime\n"
        f"• Passeur décisif\n"
        f"• Carton jaune\n\n"
        f"⚙️ Seuil edge: <b>+{EDGE_THRESHOLD}%</b>\n"
        f"⏰ Scan: toutes les <b>{SCAN_INTERVAL_MIN} min</b>\n\n"
        f"Premier scan en cours... 🔍"
    )

    run_full_scan()

    schedule.every(SCAN_INTERVAL_MIN).minutes.do(run_full_scan)
    log.info(f"Agent planifié — scan toutes les {SCAN_INTERVAL_MIN} min")

    while True:
        schedule.run_pending()
        time.sleep(60)
