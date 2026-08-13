import sys
import os
import json
import time
import smtplib
import ssl
import requests

from email.mime.text import MIMEText


# ============================================================
# KONFIGURATION
# ============================================================

PRODUCT_URL = (
    "https://www.smythstoys.com/ch/de-ch/spielzeug/action-spielzeug/"
    "pokemon/pokemon-karten/"
    "pokemon-karten-boosterbundle-mega-entwicklung-erhabene-helden-sortiert/"
    "p/260843"
)

# Diese Begriffe bedeuten: Produkt ist nicht verfügbar.
OUT_OF_STOCK_MARKERS = [
    "OutOfStock",
    "Nicht vorrätig",
]

STATE_FILE = "state.json"

# Maximale Anzahl Versuche pro GitHub-Actions-Lauf
MAX_RETRIES = 3

# Wartezeit zwischen den Versuchen
RETRY_DELAY = 30


# ============================================================
# E-MAIL
# ============================================================

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))

EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")


# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


# ============================================================
# PRODUKTSEITE ABRUFEN
# ============================================================

def get_product_page():
    """
    Ruft die Produktseite normal ab.

    Rückgabe:
        response -> HTTP 200 und HTML erhalten
        None     -> Seite konnte nicht zuverlässig geprüft werden

    403/429/503 werden nicht als "ausverkauft" interpretiert.
    """

    session = requests.Session()
    session.headers.update(HEADERS)

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            print(
                f"🔎 Produktseite wird abgerufen "
                f"(Versuch {attempt}/{MAX_RETRIES})"
            )

            response = session.get(
                PRODUCT_URL,
                timeout=20,
                allow_redirects=True,
            )

            print(f"HTTP-Status: {response.status_code}")
            print(f"Antwortlänge: {len(response.text)} Zeichen")
            print(f"Finale URL: {response.url}")

            # Erfolgreicher Abruf
            if response.status_code == 200:
                return response

            # Typische WAF-/Rate-Limit-Antworten
            if response.status_code in (403, 429, 503):

                print(
                    f"⚠️ Zugriff momentan nicht möglich "
                    f"(HTTP {response.status_code})."
                )

                if attempt < MAX_RETRIES:
                    print(
                        f"⏳ Warte {RETRY_DELAY} Sekunden "
                        f"vor dem nächsten Versuch..."
                    )
                    time.sleep(RETRY_DELAY)

                continue

            print(
                f"⚠️ Unerwarteter HTTP-Status: "
                f"{response.status_code}"
            )

            return None

        except requests.RequestException as e:

            print(f"⚠️ Netzwerkfehler: {e}")

            if attempt < MAX_RETRIES:
                print(
                    f"⏳ Warte {RETRY_DELAY} Sekunden "
                    f"vor dem nächsten Versuch..."
                )
                time.sleep(RETRY_DELAY)

    print(
        "❌ Produktseite konnte nicht zuverlässig geprüft werden."
    )

    return None


# ============================================================
# LAGERSTATUS
# ============================================================

def is_in_stock():
    """
    Rückgabe:

        True  = verfügbar
        False = ausverkauft
        None  = Seite konnte nicht zuverlässig geprüft werden

    Wichtig:
    Bei einem Fehler wird NICHT "verfügbar" angenommen.
    """

    response = get_product_page()

    if response is None:
        return None

    html = response.text

    # Debug-Ausgabe
    for marker in OUT_OF_STOCK_MARKERS:

        print(
            f"Enthält '{marker}': "
            f"{marker in html}"
        )

    # Einer der bekannten Ausverkauft-Marker gefunden
    for marker in OUT_OF_STOCK_MARKERS:

        if marker in html:

            print(
                f"❌ Nicht verfügbar erkannt "
                f"(Marker: {marker})"
            )

            return False

    # Nur bei erfolgreichem HTTP-200-Abruf und
    # ohne Ausverkauft-Marker wird verfügbar angenommen.
    print(
        "✅ Kein Ausverkauft-Marker gefunden – verfügbar."
    )

    return True


