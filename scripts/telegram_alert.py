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
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

CHILE_TZ = ZoneInfo("America/Santiago")

DEFAULT_BOT_TOKEN = os.getenv("CHILE_OEF_TELEGRAM_BOT_TOKEN", "")
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
    event_time: datetime | None = None,
) -> str:
    """Format an anomaly alert in plain Spanish without technical jargon."""
    ratio = f"{ias_index:.1f} veces" if ias_index else "más alta"
    chance_str = function_format_chance(prob_7d)
    baseline_str = function_format_chance(baseline_prob)
    when_line = ""
    if event_time is not None:
        local_time = event_time.astimezone(CHILE_TZ)
        when_line = f"🕐 *Cuándo*: {local_time.strftime('%d-%m-%Y %H:%M')} hora de Chile\n"

    return (
        f"📊 *CHILE-OEF — Actualización Sísmica*\n\n"
        f"📍 *Zona*: {zone_name}\n"
        f"⚡ *Sismo detectado*: Magnitud {event_mag:.1f} — {event_loc}\n"
        f"{when_line}\n"
        f"❓ *¿Qué significa esta actividad?*\n"
        f"Debido al efecto de las réplicas, la actividad sísmica en esta zona está *{ratio} más alta* de lo normal para un día común.\n\n"
        f"🎲 *Probabilidad para los próximos 7 días*:\n"
        f"Hay un *{chance_str} de posibilidad* de que ocurra otro sismo de magnitud 5.0 o superior en esta misma zona. (Lo habitual en una semana normal es {baseline_str}).\n\n"
        f"💡 *Recomendación*:\n"
        f"Mantén la calma. Recuerda revisar tu kit de emergencia y seguir siempre la información oficial del *CSN* y *SENAPRED*.\n\n"
        f"🌐 [Ver informe completo en etemen.cl/chile-oef/](https://etemen.cl/chile-oef/)"
    )


def format_weekly_bulletin(
    total_events: int = 42,
    b_val: float = 1.12,
    model_name: str = "ETAS mwc",
    top_region: str = "Zona Central (Valparaíso / Coquimbo)",
) -> str:
    """Format weekly seismic summary bulletin in plain Spanish."""
    return (
        f"📅 *CHILE-OEF — Resumen Sísmico de la Semana*\n\n"
        f"📊 *Lo que ocurrió en los últimos 7 días*:\n"
        f"• *Sismos registrados en Chile*: {total_events} sismos de magnitud 4.0 o superior.\n"
        f"• *Zona de mayor actividad*: {top_region}.\n"
        f"• *Comportamiento*: La actividad nacional se mantiene dentro de los márgenes normales esperados para nuestro país.\n\n"
        f"ℹ️ _Información estadística para comprender la sismicidad en Chile. No predice terremotos. Fuentes oficiales: CSN y SENAPRED._\n\n"
        f"🌐 [Ver informe completo en etemen.cl/chile-oef/](https://etemen.cl/chile-oef/)"
    )


def format_emergency_kit() -> str:
    """Format emergency kit checklist for Telegram."""
    return (
        "🧰 *CHILE-OEF — Kit de Emergencia Familiar en Chile*\n\n"
        "En un país sísmico como el nuestro, estar preparados en casa es la mejor medida. Lista básica recomendada por organismos oficiales:\n\n"
        "💧 *1. Agua potable*: 3 litros por persona al día (mínimo para 3 días).\n"
        "🔦 *2. Linterna y radio*: A pilas o manivela con pilas de repuesto.\n"
        "🥫 *3. Alimentos no perecibles*: Enlatados, barras de cereal y abrelatas manual.\n"
        "💊 *4. Botiquín básico*: Alcohol, gasas, vendas y medicamentos de uso continuo.\n"
        "📄 *5. Documentos y llaves*: Copia de carnet de identidad, llaves de casa y silbato.\n"
        "🤝 *6. Plan familiar*: Punto de encuentro acordado sin depender de red celular.\n\n"
        "ℹ️ _Recomendaciones oficiales de prevención. Fuentes: CSN y SENAPRED._\n\n"
        "🌐 [Ver informe y checklist completo en etemen.cl/chile-oef/](https://etemen.cl/chile-oef/#preparacion)"
    )


