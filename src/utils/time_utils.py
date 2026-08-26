import logging

logger = logging.getLogger(__name__)

# Waveshare recommends refreshing the panel no more often than every 180s.
MIN_REFRESH_INTERVAL_SECONDS = 180

def calculate_seconds(interval, unit):
    seconds = 5 * 60 # default to five minutes
    if unit == "minute":
        seconds = interval * 60
    elif unit == "hour":
        seconds = interval * 60 * 60
    elif unit == "day":
        seconds = interval * 60 * 60 * 24
    else:
        logger.warning(f"Unrecognized unit: {unit}, defaulting to 5 minutes")
    return seconds

def parse_refresh_interval_seconds(interval, unit):
    """Validates and converts a plugin instance's own refresh-interval
    fields (unit/interval) into seconds, enforcing the panel's minimum
    refresh interval. Raises ValueError with a user-facing message on
    invalid input.
    """
    if not unit or unit not in ["minute", "hour", "day"]:
        raise ValueError("La unidad del intervalo de actualización es obligatoria")
    if not interval or not str(interval).isnumeric():
        raise ValueError("El intervalo de actualización es obligatorio")

    seconds = calculate_seconds(int(interval), unit)
    if seconds < MIN_REFRESH_INTERVAL_SECONDS:
        raise ValueError(f"El intervalo de actualización debe ser de al menos {MIN_REFRESH_INTERVAL_SECONDS} segundos")

    return seconds