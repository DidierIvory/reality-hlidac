import os
import json
import smtplib
import requests
import re
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
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "cs-CZ,cs;q=0.9",
    "Referer": "https://www.sreality.cz/",
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
# SREALITY.CZ – JSON API
# category_main_cb: 2=Domy, 3=Pozemky
# category_type_cb: 1=Prodej
# locality_district_id: 5103=Benešov
# ------------------------------------------------------------
def hledej_sreality():
    nalezeno = []
    dotazy = [
        {"category_main_cb": 3, "label": "Pozemek"},
        {"category_main_cb": 2, "label": "Dům"},
    ]
    session = requests.Session()
    # Nejdřív načteme hlavní stránku aby jsme dostali cookies
    try:
        session.get("https://www.sreality.cz/", headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html",
        }, timeout=10)
    except:
        pass

    for dotaz in dotazy:
        url = (
            "https://www.sreality.cz/api/cs/v2/estates"
            f"?category_main_cb={dotaz['category_main_cb']}"
            "&category_type_cb=1"
            "&locality_district_id=5103"
            "&locality_radius=10"
            "&price_min=1000000"
            "&price_max=5800000"
            "&per_page=60"
            "&sort=0"
        )
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            print(f"[Sreality {dotaz['label']}] HTTP {r.status_code}, délka: {len(r.content)}")
            if r.status_code != 200:
                print(f"[Sreality {dotaz['label']}] Odpověď: {r.text[:200]}")
                continue
            data = r.json()
            estates = data.get("_embedded", {}).get("estates", [])
            print(f"[Sreality {dotaz['label']}] Nalezeno: {len(estates)}")
            for e in estates:
                eid = str(e.get("hash_id", ""))
                nazev = e.get("name", "Bez názvu")
                cena = e.get("price_czk", {})
                cena_val = cena.get("value_raw", 0) if isinstance(cena, dict) else 0
                lokalita = e.get("locality", "")
                link = f"https://www.sreality.cz/detail/prodej/{dotaz['label'].lower()}/{eid}"
                nalezeno.append({
                    "id": f"sreality_{eid}",
                    "zdroj": "Sreality.cz",
                    "typ": dotaz["label"],
                    "nazev": nazev,
                    "cena_str": f"{cena_val:,} Kč".replace(",", " ") if cena_val else "cena neuvedena",
                    "lokalita": lokalita,
                    "link": link,
                })
        except Exception as ex:
            print(f"[Sreality {dotaz['label']}] Chyba: {ex}")
    return nalezeno

