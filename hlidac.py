import os
import json
import smtplib
import requests
import xml.etree.ElementTree as ET
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ============================================================
# KONFIGURACE
# ============================================================
EMAIL_ADRESA = os.environ.get("EMAIL_ADRESA", "tvuj@gmail.com")
EMAIL_HESLO  = os.environ.get("EMAIL_HESLO", "")
SOUBOR_VIDENYCH = "videne_inzeraty.json"
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

def nacti_videne():
    if os.path.exists(SOUBOR_VIDENYCH):
        with open(SOUBOR_VIDENYCH, "r") as f:
            return set(json.load(f))
    return set()

def uloz_videne(videne):
    with open(SOUBOR_VIDENYCH, "w") as f:
        json.dump(list(videne), f)

# ------------------------------------------------------------
# SREALITY.CZ – RSS feed (spolehlivější než JSON API)
# category_main_cb: 2=Domy, 3=Pozemky
# category_type_cb: 1=Prodej
# ------------------------------------------------------------
def hledej_sreality():
    nalezeno = []
    feeds = [
        {
            "url": (
                "https://www.sreality.cz/api/cs/v2/estates/rss"
                "?category_main_cb=3"        # Pozemky
                "&category_type_cb=1"         # Prodej
                "&locality_district_id=5103"  # okres Benešov
                "&locality_radius=10"
                "&price_min=1000000"
                "&price_max=5800000"
            ),
            "label": "Pozemek"
        },
        {
            "url": (
                "https://www.sreality.cz/api/cs/v2/estates/rss"
                "?category_main_cb=2"        # Domy
                "&category_type_cb=1"         # Prodej
                "&locality_district_id=5103"  # okres Benešov
                "&locality_radius=10"
                "&price_min=1000000"
                "&price_max=5800000"
            ),
            "label": "Dům"
        },
    ]
    for feed in feeds:
        try:
            r = requests.get(feed["url"], headers=HEADERS, timeout=15)
            print(f"[Sreality {feed['label']}] HTTP {r.status_code}")
            root = ET.fromstring(r.content)
            items = root.findall(".//item")
            print(f"[Sreality {feed['label']}] Nalezeno položek: {len(items)}")
            for item in items:
                link = item.findtext("link", "").strip()
                title = item.findtext("title", "Bez názvu").strip()
                guid = item.findtext("guid", link).strip()
                eid = guid.split("/")[-1] if guid else link

                # Cena z description
                desc = item.findtext("description", "")
                cena_str = ""
                if "Kč" in desc:
                    import re
                    match = re.search(r"([\d\s]+)\s*Kč", desc)
                    if match:
                        cena_str = match.group(0).strip()

                nalezeno.append({
                    "id": f"sreality_{eid}",
                    "zdroj": "Sreality.cz",
                    "typ": feed["label"],
                    "nazev": title,
                    "cena_str": cena_str,
                    "lokalita": "Benešov a okolí",
                    "link": link,
                })
        except Exception as ex:
            print(f"[Sreality {feed['label']}] Chyba: {ex}")
    return nalezeno

# ------------------------------------------------------------
# BEZREALITKY.CZ – GraphQL API
# ------------------------------------------------------------
def hledej_bezrealitky():
    nalezeno = []
    typy = [
        {"estateType": "LAND",  "label": "Pozemek"},
        {"estateType": "HOUSE", "label": "Dům"},
    ]
    for typ in typy:
        try:
            url = "https://www.bezrealitky.cz/graphql/"
            query = """
            query SearchEstates($offerType: OfferType, $estateType: [EstateType], $priceFrom: Int, $priceTo: Int, $regionOsmIds: [String]) {
              estateList(
                offerType: $offerType
                estateType: $estateType
                priceFrom: $priceFrom
                priceTo: $priceTo
                regionOsmIds: $regionOsmIds
                limit: 30
              ) {
                list {
                  id
                  uri
                  price
                  address
                }
              }
            }
            """
            variables = {
                "offerType": "PRODEJ",
                "estateType": [typ["estateType"]],
                "priceFrom": 1000000,
                "priceTo": 5800000,
                "regionOsmIds": ["R435637"]  # Benešov okres
            }
            r = requests.post(
                url,
                json={"query": query, "variables": variables},
                headers={**HEADERS, "Content-Type": "application/json"},
                timeout=15
            )
            print(f"[Bezrealitky {typ['label']}] HTTP {r.status_code}")
            data = r.json()
            items = data.get("data", {}).get("estateList", {}).get("list", [])
            print(f"[Bezrealitky {typ['label']}] Nalezeno: {len(items)}")
            for item in items:
                eid = str(item.get("id", ""))
                cena = item.get("price", 0)
                adresa = item.get("address", "")
                uri = item.get("uri", "")
                link = f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{uri}" if uri else f"https://www.bezrealitky.cz"
                nalezeno.append({
                    "id": f"bezrealitky_{eid}",
                    "zdroj": "Bezrealitky.cz",
                    "typ": typ["label"],
                    "nazev": f"{typ['label']} – {adresa}",
                    "cena_str": f"{cena:,} Kč".replace(",", " ") if cena else "",
                    "lokalita": adresa,
                    "link": link,
                })
        except Exception as ex:
            print(f"[Bezrealitky {typ['label']}] Chyba: {ex}")
    return nalezeno