# ============================================================
# STATUS LADEN
# ============================================================

def load_previous_state():

    if not os.path.exists(STATE_FILE):

        print(
            "ℹ️ Keine state.json vorhanden – "
            "erster Lauf wird als ausverkauft behandelt."
        )

        return False

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        previous = bool(
            data.get("in_stock", False)
        )

        print(
            "Vorheriger Status: "
            f"{'verfügbar' if previous else 'ausverkauft'}"
        )

        return previous

    except (
        json.JSONDecodeError,
        OSError
    ) as e:

        print(
            f"⚠️ state.json konnte nicht gelesen werden: {e}"
        )

        return False


# ============================================================
# STATUS SPEICHERN
# ============================================================

def save_state(in_stock):

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "in_stock": in_stock,
                "last_check": time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            },
            f,
            indent=2,
        )

    print(
        "Status gespeichert: "
        f"{'verfügbar' if in_stock else 'ausverkauft'}"
    )


# ============================================================
# E-MAIL SENDEN
# ============================================================

def send_email_notification():

    if not all(
        [
            EMAIL_SENDER,
            EMAIL_PASSWORD,
            EMAIL_RECEIVER,
        ]
    ):

        print(
            "⚠️ E-Mail-Zugangsdaten fehlen "
            "(GitHub Secrets nicht gesetzt)."
        )

        return

    subject = (
        "🔔 Pokémon Karten wieder verfügbar!"
    )

    body = (
        "Das Produkt ist wieder auf Lager!\n\n"
        f"{PRODUCT_URL}\n\n"
        "Schnell prüfen, bevor es wieder "
        "ausverkauft ist!"
    )

    msg = MIMEText(
        body,
        "plain",
        "utf-8",
    )

    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER

    context = ssl.create_default_context()

    with smtplib.SMTP_SSL(
        SMTP_SERVER,
        SMTP_PORT,
        context=context,
    ) as server:

        server.login(
            EMAIL_SENDER,
            EMAIL_PASSWORD,
        )

        server.sendmail(
            EMAIL_SENDER,
            EMAIL_RECEIVER,
            msg.as_string(),
        )

    print(
        "📧 E-Mail-Benachrichtigung wurde verschickt."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    timestamp = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print("=" * 60)
    print(
        f"Restock Checker – {timestamp}"
    )
    print("=" * 60)

    try:

        in_stock = is_in_stock()

        # ----------------------------------------------------
        # SEITE NICHT ZUVERLÄSSIG ERREICHBAR
        # ----------------------------------------------------

        if in_stock is None:

            print(
                "⚠️ Lagerstatus konnte nicht zuverlässig "
                "bestimmt werden."
            )

            print(
                "ℹ️ Keine E-Mail wird verschickt."
            )

            print(
                "ℹ️ Der bisherige Status bleibt unverändert."
            )

            return

        # ----------------------------------------------------
        # VORHERIGEN STATUS LADEN
        # ----------------------------------------------------

        was_in_stock = load_previous_state()

        # ----------------------------------------------------
        # RESTOCK ERKANNT
        # ----------------------------------------------------

        if in_stock and not was_in_stock:

            print(
                "🎉 RESTOCK ERKANNT!"
            )

            send_email_notification()

        # ----------------------------------------------------
        # WEITERHIN VERFÜGBAR
        # ----------------------------------------------------

        elif in_stock:

            print(
                "✅ Weiterhin verfügbar "
                "(bereits gemeldet)."
            )

        # ----------------------------------------------------
        # AUSVERKAUFT
        # ----------------------------------------------------

        else:

            print(
                "❌ Ausverkauft."
            )

        # Nur bei einem erfolgreichen Abruf
        # den Status aktualisieren.
        save_state(in_stock)

    except Exception as e:

        print(
            f"❌ Unerwarteter Fehler: {e}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