# ------------------------------------------------------------
# BEZREALITKY.CZ – scraping výsledků přes jejich API
# ------------------------------------------------------------
def hledej_bezrealitky():
    nalezeno = []
    # Benešov GPS souřadnice: 49.7818, 14.6868
    typy = [
        {"offerType": "prodej", "estateType": "pozemek", "label": "Pozemek"},
        {"offerType": "prodej", "estateType": "dum",     "label": "Dům"},
    ]
    for typ in typy:
        url = (
            f"https://www.bezrealitky.cz/api/record/markers"
            f"?offerType={typ['offerType']}"
            f"&estateType={typ['estateType']}"
            f"&priceMin=1000000&priceMax=5800000"
            f"&lat=49.7818&lng=14.6868&radius=10"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            print(f"[Bezrealitky {typ['label']}] HTTP {r.status_code}")
            if r.status_code != 200:
                # Zkus alternativní endpoint
                url2 = (
                    f"https://www.bezrealitky.cz/vyhledavani-nemovitosti"
                    f"?offerType=prodej&estateType={typ['estateType']}"
                    f"&priceMin=1000000&priceMax=5800000"
                    f"&city=Ben%C4%9B%C5%A1ov&radius=10"
                )
                r = requests.get(url2, headers={**HEADERS, "Accept": "text/html"}, timeout=15)
                print(f"[Bezrealitky {typ['label']}] Alt HTTP {r.status_code}")
                # Parsuj ID z HTML
                ids = re.findall(r'nemovitosti-byty-domy/([a-z0-9-]+)', r.text)
                ids = list(set(ids))
                print(f"[Bezrealitky {typ['label']}] Nalezeno ID: {len(ids)}")
                for eid in ids[:20]:
                    nalezeno.append({
                        "id": f"bezrealitky_{eid}",
                        "zdroj": "Bezrealitky.cz",
                        "typ": typ["label"],
                        "nazev": f"{typ['label']} – Benešov a okolí",
                        "cena_str": "",
                        "lokalita": "Benešov a okolí",
                        "link": f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{eid}",
                    })
                continue

            items = r.json()
            if not isinstance(items, list):
                items = items.get("results", []) if isinstance(items, dict) else []
            print(f"[Bezrealitky {typ['label']}] Nalezeno: {len(items)}")
            for item in items[:30]:
                eid = str(item.get("id", ""))
                cena = item.get("price", 0)
                adresa = item.get("address", item.get("city", ""))
                uri = item.get("uri", eid)
                nalezeno.append({
                    "id": f"bezrealitky_{eid}",
                    "zdroj": "Bezrealitky.cz",
                    "typ": typ["label"],
                    "nazev": f"{typ['label']} – {adresa}",
                    "cena_str": f"{cena:,} Kč".replace(",", " ") if cena else "",
                    "lokalita": adresa,
                    "link": f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{uri}",
                })
        except Exception as ex:
            print(f"[Bezrealitky {typ['label']}] Chyba: {ex}")
    return nalezeno

# ------------------------------------------------------------
# REALITY.CZ – scraping HTML
# ------------------------------------------------------------
def hledej_reality_cz():
    nalezeno = []
    dotazy = [
        {
            "url": "https://www.reality.cz/pozemky/prodej/?search[region]=Bene%C5%A1ov&search[price_from]=1000000&search[price_to]=5800000&search[radius]=10",
            "label": "Pozemek"
        },
        {
            "url": "https://www.reality.cz/rodinne-domy/prodej/?search[region]=Bene%C5%A1ov&search[price_from]=1000000&search[price_to]=5800000&search[radius]=10",
            "label": "Dům"
        },
    ]
    for dotaz in dotazy:
        try:
            r = requests.get(dotaz["url"], headers={**HEADERS, "Accept": "text/html"}, timeout=15)
            print(f"[Reality.cz {dotaz['label']}] HTTP {r.status_code}")
            # Hledej ID inzerátů v HTML
            ids = re.findall(r'/nemovitost/(\d+)', r.text)
            ids = list(set(ids))
            print(f"[Reality.cz {dotaz['label']}] Nalezeno ID: {len(ids)}")
            # Hledej názvy
            nazvy = re.findall(r'<h2[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h2>', r.text, re.DOTALL)
            nazvy = [re.sub(r'<[^>]+>', '', n).strip() for n in nazvy]
            for i, eid in enumerate(ids[:20]):
                nazev = nazvy[i] if i < len(nazvy) else f"{dotaz['label']} – Benešov a okolí"
                nalezeno.append({
                    "id": f"reality_{eid}",
                    "zdroj": "Reality.cz",
                    "typ": dotaz["label"],
                    "nazev": nazev,
                    "cena_str": "",
                    "lokalita": "Benešov a okolí",
                    "link": f"https://www.reality.cz/nemovitost/{eid}/",
                })
        except Exception as ex:
            print(f"[Reality.cz {dotaz['label']}] Chyba: {ex}")
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
    <ul style='color:#555;font-size:13px'>
      <li>Typ: Pozemky a Domy k prodeji</li>
      <li>Lokalita: Benešov a okolí 10 km</li>
      <li>Cena: 1 000 000 – 5 800 000 Kč</li>
    </ul>
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
