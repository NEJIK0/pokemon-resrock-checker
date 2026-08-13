"""
Restock-Checker für Smith Toys (oder jede andere Shop-Seite)
==============================================================

Was das Skript macht:
1. Ruft EINMAL die Produktseite auf — mit einem echten, headless
   laufenden Chromium-Browser (Playwright), nicht mit einer reinen
   HTTP-Anfrage. Das lässt JavaScript normal ausführen, so wie es
   ein Mensch mit einem Browser auch tun würde.
2. Prüft, ob das Produkt verfügbar ist.
3. Vergleicht mit dem letzten bekannten Status (gespeichert in state.json).
4. Schickt NUR dann eine E-Mail, wenn sich der Status von
   "ausverkauft" zu "verfügbar" ändert (nicht bei jedem Lauf).
5. Aktualisiert state.json mit dem neuen Status.

WICHTIGER HINWEIS:
Manche Websites setzen Bot-Schutz-Systeme (z.B. Incapsula/Imperva)
ein, die aktiv versuchen, automatisierte Zugriffe zu erkennen und
zu blockieren - auch von echten Browsern wie diesem. Dieses Skript
versucht NICHT, solche Schutzmassnahmen gezielt zu umgehen (kein
Fingerprint-Spoofing, kein Lösen von Challenges). Falls die Seite
weiterhin eine Blockseite statt der echten Produktseite ausliefert,
ist an dieser Stelle technisch wie auch inhaltlich Schluss - dann
bitte eine der Alternativen aus dem Chat nutzen (Kontakt zum Shop,
manuelle Prüfung, offizielle API/Feed, falls vorhanden).

Gedacht für den Betrieb per GitHub Actions.

Bevor du loslegst, musst du anpassen (siehe "KONFIGURATION" unten):
  - PRODUCT_URL   -> Link zur Produktseite bei Smith Toys
  - SOLD_OUT_TEXT -> welcher Text/Wert "ausverkauft" bedeutet

Die E-Mail-Zugangsdaten kommen NICHT hierher, sondern werden als
GitHub Secrets gesetzt und über Umgebungsvariablen eingelesen.

Installation (lokal zum Testen):
    pip install playwright beautifulsoup4
    playwright install --with-deps chromium
"""

import sys
import os
import json
import time
import smtplib
import ssl
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright

# ============================================================
# KONFIGURATION – hier musst du deine eigenen Werte eintragen
# ============================================================

PRODUCT_URL = "https://www.smith-toys.ch/dein-produkt-link"  # <-- anpassen

# Text/Wert, der auf der Seite auftaucht, WENN das Produkt
# ausverkauft ist. Sobald er NICHT mehr gefunden wird, gehen wir
# davon aus, dass es wieder verfügbar ist.
SOLD_OUT_TEXT = "OutOfStock"

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

# Wie lange (in Millisekunden) auf das vollständige Laden der Seite
# gewartet wird, bevor wir den Inhalt auslesen.
PAGE_LOAD_TIMEOUT_MS = 20000
WAIT_AFTER_LOAD_MS = 3000  # zusätzliche Wartezeit für nachladendes JS


# ============================================================
# FUNKTIONEN
# ============================================================

def fetch_rendered_html() -> str:
    """Öffnet die Seite in einem echten (headless) Chromium-Browser
    und gibt das HTML zurück, NACHDEM JavaScript ausgeführt wurde."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page.goto(PRODUCT_URL, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="networkidle")
        page.wait_for_timeout(WAIT_AFTER_LOAD_MS)
        html = page.content()
        browser.close()
    return html


def is_in_stock() -> bool:
    """Lädt die Produktseite (gerendert) und prüft, ob sie als
    verfügbar gilt."""
    html = fetch_rendered_html()

    # --- DEBUG: zeigt im Actions-Log, was wir tatsächlich empfangen haben ---
    print(f"DEBUG: Antwortlänge: {len(html)} Zeichen")
    print(f"DEBUG: Enthält '{SOLD_OUT_TEXT}': {SOLD_OUT_TEXT in html}")
    print(f"DEBUG: Enthält 'Incapsula': {'Incapsula' in html}")
    print(f"DEBUG: Erste 500 Zeichen:\n{html[:500]}")
    # --- ENDE DEBUG ---

    if "Incapsula" in html or len(html) < 3000:
        print("WARNUNG: Die Antwort sieht nach einer Bot-Schutz-Seite aus, "
              "nicht nach der echten Produktseite. Status kann nicht "
              "zuverlässig ermittelt werden - Ergebnis wird verworfen.")
        raise RuntimeError("Vermutlich durch Bot-Schutz blockiert")

    return SOLD_OUT_TEXT not in html


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

    except RuntimeError as e:
        # Vermutlich durch Bot-Schutz blockiert -> Status NICHT speichern,
        # damit ein blockierter Lauf keine falsche "Änderung" auslöst.
        print(f"[{timestamp}] {e}")
        sys.exit(1)

    except Exception as e:
        print(f"[{timestamp}] Fehler beim Abrufen der Seite: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
