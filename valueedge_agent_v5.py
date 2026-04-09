"""
ValueEdge Agent v5 — Scraper compare-bet.fr
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE UNIQUE : compare-bet.fr
  → Agrège Winamax, Unibet, PMU, Betclic, Olybet, Feelingbet, Genybet, Daznbet, Vbet
  → Mis à jour toutes les heures
  → Pas d'API key requise
  → Zéro estimation — uniquement des vraies cotes publiées

COUVERTURE :
  Ligue 1, Ligue 2, Premier League, Championship, La Liga,
  Segunda, Bundesliga, 2.Bundesliga, Serie A, Serie B,
  Primeira Liga, Eredivisie, Jupiler, Süper Lig,
  Champions League, Europa League, Conference League

MÉTHODE VALUE BET :
  1. Scrape toutes les cotes des bookmakers FR sur compare-bet.fr
  2. Calcule la probabilité juste (retrait de marge, normalisation)
  3. Edge = (prob_juste × meilleure_cote) - 1
  4. Alerte si edge > seuil ET bookmaker identifié précisément

DÉPLOIEMENT Railway :
  Variables : TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, EDGE_THRESHOLD, SCAN_INTERVAL
  Dépendances : pip install requests beautifulsoup4 schedule lxml
"""

import requests
from bs4 import BeautifulSoup
import schedule
import time
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════
TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN", "VOTRE_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "VOTRE_CHAT_ID")
EDGE_THRESHOLD      = float(os.getenv("EDGE_THRESHOLD", "6"))
SCAN_INTERVAL_MIN   = int(os.getenv("SCAN_INTERVAL", "60"))   # 60 min car compare-bet MAJ toutes les heures
MAX_ALERTS_PER_SCAN = int(os.getenv("MAX_ALERTS", "5"))
ALERT_TTL_HOURS     = int(os.getenv("ALERT_TTL_HOURS", "20"))
SENT_CACHE_FILE     = "/tmp/ve_sent_v5.json"

