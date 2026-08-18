#!/usr/bin/env python3
"""CHILE-OEF — Telegram Notification & Anomaly Alert Script.

Sends formatted statistical alerts to Telegram channels/chats following
the strict CHILE-OEF Communication Policy (no earthquake alarms or predictions).
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_BOT_TOKEN = os.getenv(
    "CHILE_OEF_TELEGRAM_BOT_TOKEN",
    "8809786212:AAGDWCfSg0WxkC0siPYPjn70GOWdcjGP6Tw"
)
DEFAULT_CHANNEL_ID = os.getenv("CHILE_OEF_TELEGRAM_CHANNEL_ID", "")
API_BASE = "https://chile-oef-api.onrender.com/v1"


def send_telegram_message(bot_token: str, chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            return res_json.get("ok", False)
    except Exception as e:
        print(f"[ERROR] Error al enviar mensaje a Telegram: {e}", file=sys.stderr)
        return False


function_format_chance = lambda prob: f"{prob*100:.1f}%" if prob >= 0.01 else f"1 en {round(1/prob):,}" if prob > 0 else "0%"


def format_test_message() -> str:
    """Generate a test message adhering to CHILE-OEF communication policy."""
    return (
        "📊 *CHILE-OEF — Notificación de Prueba*\n\n"
        "🟢 Bot configurado correctamente.\n"
        "📍 *Sistema*: Modelo ETAS mwc + Gutenberg–Richter (USGS 1964–2026)\n"
        "⚡ *Estado*: Conectado y operativo.\n\n"
        "ℹ️ _Este canal notificará secuencias de réplicas y tasas anómalas relativas. "
        "No predice terremotos ni emite alarmas de evacuación. "
        "Fuentes oficiales: CSN y SENAPRED._\n\n"
        "🌐 [Ver informe completo en etemen.cl/chile-oef/](https://etemen.cl/chile-oef/)"
    )


def format_anomaly_message(
    zone_name: str,
    event_mag: float,
    event_loc: str,
    ias_index: float,
    prob_7d: float,
    baseline_prob: float,
) -> str:
    """Format an anomaly alert adhering to scientific communication guidelines."""
    ratio = f"{ias_index:.1f}x" if ias_index else "elevada"
    chance_str = function_format_chance(prob_7d)
    baseline_str = function_format_chance(baseline_prob)

    return (
        f"📊 *CHILE-OEF — Notificación de Anomalía Sísmica*\n\n"
        f"📍 *Zona*: {zone_name}\n"
        f"⚡ *Evento detonante*: M {event_mag:.1f} — {event_loc}\n"
        f"📈 *Índice IAS*: *{ratio}* sobre la tasa histórica de fondo.\n"
        f"🎲 *Probabilidad ETAS (7d, M≥5.0)*: *{chance_str}* (vs {baseline_str} habitual)\n\n"
        f"ℹ️ _Estadística experimental sobre patrones de sismicidad. "
        f"No constituye predicción determinista ni alarma de emergencia. "
        f"Fuentes oficiales: [CSN](https://www.csn.uchile.cl/) y [SENAPRED](https://www.senapred.cl/)._\n\n"
        f"🌐 [Ver informe completo en etemen.cl/chile-oef/](https://etemen.cl/chile-oef/)"
    )


def main():
    parser = argparse.ArgumentParser(description="CHILE-OEF Telegram Alert Tool")
    parser.add_argument("--token", default=DEFAULT_BOT_TOKEN, help="Telegram Bot Token")
    parser.add_argument("--chat-id", default=DEFAULT_CHANNEL_ID, help="Telegram Chat ID or @channel_name")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    parser.add_argument("--message", help="Custom text message to send")

    args = parser.parse_args()

    if not args.chat_id:
        print("[AVISO] Debe especificar --chat-id (ej: @mi_canal) o configurar CHILE_OEF_TELEGRAM_CHANNEL_ID")
        sys.exit(1)

    if args.test:
        print(f"[INFO] Enviando mensaje de prueba a {args.chat_id}...")
        ok = send_telegram_message(args.token, args.chat_id, format_test_message())
        if ok:
            print("[ÉXITO] Mensaje enviado correctamente.")
        else:
            print("[FALLO] No se pudo enviar el mensaje.")
    elif args.message:
        ok = send_telegram_message(args.token, args.chat_id, args.message)
        if ok:
            print("[ÉXITO] Mensaje personalizado enviado.")
        else:
            print("[FALLO] Error al enviar mensaje.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
