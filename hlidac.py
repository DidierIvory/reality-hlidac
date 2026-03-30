import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ============================================================
# KONFIGURACE – vyplň jen toto
# ============================================================
EMAIL_ADRESA = os.environ.get("EMAIL_ADRESA", "tvuj@gmail.com")
EMAIL_HESLO  = os.environ.get("EMAIL_HESLO", "")   # Gmail App Password
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
# SREALITY.CZ
# ------------------------------------------------------------
def hledej_sreality():
    nalezeno = []
    kategorie = [
        {"cat_main": 1, "cat_sub": 3, "label": "Pozemek"},   # pozemky – bydlení
        {"cat_main": 1, "cat_sub": 1, "label": "Dům"},        # domy
    ]
    for kat in kategorie:
        url = (
            "https://www.sreality.cz/api/cs/v2/estates"
            f"?category_main_cb={kat['cat_main']}"
            f"&category_sub_cb={kat['cat_sub']}"
            "&category_type_cb=1"          # prodej
            "&locality_region_id=2"        # Středočeský kraj
            "&locality_district_id=5103"   # Benešov
            "&locality_radius=10"          # 10 km okolí
            "&price_min=1000000"
            "&price_max=5800000"
            "&per_page=20"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            data = r.json()
            estates = data.get("_embedded", {}).get("estates", [])
            for e in estates:
                eid = str(e.get("hash_id", ""))
                nazev = e.get("name", "Bez názvu")
                cena_info = e.get("price_czk", {})
                cena = cena_info.get("value_raw", 0)
                lokalita = e.get("locality", "")
                link = f"https://www.sreality.cz/detail/{eid}"
                nalezeno.append({
                    "id": f"sreality_{eid}",
                    "zdroj": "Sreality.cz",
                    "typ": kat["label"],
                    "nazev": nazev,
                    "cena": cena,
                    "lokalita": lokalita,
                    "link": link,
                })
        except Exception as ex:
            print(f"[Sreality] Chyba: {ex}")
    return nalezeno

# ------------------------------------------------------------
# BEZREALITKY.CZ
# ------------------------------------------------------------
def hledej_bezrealitky():
    nalezeno = []
    typy = [
        {"offerType": "sale", "estateType": "land",   "label": "Pozemek"},
        {"offerType": "sale", "estateType": "house",  "label": "Dům"},
    ]
    for typ in typy:
        url = (
            "https://www.bezrealitky.cz/api/record/markers"
            f"?offerType={typ['offerType']}"
            f"&estateType={typ['estateType']}"
            "&boundary=%7B%22lat%22%3A49.7818%2C%22lng%22%3A14.6868%7D"  # Benešov střed
            "&radius=10"
            "&priceMin=1000000"
            "&priceMax=5800000"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            items = r.json() if r.status_code == 200 else []
            if isinstance(items, list):
                for item in items[:30]:
                    eid = str(item.get("id", ""))
                    cena = item.get("price", 0)
                    lokalita = item.get("city", "")
                    link = f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{eid}"
                    nalezeno.append({
                        "id": f"bezrealitky_{eid}",
                        "zdroj": "Bezrealitky.cz",
                        "typ": typ["label"],
                        "nazev": f"{typ['label']} – {lokalita}",
                        "cena": cena,
                        "lokalita": lokalita,
                        "link": link,
                    })
        except Exception as ex:
            print(f"[Bezrealitky] Chyba: {ex}")
    return nalezeno

# ------------------------------------------------------------
# REALITY.CZ  (RSS feed)
# ------------------------------------------------------------
def hledej_reality_cz():
    nalezeno = []
    feeds = [
        {
            "url": (
                "https://www.reality.cz/rss/?s%5Btype%5D=1"  # prodej
                "&s%5Bkind%5D%5B%5D=4"                        # pozemky
                "&s%5Blocality%5D=Bene%C5%A1ov"
                "&s%5Bprice_from%5D=1000000&s%5Bprice_to%5D=5800000"
            ),
            "label": "Pozemek"
        },
        {
            "url": (
                "https://www.reality.cz/rss/?s%5Btype%5D=1"  # prodej
                "&s%5Bkind%5D%5B%5D=2"                        # domy
                "&s%5Blocality%5D=Bene%C5%A1ov"
                "&s%5Bprice_from%5D=1000000&s%5Bprice_to%5D=5800000"
            ),
            "label": "Dům"
        },
    ]
    import xml.etree.ElementTree as ET
    for feed in feeds:
        try:
            r = requests.get(feed["url"], headers=HEADERS, timeout=15)
            root = ET.fromstring(r.content)
            for item in root.iter("item"):
                link = item.findtext("link", "")
                title = item.findtext("title", "Bez názvu")
                guid = item.findtext("guid", link)
                eid = guid.split("/")[-1] if guid else link
                nalezeno.append({
                    "id": f"reality_{eid}",
                    "zdroj": "Reality.cz",
                    "typ": feed["label"],
                    "nazev": title,
                    "cena": 0,
                    "lokalita": "Benešov a okolí",
                    "link": link,
                })
        except Exception as ex:
            print(f"[Reality.cz] Chyba: {ex}")
    return nalezeno

# ------------------------------------------------------------
# EMAIL
# ------------------------------------------------------------
def posli_email(nove_inzeraty):
    if not nove_inzeraty:
        return

    radky = []
    for inz in nove_inzeraty:
        cena_str = f"{inz['cena']:,} Kč".replace(",", " ") if inz["cena"] else "cena neuvedena"
        radky.append(
            f"<tr>"
            f"<td style='padding:6px;border-bottom:1px solid #eee'>{inz['zdroj']}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee'>{inz['typ']}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee'>{inz['nazev']}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee'>{inz['lokalita']}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee'>{cena_str}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee'>"
            f"<a href='{inz['link']}'>Zobrazit</a></td>"
            f"</tr>"
        )

    html = f"""
    <html><body>
    <h2>🏡 Nové nemovitosti – Benešov a okolí</h2>
    <p>Nalezeno <b>{len(nove_inzeraty)}</b> nových inzerátů odpovídajících tvým kritériím:</p>
    <table style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px'>
      <thead>
        <tr style='background:#f0f0f0'>
          <th style='padding:8px'>Zdroj</th>
          <th style='padding:8px'>Typ</th>
          <th style='padding:8px'>Název</th>
          <th style='padding:8px'>Lokalita</th>
          <th style='padding:8px'>Cena</th>
          <th style='padding:8px'>Odkaz</th>
        </tr>
      </thead>
      <tbody>{''.join(radky)}</tbody>
    </table>
    <p style='color:gray;font-size:12px'>Automatický hlídač nemovitostí • {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
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
