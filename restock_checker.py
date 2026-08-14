import sys
import os
import json
import time
import smtplib
import ssl
from email.mime.text import MIMEText
from scrapfly import ScrapflyClient, ScrapeConfig

# ============================================================
# KONFIGURATION
# ============================================================

# Liste der zu überwachenden Produkte (Name & URL)
PRODUCTS = [

    {
        "name": "Pokémon Karten Mega-Entwicklung Wachsendes Chaos Top-Trainer-Box",
        "url": "https://www.smythstoys.com/ch/de-ch/spielzeug/action-spielzeug/pokemon/pokemon-karten/pokemon-karten-mega-entwicklung-wachsendes-chaos-top-trainer-box/p/260030"
    },

    # Hier kannst du beliebig viele weitere Produkte hinzufügen:
    # {
    #     "name": "Weiteres Produkt Name",
    #     "url": "https://www.smythstoys.com/.../p/123456"
    # },
]

# Text, der "ausverkauft" bedeutet
SOLD_OUT_TEXT = "OutOfStock"

STATE_FILE = "state.json"

# Zugangsdaten aus den GitHub Secrets
SCRAPFLY_API_KEY = os.environ.get("SCRAPFLY_API_KEY")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")


# ============================================================
# FUNKTIONEN
# ============================================================

def fetch_rendered_html(url: str) -> str:
    """Ruft eine spezifische Seite über Scrapfly ab."""
    if not SCRAPFLY_API_KEY:
        raise ValueError("SCRAPFLY_API_KEY wurde nicht in den Umgebungsvariablen/Secrets gefunden!")

    scrapfly = ScrapflyClient(key=SCRAPFLY_API_KEY)
    
    result = scrapfly.scrape(ScrapeConfig(
        url=url,
        asp=True,          # Umgeht Bot-Schutz
        render_js=True,    # Rendert JavaScript
        country="CH",      # Proxy aus der Schweiz
        proxy_pool=ScrapeConfig.PUBLIC_RESIDENTIAL_POOL,
    ))
    
    return result.scrape_result["content"]


def is_in_stock(url: str) -> bool:
    """Prüft, ob ein Produkt verfügbar ist."""
    html = fetch_rendered_html(url)

    if len(html) < 3000:
        raise RuntimeError("Antwort ist auffällig kurz – möglicherweise weiterhin blockiert.")

    return SOLD_OUT_TEXT not in html


def load_previous_state() -> dict:
    """Lädt den gesamten bisherigen Status aller Produkte aus state.json."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_state(state_data: dict):
    """Speichert den aktualisierten Status im JSON-Format."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=4, ensure_ascii=False)


def send_email_notification(product_name: str, product_url: str):
    """Verschickt eine E-Mail für ein bestimmtes Produkt."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("E-Mail-Zugangsdaten fehlen — überspringe Mailversand.", flush=True)
        return

    subject = f"🔔 Restock: {product_name} ist wieder verfügbar!"
    body = f"Das folgende Produkt ist wieder auf Lager:\n\n{product_name}\n{product_url}\n\nSchnell zuschlagen!"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())

    print(f"E-Mail-Benachrichtigung für '{product_name}' wurde verschickt.", flush=True)


def main():
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    state_data = load_previous_state()
    
    # flush=True sorgt dafür, dass die Nachricht SOFORT in GitHub Actions sichtbar ist
    print(f"[{timestamp}] Starte Prüfung für {len(PRODUCTS)} Produkte...\n", flush=True)

    for product in PRODUCTS:
        name = product["name"]
        url = product["url"]

        print(f"--- Prüfe: {name} ---", flush=True)

        try:
            in_stock = is_in_stock(url)
            was_in_stock = state_data.get(url, {}).get("in_stock", False)

            if in_stock and not was_in_stock:
                print(f"✅ Neu verfügbar! Sende E-Mail...", flush=True)
                send_email_notification(name, url)
            elif in_stock:
                print(f"✅ Weiterhin verfügbar.", flush=True)
            else:
                print(f"❌ Ausverkauft.", flush=True)

            # Status im Dict aktualisieren
            state_data[url] = {
                "name": name,
                "in_stock": in_stock,
                "last_check": timestamp
            }

        except Exception as e:
            print(f"Fehler beim Abrufen von '{name}': {e}", flush=True)

        # Pause zwischen Abfragen
        time.sleep(2)

    # Nach allen Produkten den Status speichern
    save_state(state_data)


if __name__ == "__main__":
    main()
