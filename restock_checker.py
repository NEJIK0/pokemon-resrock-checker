import sys
import os
import json
import time
import smtplib
import ssl
import requests
from email.mime.text import MIMEText

PRODUCT_URL = "https://www.smythstoys.com/ch/de-ch/spielzeug/action-spielzeug/pokemon/pokemon-karten/pokemon-karten-boosterbundle-mega-entwicklung-erhabene-helden-sortiert/p/260843"
SOLD_OUT_TEXT = "OutOfStock"
STATE_FILE = "state.json"
MAX_RETRIES = 3
RETRY_DELAY = 30
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

def get_product_page():
    session = requests.Session()
    session.headers.update(HEADERS)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"🔎 Abruf der Produktseite (Versuch {attempt}/{MAX_RETRIES})")
            response = session.get(PRODUCT_URL, timeout=20, allow_redirects=True)
            print(f"HTTP-Status: {response.status_code}")
            print(f"Antwortlänge: {len(response.text)} Zeichen")
            if response.status_code == 200:
                return response
            if response.status_code in (403, 429, 503):
                print(f"⚠️ Zugriff momentan nicht möglich (HTTP {response.status_code}).")
                if attempt < MAX_RETRIES:
                    print(f"⏳ Warte {RETRY_DELAY} Sekunden vor dem nächsten Versuch...")
                    time.sleep(RETRY_DELAY)
                continue
            print(f"⚠️ Unerwarteter HTTP-Status: {response.status_code}")
            return None
        except requests.RequestException as e:
            print(f"⚠️ Netzwerkfehler: {e}")
            if attempt < MAX_RETRIES:
                print(f"⏳ Warte {RETRY_DELAY} Sekunden vor dem nächsten Versuch...")
                time.sleep(RETRY_DELAY)
    print("❌ Produktseite konnte nicht zuverlässig abgerufen werden.")
    return None

def is_in_stock():
    response = get_product_page()
    if response is None:
        return None
    html = response.text
    print(f"Enthält '{SOLD_OUT_TEXT}': {SOLD_OUT_TEXT in html}")
    return SOLD_OUT_TEXT not in html

def load_previous_state():
    if not os.path.exists(STATE_FILE):
        return False
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("in_stock", False)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ state.json konnte nicht gelesen werden: {e}")
        return False

def save_state(in_stock):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"in_stock": in_stock, "last_check": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=2)

def send_email_notification():
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("⚠️ E-Mail-Zugangsdaten fehlen (GitHub Secrets nicht gesetzt).")
        return
    msg = MIMEText(
        f"Das Produkt ist wieder auf Lager!\n\n{PRODUCT_URL}\n\nSchnell zuschlagen, bevor es wieder ausverkauft ist!",
        "plain", "utf-8"
    )
    msg["Subject"] = "🔔 Produkt wieder verfügbar!"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print("📧 E-Mail-Benachrichtigung wurde verschickt.")

def main():
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"Restock Checker – {timestamp}")
    print("=" * 60)
    try:
        in_stock = is_in_stock()
        if in_stock is None:
            print("⚠️ Status konnte nicht zuverlässig bestimmt werden.")
            print("ℹ️ Der bisherige Status bleibt unverändert.")
            return
        was_in_stock = load_previous_state()
        if in_stock and not was_in_stock:
            print("🎉 NEU VERFÜGBAR!")
            send_email_notification()
        elif in_stock:
            print("✅ Weiterhin verfügbar (bereits gemeldet).")
        else:
            print("❌ Ausverkauft.")
        save_state(in_stock)
    except Exception as e:
        print(f"❌ Unerwarteter Fehler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