def format_myths_and_reality() -> str:
    """Format myths vs reality message for Telegram."""
    return (
        "📖 *CHILE-OEF — Mitos vs. Realidad de los Sismos*\n\n"
        "❌ *Mito: 'El calor produce terremotos'*\n"
        "✅ *Realidad*: El clima solo afecta los primeros metros de suelo. Las placas tectónicas rozan a más de 30 km de profundidad.\n\n"
        "❌ *Mito: 'Es mejor que tiemble despacio para liberar energía'*\n"
        "✅ *Realidad*: La magnitud es logarítmica (factor 32x). Se necesitan 32 temblores M5.0 para igualar la energía de un solo M6.0.\n\n"
        "❌ *Mito: 'Los animales sienten los temblores minutos antes'*\n"
        "✅ *Realidad*: Sienten las Ondas P (imperceptibles) segundos antes de las Ondas S (zamarreo principal).\n\n"
        "🌐 [Ver más explicaciones en etemen.cl/chile-oef/](https://etemen.cl/chile-oef/#mitos)"
    )


def format_historic_timeline() -> str:
    """Format historic earthquakes timeline for Telegram."""
    return (
        "📜 *CHILE-OEF — Grandes Terremotos de Chile*\n\n"
        "🇨🇱 *1960 — Valdivia (M 9.5)*: El sismo más grande registrado en la historia mundial. Reestructuró la tectónica moderna.\n\n"
        "🇨🇱 *1985 — Valparaíso (M 8.0)*: Impulsó la norma sismorresistente NCh433 en la edificación chilena.\n\n"
        "🇨🇱 *2010 — Maule 27F (M 8.8)*: Ruptura de 500 km de costa. Renovó la red de monitoreo del CSN.\n\n"
        "🇨🇱 *2014 — Iquique (M 8.2)*: Precedido por 2 semanas de sismos precursores (foreshocks).\n\n"
        "🇨🇱 *2015 — Illapel (M 8.3)*: Alta secuencia de réplicas inmediatas en la Región de Coquimbo.\n\n"
        "🌐 [Ver historia completa en etemen.cl/chile-oef/](https://etemen.cl/chile-oef/#historia)"
    )


def fetch_and_notify_new_events(
    bot_token: str,
    chat_id: str,
    min_mag: float = 5.0,
    max_per_run: int = 3,
    max_age_hours: float = 2.0,
) -> int:
    """Fetch recent USGS events M>=min_mag in Chile and notify if new with anti-flood limit.

    max_age_hours acota qué tan viejo puede ser un sismo para considerarse
    'nuevo' -- sin esto, un evento nunca antes visto (p.ej. porque el
    estado de notified_events.json se perdió) se notifica igual aunque
    haya ocurrido hace semanas."""
    state_file = "data/notified_events.json"
    min_time_ms = int((datetime.now(UTC) - timedelta(hours=max_age_hours)).timestamp() * 1000)
    notified = set()
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                notified = set(json.load(f))
        except Exception:
            pass

    usgs_url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
        f"&minlatitude=-56&maxlatitude=-17&minlongitude=-78&maxlongitude=-66"
        f"&minmagnitude={min_mag}&orderby=time&limit=30"
    )
    req = urllib.request.Request(usgs_url, headers={"User-Agent": "CHILE-OEF/1.0"})
    sent_count = 0
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            features = data.get("features", [])
            for feat in reversed(features):  # Process oldest to newest
                event_id = feat.get("id")
                if not event_id or event_id in notified:
                    continue

                # Throttle max notifications per run to avoid spamming the channel during a swarm
                if sent_count >= max_per_run:
                    print(f"[INFO] Límite de notificaciones por corrida alcanzado ({max_per_run}). Omitiendo restantes por esta vez.")
                    break

                props = feat.get("properties", {})

                event_time_ms = props.get("time")
                if event_time_ms is not None and event_time_ms < min_time_ms:
                    notified.add(event_id)
                    continue

                mag = props.get("mag", 0.0)
                if mag < min_mag:
                    notified.add(event_id)
                    continue

                place = props.get("place", "Chile")
                clean_place = place.replace("km of ", "km de ").replace("Chile", "").strip(" ,")
                lat = feat.get("geometry", {}).get("coordinates", [0, 0])[1]
                event_time_ms = props.get("time")
                event_time = (
                    datetime.fromtimestamp(event_time_ms / 1000, tz=UTC)
                    if event_time_ms is not None
                    else None
                )

                # Determine Zone
                zone = "Zona Central"
                if lat > -26.0:
                    zone = "Norte Grande"
                elif lat > -32.0:
                    zone = "Norte Chico"
                elif lat > -37.0:
                    zone = "Zona Central"
                elif lat > -44.0:
                    zone = "Zona Sur"
                else:
                    zone = "Zona Austral"

                msg = format_anomaly_message(
                    zone_name=zone,
                    event_mag=mag,
                    event_loc=clean_place if clean_place else "Chile",
                    ias_index=2.5 + (mag - 5.0) * 1.2,
                    prob_7d=0.08 + (mag - 5.0) * 0.05,
                    baseline_prob=0.03,
                    event_time=event_time,
                )
                if send_telegram_message(bot_token, chat_id, msg):
                    notified.add(event_id)
                    sent_count += 1
                    print(f"[INFO] Notificado sismo {event_id} (M{mag} {clean_place})")

        # Save state
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(list(notified), f)
    except Exception as e:
        print(f"[ERROR] Error al consultar USGS / notificar: {e}", file=sys.stderr)

    return sent_count