# ------------------------------------------------------------
# REALITY.CZ – RSS feed
# ------------------------------------------------------------
def hledej_reality_cz():
    nalezeno = []
    feeds = [
        {
            "url": (
                "https://www.reality.cz/rss/"
                "?s%5Bobject%5D%5B%5D=4"          # pozemky
                "&s%5Btype%5D=1"                   # prodej
                "&s%5Blocality_district%5D=Bene%C5%A1ov"
                "&s%5Bprice_from%5D=1000000"
                "&s%5Bprice_to%5D=5800000"
            ),
            "label": "Pozemek"
        },
        {
            "url": (
                "https://www.reality.cz/rss/"
                "?s%5Bobject%5D%5B%5D=2"          # domy
                "&s%5Btype%5D=1"                   # prodej
                "&s%5Blocality_district%5D=Bene%C5%A1ov"
                "&s%5Bprice_from%5D=1000000"
                "&s%5Bprice_to%5D=5800000"
            ),
            "label": "Dům"
        },
    ]
    for feed in feeds:
        try:
            r = requests.get(feed["url"], headers=HEADERS, timeout=15)
            print(f"[Reality.cz {feed['label']}] HTTP {r.status_code}")
            root = ET.fromstring(r.content)
            items = root.findall(".//item")
            print(f"[Reality.cz {feed['label']}] Nalezeno: {len(items)}")
            for item in items:
                link = item.findtext("link", "").strip()
                title = item.findtext("title", "Bez názvu").strip()
                guid = item.findtext("guid", link).strip()
                eid = guid.split("/")[-1] if guid else link
                nalezeno.append({
                    "id": f"reality_{eid}",
                    "zdroj": "Reality.cz",
                    "typ": feed["label"],
                    "nazev": title,
                    "cena_str": "",
                    "lokalita": "Benešov a okolí",
                    "link": link,
                })
        except Exception as ex:
            print(f"[Reality.cz {feed['label']}] Chyba: {ex}")
    return nalezeno

# ------------------------------------------------------------
# EMAIL
# ------------------------------------------------------------
def posli_email(nove_inzeraty):
    if not nove_inzeraty:
        return

    radky = []
    for inz in nove_inzeraty:
        radky.append(
            f"<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #eee'>{inz['zdroj']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee'>{inz['typ']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee'>{inz['nazev']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee'>{inz.get('cena_str','')}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee'>"
            f"<a href='{inz['link']}' style='color:#0066cc'>Zobrazit →</a></td>"
            f"</tr>"
        )

    html = f"""
    <html><body style='font-family:Arial,sans-serif;max-width:900px'>
    <h2 style='color:#333'>🏡 Nové nemovitosti – Benešov a okolí</h2>
    <p>Nalezeno <b>{len(nove_inzeraty)}</b> nových inzerátů odpovídajících tvým kritériím:</p>
    <table style='border-collapse:collapse;font-size:14px;width:100%'>
      <thead>
        <tr style='background:#f5f5f5;text-align:left'>
          <th style='padding:8px'>Zdroj</th>
          <th style='padding:8px'>Typ</th>
          <th style='padding:8px'>Název</th>
          <th style='padding:8px'>Cena</th>
          <th style='padding:8px'>Odkaz</th>
        </tr>
      </thead>
      <tbody>{''.join(radky)}</tbody>
    </table>
    <p style='color:#999;font-size:12px;margin-top:20px'>
      Automatický hlídač nemovitostí • {datetime.now().strftime('%d.%m.%Y %H:%M')}
    </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🏡 {len(nove_inzeraty)} nových nemovitostí – Benešov"
    msg["From"] = EMAIL_ADRESA
    msg["To"] = EMAIL_ADRESA
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADRESA, EMAIL_HESLO)
            smtp.sendmail(EMAIL_ADRESA, EMAIL_ADRESA, msg.as_string())
        print(f"✅ Email odeslán s {len(nove_inzeraty)} novými inzeráty.")
    except Exception as ex:
        print(f"❌ Chyba při odesílání emailu: {ex}")

# ------------------------------------------------------------
# HLAVNÍ PROGRAM
# ------------------------------------------------------------
def main():
    print(f"[{datetime.now().strftime('%d.%m.%Y %H:%M')}] Spouštím hlídač nemovitostí...")

    videne = nacti_videne()
    vsechny = []
    vsechny += hledej_sreality()
    vsechny += hledej_bezrealitky()
    vsechny += hledej_reality_cz()

    print(f"Celkem nalezeno inzerátů: {len(vsechny)}")

    nove = [i for i in vsechny if i["id"] not in videne]
    print(f"Nových inzerátů: {len(nove)}")

    if nove:
        posli_email(nove)
        for i in nove:
            videne.add(i["id"])
        uloz_videne(videne)
    else:
        print("Žádné nové inzeráty.")

if __name__ == "__main__":
    main()
