"""
Restock-Checker für Smith Toys (oder jede andere Shop-Seite)
==============================================================

Was das Skript macht:
1. Ruft EINMAL die Produktseite auf.
2. Prüft mit BeautifulSoup, ob das Produkt verfügbar ist.
3. Vergleicht mit dem letzten bekannten Status (gespeichert in state.json).
4. Schickt NUR dann eine E-Mail, wenn sich der Status von
   "ausverkauft" zu "verfügbar" ändert (nicht bei jedem Lauf).
5. Aktualisiert state.json mit dem neuen Status.

Gedacht für den Betrieb per GitHub Actions (Cronjob-Ersatz).

Bevor du loslegst, musst du anpassen (siehe "KONFIGURATION" unten):
  - PRODUCT_URL   -> Link zur Produktseite bei Smith Toys
  - SOLD_OUT_TEXT -> welcher Text im HTML "ausverkauft" bedeutet

Die E-Mail-Zugangsdaten kommen NICHT hierher, sondern werden als
GitHub Secrets gesetzt und über Umgebungsvariablen eingelesen
(siehe Anleitung im Chat).

Installation (lokal zum Testen):
    pip install requests beautifulsoup4
"""

import sys
import os
import json
import time
import smtplib
import ssl
import requests
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# ============================================================
# KONFIGURATION – hier musst du deine eigenen Werte eintragen
# ============================================================

PRODUCT_URL = "https://www.smythstoys.com/ch/de-ch/spielzeug/action-spielzeug/pokemon/pokemon-karten/pokemon-karten-mega-entwicklung-fatale-flammen-top-trainer-box/p/254125"  # <-- anpassen

# Ein Text, der auf der Seite auftaucht, WENN das Produkt
# ausverkauft ist. Sobald dieser Text NICHT mehr gefunden wird,
# gehen wir davon aus, dass es wieder verfügbar ist.
# -> Musst du im HTML der Produktseite nachschauen (siehe unten "So findest du den richtigen Text")
SOLD_OUT_TEXT = "Nicht vorrätig"

# Datei, in der der letzte bekannte Status gespeichert wird,
# damit wir zwischen den Läufen wissen, ob sich etwas geändert hat.
STATE_FILE = "state.json"

# E-Mail-Zugangsdaten werden aus Umgebungsvariablen gelesen
# (= GitHub Secrets). NIEMALS Passwörter direkt im Code eintragen!
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

# Ein normaler Browser-User-Agent, damit die Anfrage nicht
# sofort als Bot erkannt wird
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ============================================================
# FUNKTIONEN
# ============================================================

def is_in_stock() -> bool:
    """Lädt die Produktseite und prüft, ob sie als verfügbar gilt."""
    response = requests.get(PRODUCT_URL, headers=HEADERS, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text()

    # Wenn der "Ausverkauft"-Text NICHT mehr im Seitentext vorkommt,
    # gehen wir davon aus, dass das Produkt verfügbar ist.
    return SOLD_OUT_TEXT not in page_text


def load_previous_state() -> bool:
    """Liest den zuletzt gespeicherten Status. Falls die Datei nicht
    existiert (erster Lauf), gehen wir von 'ausverkauft' aus."""
    if not os.path.exists(STATE_FILE):
        return False
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("in_stock", False)


def save_state(in_stock: bool):
    """Speichert den aktuellen Status in state.json."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"in_stock": in_stock, "last_check": time.strftime("%Y-%m-%d %H:%M:%S")}, f)


def send_email_notification():
    """Verschickt eine E-Mail über SMTP."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("E-Mail-Zugangsdaten fehlen (Secrets nicht gesetzt) — überspringe Mailversand.")
        return

    subject = "🔔 Pokemon-Karten sind wieder verfügbar!"
    body = (
        f"Das Produkt ist wieder auf Lager:\n\n{PRODUCT_URL}\n\n"
        "Schnell zuschlagen, bevor es wieder ausverkauft ist!"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())

    print("E-Mail-Benachrichtigung wurde verschickt.")


def main():
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        in_stock = is_in_stock()
        was_in_stock = load_previous_state()

        if in_stock and not was_in_stock:
            print(f"[{timestamp}] ✅ Neu verfügbar! Sende E-Mail...")
            send_email_notification()
        elif in_stock:
            print(f"[{timestamp}] ✅ Weiterhin verfügbar (bereits gemeldet).")
        else:
            print(f"[{timestamp}] ❌ Ausverkauft.")

        save_state(in_stock)

    except requests.RequestException as e:
        print(f"[{timestamp}] Fehler beim Abrufen der Seite: {e}")
        sys.exit(1)  # Exit-Code 1 signalisiert GitHub Actions einen Fehler


if __name__ == "__main__":
    main()