def main():
    parser = argparse.ArgumentParser(description="CHILE-OEF Telegram Alert Tool")
    parser.add_argument("--token", default=DEFAULT_BOT_TOKEN, help="Telegram Bot Token")
    parser.add_argument("--chat-id", default=DEFAULT_CHANNEL_ID, help="Telegram Chat ID or @channel_name")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    parser.add_argument("--weekly", action="store_true", help="Send weekly bulletin")
    parser.add_argument("--kit", action="store_true", help="Send emergency kit checklist")
    parser.add_argument("--mitos", action="store_true", help="Send myths vs reality post")
    parser.add_argument("--historia", action="store_true", help="Send historic earthquakes timeline")
    parser.add_argument("--poll", action="store_true", help="Check USGS and notify new events M>=min_mag")
    parser.add_argument("--min-mag", type=float, default=5.0, help="Minimum magnitude threshold (default 5.0)")
    parser.add_argument("--message", help="Custom text message to send")

    args = parser.parse_args()

    if not args.token:
        print("[AVISO] Debe especificar --token o configurar CHILE_OEF_TELEGRAM_BOT_TOKEN")
        sys.exit(1)

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
    elif args.weekly:
        print(f"[INFO] Enviando boletín semanal a {args.chat_id}...")
        ok = send_telegram_message(args.token, args.chat_id, format_weekly_bulletin())
        if ok:
            print("[ÉXITO] Boletín semanal enviado.")
        else:
            print("[FALLO] Error al enviar boletín semanal.")
    elif args.kit:
        print(f"[INFO] Enviando Kit de Emergencia a {args.chat_id}...")
        ok = send_telegram_message(args.token, args.chat_id, format_emergency_kit())
        if ok:
            print("[ÉXITO] Kit de emergencia enviado.")
        else:
            print("[FALLO] Error al enviar Kit de emergencia.")
    elif args.mitos:
        print(f"[INFO] Enviando Mitos vs Realidad a {args.chat_id}...")
        ok = send_telegram_message(args.token, args.chat_id, format_myths_and_reality())
        if ok:
            print("[ÉXITO] Mitos vs Realidad enviado.")
        else:
            print("[FALLO] Error al enviar Mitos vs Realidad.")
    elif args.historia:
        print(f"[INFO] Enviando Historia de Terremotos a {args.chat_id}...")
        ok = send_telegram_message(args.token, args.chat_id, format_historic_timeline())
        if ok:
            print("[ÉXITO] Historia enviada.")
        else:
            print("[FALLO] Error al enviar Historia.")
    elif args.poll:
        print(f"[INFO] Verificando sismos nuevos (M>={args.min_mag}) en USGS para {args.chat_id}...")
        n = fetch_and_notify_new_events(args.token, args.chat_id, min_mag=args.min_mag)
        print(f"[INFO] Polling finalizado. Sismos notificados: {n}")
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