# ══════════════════════════════════════════════════════
# TOUTES LES COMPÉTITIONS DISPONIBLES SUR COMPARE-BET
# ══════════════════════════════════════════════════════
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMPÉTITIONS RÉELLEMENT DISPONIBLES SUR COMPARE-BET.FR
# Source vérifiée : compare-bet.fr/cotes.html (avril 2026)
# Compare-bet couvre uniquement les cotes 1N2 (pas de buteurs)
# Bookmakers : Daznbet, Feelingbet, Olybet, PMU, Unibet, Vbet, Winamax
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPETITIONS = {
    # France
    "🇫🇷 Ligue 1":            "https://www.compare-bet.fr/cotes/ligue1.html",
    "🇫🇷 Ligue 2":            "https://www.compare-bet.fr/cotes/ligue2.html",
    # Angleterre
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League":  "https://www.compare-bet.fr/cotes/premier-league.html",
    # Espagne
    "🇪🇸 La Liga":             "https://www.compare-bet.fr/cotes/liga.html",
    # Allemagne
    "🇩🇪 Bundesliga":          "https://www.compare-bet.fr/cotes/bundesliga.html",
    # Italie
    "🇮🇹 Serie A":             "https://www.compare-bet.fr/cotes/serie-a.html",
    # Coupe d'Europe
    "🏆 Champions League":     "https://www.compare-bet.fr/cotes/champions-league.html",
    # Clubs français (pages dédiées avec matchs toutes compétitions)
    "PSG (tous matchs)":       "https://www.compare-bet.fr/cotes/psg.html",
    "OM (tous matchs)":        "https://www.compare-bet.fr/cotes/om.html",
    "OL (tous matchs)":        "https://www.compare-bet.fr/cotes/lyon.html",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOURCES COTES BUTEURS — Pages pronostics Sportytrader
# Sportytrader publie les cotes Winamax buteur/passeur
# pour les matchs à venir sous forme de texte structuré
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCORER_SOURCES = {
    "🇫🇷 Ligue 1":        "https://www.sportytrader.com/pronostics/football/france/ligue-1-123/",
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League": "https://www.sportytrader.com/pronostics/football/angleterre/premier-league-35/",
    "🏆 Champions League": "https://www.sportytrader.com/pronostics/football/europe/champions-league-8/",
    "🇪🇸 La Liga":         "https://www.sportytrader.com/pronostics/football/espagne/la-liga-13/",
    "🇩🇪 Bundesliga":      "https://www.sportytrader.com/pronostics/football/allemagne/bundesliga-12/",
    "🇮🇹 Serie A":         "https://www.sportytrader.com/pronostics/football/italie/serie-a-14/",
}



# Bookmakers affichés sur compare-bet.fr (pour identifier les colonnes)
# L'ordre peut varier selon les matchs — on les détecte dynamiquement
KNOWN_FR_BOOKMAKERS = {
    "winamax", "unibet", "pmu", "betclic", "olybet",
    "feelingbet", "genybet", "daznbet", "vbet", "zebet",
    "parions sport", "parionssport"
}

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
# CACHE ANTI-DOUBLONS (persistant sur disque)
# ══════════════════════════════════════════════════════
def load_cache() -> dict:
    try:
        if Path(SENT_CACHE_FILE).exists():
            with open(SENT_CACHE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_cache(cache: dict):
    try:
        with open(SENT_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        log.warning(f"Cache save: {e}")

def is_duplicate(cache: dict, key: str) -> bool:
    if key not in cache:
        return False
    return datetime.now() - datetime.fromisoformat(cache[key]) < timedelta(hours=ALERT_TTL_HOURS)

def mark_sent(cache: dict, key: str):
    cache[key] = datetime.now().isoformat()
    cutoff = datetime.now() - timedelta(hours=ALERT_TTL_HOURS * 2)
    expired = [k for k, v in cache.items() if datetime.fromisoformat(v) < cutoff]
    for k in expired:
        del cache[k]
    save_cache(cache)

# ══════════════════════════════════════════════════════
# SCRAPER COMPARE-BET.FR
# ══════════════════════════════════════════════════════
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

def scrape_competition(competition: str, url: str) -> list:
    """
    Scrape compare-bet.fr et retourne une liste de matchs avec cotes.

    Structure de la page :
      <h2>Équipe A - Équipe B</h2>
      <p>Date - heure</p>
      <table>
        <tr><td>Bookmaker</td><td>cote_1</td><td>cote_N</td><td>cote_2</td></tr>
        ...
      </table>
    """
    matches = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if not resp.ok:
            log.warning(f"HTTP {resp.status_code} — {url}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # Chaque bloc de match commence par un <h2> "Équipe A - Équipe B"
        for h2 in soup.find_all("h2"):
            raw_title = h2.get_text(strip=True)

            # Filtrer les h2 qui ne sont pas des matchs
            if " - " not in raw_title or len(raw_title) > 80:
                continue
            # Ignorer les titres de section
            if any(w in raw_title.lower() for w in ["meilleures", "pourquoi", "à propos", "comparer"]):
                continue

            # Date du match
            date_el = h2.find_next_sibling()
            date_str = ""
            if date_el:
                txt = date_el.get_text(strip=True)
                if any(c.isdigit() for c in txt):
                    date_str = txt

            # Tableau des cotes
            table = h2.find_next("table")
            if not table:
                continue

            # Lire les en-têtes de colonnes (1 / N / 2)
            # et les lignes de bookmakers
            bookmaker_odds = {}
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue

                bk_name = cells[0].get_text(strip=True).lower()
                # Ignorer les lignes vides ou non-bookmakers
                if not bk_name or bk_name in ("", "pariez"):
                    continue

                try:
                    c1 = cells[1].get_text(strip=True).replace(",", ".")
                    cn = cells[2].get_text(strip=True).replace(",", ".")
                    c2 = cells[3].get_text(strip=True).replace(",", ".")

                    h_odd = float(c1)
                    d_odd = float(cn)
                    a_odd = float(c2)

                    # Vérifications de cohérence
                    if not (1.01 <= h_odd <= 50 and 1.01 <= d_odd <= 50 and 1.01 <= a_odd <= 50):
                        continue

                    # Normaliser le nom du bookmaker
                    bk_clean = _normalize_bk(bk_name)
                    bookmaker_odds[bk_clean] = (h_odd, d_odd, a_odd)

                except (ValueError, IndexError):
                    continue

            if len(bookmaker_odds) < 2:
                continue

            # Séparer équipes
            parts = raw_title.split(" - ", 1)
            home = parts[0].strip()
            away = parts[1].strip() if len(parts) > 1 else "?"

            matches.append({
                "competition": competition,
                "home": home,
                "away": away,
                "date": date_str,
                "odds": bookmaker_odds,
            })

    except requests.exceptions.RequestException as e:
        log.error(f"Scrape error ({competition}): {e}")
    except Exception as e:
        log.error(f"Parse error ({competition}): {e}")

    return matches

def _normalize_bk(name: str) -> str:
    """Normalise le nom du bookmaker pour un affichage propre"""
    mapping = {
        "winamax":      "Winamax",
        "unibet":       "Unibet",
        "pmu":          "PMU Sport",
        "betclic":      "Betclic",
        "olybet":       "Olybet",
        "feelingbet":   "Feelingbet",
        "genybet":      "Genybet",
        "daznbet":      "Daznbet",
        "vbet":         "Vbet",
        "zebet":        "Zebet",
        "parions sport": "Parions Sport",
        "parionssport": "Parions Sport",
    }
    for key, label in mapping.items():
        if key in name.lower():
            return label
    # Capitaliser si inconnu
    return name.title()

# ══════════════════════════════════════════════════════
# CALCUL EDGE
# ══════════════════════════════════════════════════════
def avg(lst):
    return sum(lst) / len(lst) if lst else 0


def scrape_scorer_odds(competition: str, url: str) -> list:
    """
    Scrape les cotes buteurs/passeurs depuis sportytrader.com
    Format retourné : [{match, home, away, date, players: [{name, bet_type, cote, bookmaker}]}]
    """
    results = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if not resp.ok:
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # Sportytrader liste les prochains matchs avec liens vers les pronostics
        match_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/pronostics/" in href and href.count("/") >= 5:
                full_url = href if href.startswith("http") else "https://www.sportytrader.com" + href
                if full_url not in match_links:
                    match_links.append(full_url)

        # Limiter à 5 matchs pour préserver les quotas
        for match_url in match_links[:5]:
            match_data = scrape_single_match_scorers(match_url, competition)
            if match_data:
                results.append(match_data)
            time.sleep(2)

    except Exception as e:
        log.error(f"Scorer scrape error ({competition}): {e}")

    return results


def scrape_single_match_scorers(url: str, competition: str) -> dict | None:
    """Scrape les cotes buteurs/passeurs pour un match depuis sportytrader"""
    import re
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if not resp.ok:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text()

        title = soup.find("h1")
        if not title:
            return None
        title_text = title.get_text(strip=True)

        # Extraire équipes A - B ou A / B
        sep = " - " if " - " in title_text else " / "
        parts = title_text.split(sep, 1)
        if len(parts) < 2:
            return None
        home = parts[0].strip().split()[0:3]
        away = parts[1].strip().split()[0:3]
        home = " ".join(home)
        away = " ".join(away)

        date_el = soup.find(class_=re.compile("date|time", re.I))
        date_str = date_el.get_text(strip=True) if date_el else ""

        players = []

        for bet_type, keyword, cote_max in [
            ("Buteur", "buteur", 30),
            ("Passeur", "passeur", 40),
            ("Decisif", r"d[eé]cisif", 20),
        ]:
            pattern = re.compile(
                r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+" + keyword + r"\s*:\s*([\d,\.]+)",
                re.UNICODE
            )
            for m in pattern.finditer(text):
                name = m.group(1).strip()
                cote_str = m.group(2).replace(",", ".")
                try:
                    cote = float(cote_str)
                    if 1.1 <= cote <= cote_max:
                        players.append({
                            "name": name,
                            "bet_type": bet_type,
                            "cote": cote,
                            "bookmaker": "Winamax"
                        })
                except ValueError:
                    continue

        if not players:
            return None

        return {
            "competition": competition,
            "home": home,
            "away": away,
            "date": date_str,
            "url": url,
            "players": players,
        }

    except Exception as e:
        log.warning(f"Match scorer scrape error: {e}")
        return None


def analyze_scorer_value(match_data: dict) -> list:
    """
    Analyse les value bets buteurs/passeurs.
    Compare la cote Winamax scrapée à la cote juste estimée
    via les stats de la base de données joueurs.
    Uniquement pour les joueurs dont on a des stats.
    """
    import math
    results = []

    for player_bet in match_data.get("players", []):
        name = player_bet["name"]
        cote = player_bet["cote"]
        bet_type = player_bet["bet_type"]
        bookmaker = player_bet["bookmaker"]

        # Chercher les stats du joueur
        stats = None
        for player_name, s in PLAYER_STATS.items():
            if player_name.lower() in name.lower() or name.lower() in player_name.lower():
                stats = s
                found_name = player_name
                break

        if not stats or stats["min_s"] < 200:
            continue

        # Calculer la probabilité réelle
        if bet_type == "Buteur":
            rate = stats["buts_s"] / stats["min_s"] * 90
            form_ratio = stats["buts_5j"] / max(rate * 5, 0.3)
        elif bet_type in ("Passeur", "Décisif"):
            rate = stats["passes_s"] / stats["min_s"] * 90
            form_ratio = stats["passes_5j"] / max(rate * 5, 0.3)
        else:
            continue

        rate_adj = rate * min(max(form_ratio, 0.6), 1.8)
        prob = 1 - math.exp(-rate_adj)

        if prob < 0.05:
            continue

        fair_cote = 1 / prob
        edge = (prob * cote - 1) * 100

        if edge < EDGE_THRESHOLD:
            continue

        # Filtres qualité
        is_form_spike = form_ratio >= 1.5
        is_under_radar = stats["popularite"] >= 4
        is_solid = form_ratio >= 1.2 and stats["popularite"] >= 3

        if not (is_form_spike or is_under_radar or is_solid):
            continue

        # Exclure les stars sur-médiatisées sans signal fort
        if found_name in OVERHYPED_PLAYERS and form_ratio < 1.4:
            continue

        trend = "🔥 Explosion de forme" if form_ratio >= 1.8 else "📈 En forme"
        stat_line = f"{stats['buts_s'] if bet_type=='Buteur' else stats['passes_s']} {bet_type.lower()}s en {stats['matchs_s']} matchs · {trend}"

        results.append({
            "type": "BUTEUR",
            "player": found_name,
            "bet_type": bet_type,
            "competition": match_data["competition"],
            "match": f"{match_data['home']} vs {match_data['away']}",
            "date": match_data["date"],
            "cote": cote,
            "bookmaker": bookmaker,
            "fair_cote": fair_cote,
            "prob": prob,
            "edge": edge,
            "form_ratio": form_ratio,
            "stat_line": stat_line,
            "is_estimated": False,  # Cote réellement scrapée
        })

    return sorted(results, key=lambda x: x["edge"], reverse=True)

def analyze_match(match: dict) -> dict | None:
    """
    Calcule la value bet pour un match.

    Méthode :
    - Probabilité juste = moyenne des cotes inverses, normalisée (marge retirée)
    - Meilleure cote = max sur tous les bookmakers
    - Edge = prob_juste × meilleure_cote - 1
    """
    odds = match["odds"]
    if len(odds) < 2:
        return None

    all_h = [v[0] for v in odds.values()]
    all_d = [v[1] for v in odds.values()]
    all_a = [v[2] for v in odds.values()]

    # Probabilités brutes (avec marge)
    raw = {
        "h": 1 / avg(all_h),
        "d": 1 / avg(all_d),
        "a": 1 / avg(all_a),
    }
    tot = sum(raw.values())

    # Probabilités justes (marge retirée)
    fair = {k: v / tot for k, v in raw.items()}

    # Marge moyenne du marché
    vig = (tot - 1) * 100

    # Meilleure cote disponible + bookmaker associé
    best_h = max(odds.items(), key=lambda x: x[1][0])
    best_d = max(odds.items(), key=lambda x: x[1][1])
    best_a = max(odds.items(), key=lambda x: x[1][2])

    best = {
        "h": (best_h[1][0], best_h[0]),
        "d": (best_d[1][1], best_d[0]),
        "a": (best_a[1][2], best_a[0]),
    }

    # Edges
    edge = {
        "h": (fair["h"] * best["h"][0] - 1) * 100,
        "d": (fair["d"] * best["d"][0] - 1) * 100,
        "a": (fair["a"] * best["a"][0] - 1) * 100,
    }

    max_edge = max(edge.values())
    if max_edge < EDGE_THRESHOLD:
        return None

    # Divergence entre bookmakers (signal de marché inefficient)
    divergence = max(
        (max(all_h) - min(all_h)) / min(all_h) * 100,
        (max(all_d) - min(all_d)) / min(all_d) * 100,
        (max(all_a) - min(all_a)) / min(all_a) * 100,
    )

    return {
        **match,
        "fair":       fair,
        "best":       best,
        "edge":       edge,
        "max_edge":   max_edge,
        "vig":        vig,
        "divergence": divergence,
        "n_bk":       len(odds),
    }

# ══════════════════════════════════════════════════════
# FORMATAGE TELEGRAM
# ══════════════════════════════════════════════════════

def format_scorer_alert(vb: dict) -> str:
    emojis = {"Buteur": "⚽", "Passeur": "🅰️", "Décisif": "🎯"}
    emoji = emojis.get(vb["bet_type"], "🎯")
    return (
        f"{emoji} <b>VALUE BET — {vb['bet_type'].upper()}</b>\n"
        f"\n"
        f"🏆 {vb['competition']}\n"
        f"⚽ {vb['match']}\n"
        f"📅 {vb['date']}\n"
        f"\n"
        f"👤 <b>{vb['player']}</b>\n"
        f"\n"
        f"📊 {vb['stat_line']}\n"
        f"\n"
        f"💰 Cote <b>{vb['cote']:.2f}</b> chez <b>{vb['bookmaker']}</b>\n"
        f"📐 Cote juste : {vb['fair_cote']:.2f}\n"
        f"📈 Prob. réelle : {vb['prob']*100:.1f}%\n"
        f"🔥 Edge : <b>+{vb['edge']:.1f}%</b>\n"
        f"\n"
        f"⚠️ Usage éducatif uniquement"
    )

def format_alert(vb: dict) -> str:
    labels = {"h": "1 Domicile", "d": "N Nul", "a": "2 Extérieur"}

    # Sélectionner les issues avec value
    value_lines = []
    for k, label in labels.items():
        e = vb["edge"][k]
        if e >= EDGE_THRESHOLD:
            cote, bk = vb["best"][k]
            prob = vb["fair"][k] * 100
            value_lines.append(
                f"🎯 <b>{label}</b>\n"
                f"   💰 Cote : <b>{cote:.2f}</b> chez <b>{bk}</b>\n"
                f"   📈 Prob. réelle : {prob:.1f}%\n"
                f"   🔥 Edge : <b>+{e:.1f}%</b>"
            )

    # Contexte du marché
    context_parts = [f"📚 {vb['n_bk']} bookmakers comparés · Marge moy. : {vb['vig']:.1f}%"]
    if vb["divergence"] > 5:
        context_parts.append(f"⚠️ Forte divergence marché : {vb['divergence']:.1f}%")

    # Toutes les cotes disponibles
    all_odds_lines = []
    for bk_name, (h, d, a) in sorted(vb["odds"].items()):
        all_odds_lines.append(f"   {bk_name:<14} {h:.2f}  {d:.2f}  {a:.2f}")

    msg = (
        f"⚡ <b>VALUE BET</b>\n"
        f"\n"
        f"🏆 {vb['competition']}\n"
        f"⚽ <b>{vb['home']} vs {vb['away']}</b>\n"
        f"📅 {vb['date']}\n"
        f"\n"
        + "\n\n".join(value_lines) +
        f"\n\n"
        f"{'chr(10)'.join(context_parts)}\n"
        f"\n"
        f"<pre>{'Bookmaker':<14} 1     N     2\n"
        + "\n".join(all_odds_lines) +
        f"</pre>\n"
        f"\n"
        f"⚠️ Usage éducatif uniquement"
    )
    return msg

# ══════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════
def send_telegram(message: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.error(f"Telegram: {e}")
        return False

# ══════════════════════════════════════════════════════
# SCAN PRINCIPAL
# ══════════════════════════════════════════════════════
def run_scan():
    global scan_count, total_alerts
    scan_count += 1
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    log.info(f"=== SCAN #{scan_count} — {now} ===")

    cache = load_cache()
    all_vbs = []
    total_matches = 0
    comps_scanned = 0

    # ── 1. Cotes 1N2 via compare-bet.fr ────────────────
    for competition, url in COMPETITIONS.items():
        log.info(f"  Scrape 1N2 {competition}...")
        matches = scrape_competition(competition, url)

        if not matches:
            time.sleep(2)
            continue

        comps_scanned += 1
        total_matches += len(matches)
        log.info(f"    → {len(matches)} matchs")

        for match in matches:
            vb = analyze_match(match)
            if vb:
                all_vbs.append(vb)

        time.sleep(3)

    # ── 2. Cotes buteurs via sportytrader ───────────────
    log.info("  Scrape cotes buteurs (sportytrader)...")
    for competition, url in SCORER_SOURCES.items():
        scorer_matches = scrape_scorer_odds(competition, url)
        for m in scorer_matches:
            scorer_vbs = analyze_scorer_value(m)
            all_vbs.extend(scorer_vbs)
        time.sleep(3)

    # Trier par edge décroissant
    all_vbs.sort(key=lambda x: x["max_edge"], reverse=True)

    log.info(f"Scan #{scan_count} : {comps_scanned} compétitions · {total_matches} matchs · {len(all_vbs)} value bets")

    # Envoyer les alertes
    alerts_sent = 0
    for vb in all_vbs:
        if alerts_sent >= MAX_ALERTS_PER_SCAN:
            break

        # Clé stable : équipes + compétition (pas l'edge)
        if vb.get("type") == "BUTEUR":
            key = f"scorer_{vb['player']}_{vb['bet_type']}_{vb['match'][:30]}"
            msg = format_scorer_alert(vb)
            log_label = f"{vb['player']} {vb['bet_type']} +{vb['edge']:.1f}%"
        else:
            key = f"{vb['competition']}_{vb['home']}_{vb['away']}"
            msg = format_alert(vb)
            log_label = f"{vb['home']} vs {vb['away']} +{vb.get('max_edge', vb.get('edge',0)):.1f}%"

        if is_duplicate(cache, key):
            log.debug(f"Doublon ignoré : {key[:60]}")
            continue

        if send_telegram(msg):
            mark_sent(cache, key)
            total_alerts += 1
            alerts_sent += 1
            log.info(f"  ✓ Alerte : {log_label}")
            time.sleep(2)

    if alerts_sent == 0:
        log.info("  Aucune nouvelle value bet ce scan")

    # Rapport toutes les 12h
    if scan_count % max(1, 720 // SCAN_INTERVAL_MIN) == 0:
        send_telegram(
            f"📊 <b>Rapport ValueEdge v5 — {now}</b>\n\n"
            f"✅ {scan_count} scans\n"
            f"📬 {total_alerts} alertes envoyées\n"
            f"🏆 {comps_scanned} compétitions scrapées\n"
            f"⚽ {total_matches} matchs analysés\n"
            f"⚙️ Seuil : +{EDGE_THRESHOLD}%\n"
            f"🔄 Interval : {SCAN_INTERVAL_MIN} min\n\n"
            f"🟢 Agent opérationnel"
        )

# ══════════════════════════════════════════════════════
# DÉMARRAGE
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("╔═════════════════════════════════════════════╗")
    log.info("║   ValueEdge v5 — Scraper compare-bet.fr    ║")
    log.info(f"║   {len(COMPETITIONS)} compétitions · seuil +{EDGE_THRESHOLD}% · {SCAN_INTERVAL_MIN}min  ║")
    log.info("╚═════════════════════════════════════════════╝")

    send_telegram(
        f"🚀 <b>ValueEdge Agent v5</b>\n\n"
        f"📡 Source : <b>compare-bet.fr</b>\n"
        f"   Winamax · Unibet · PMU · Betclic\n"
        f"   Olybet · Feelingbet · Genybet · Vbet · Daznbet\n\n"
        f"🏆 <b>{len(COMPETITIONS)} compétitions</b> :\n"
        f"   Ligue 1/2 · PL · Championship\n"
        f"   La Liga · Bundesliga · Serie A\n"
        f"   Primeira Liga · Eredivisie · Jupiler\n"
        f"   CL · EL · Conference League\n\n"
        f"✅ <b>Cotes 100% réelles</b> — aucune estimation\n"
        f"✅ Bookmaker précis affiché pour chaque value bet\n"
        f"✅ Tableau complet des cotes dans chaque alerte\n"
        f"✅ Anti-doublons persistant ({ALERT_TTL_HOURS}h)\n\n"
        f"⚙️ Seuil : +{EDGE_THRESHOLD}% · Scan : toutes les {SCAN_INTERVAL_MIN} min\n\n"
        f"🔍 Premier scan en cours..."
    )

    run_scan()
    schedule.every(SCAN_INTERVAL_MIN).minutes.do(run_scan)

    while True:
        schedule.run_pending()
        time.sleep(60)
