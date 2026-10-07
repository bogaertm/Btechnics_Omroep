"""Constanten voor Btechnics Omroep."""

DOMAIN = "btx_omroep"

CONF_PIN = "pin"
CONF_BASIS_URL = "basis_url"

DEFAULT_PIN = "1234"

SERVICE_OMROEP = "omroep"

ATTR_TUNER = "tuner"
ATTR_BERICHT = "bericht"
ATTR_VOLUME = "volume"
ATTR_HERHALINGEN = "herhalingen"
ATTR_PAUZE = "pauze"

URL_BESTAND = "/api/btx_omroep/bestand/{token}/{naam}"

SIGNAAL_STATUS = "btx_omroep_status_{}"

ATTR_TEKST = "tekst"
ATTR_MUZIEKJE = "muziekje"

CONF_TTS = "tts"

MAP_OMROEP = "omroep"  # submap van de lokale mediamap met de boodschappen
AUDIO_EXTENSIES = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
GELUID_IN = "gong_in.mp3"
GELUID_UIT = "gong_uit.mp3"
