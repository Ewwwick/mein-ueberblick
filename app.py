#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mein Überblick
==============
Zeigt deinen Apple-Kalender (iCloud) und deine Microsoft-Teams-Aufgaben
in einer Oberfläche im iOS-Stil – und trägt neue Teams-Aufgaben
automatisch in deinen Apple-Kalender ein.

Start:  starten.bat doppelklicken  (oder:  python app.py)
"""
import datetime as dt
import hashlib
import ast
import base64
import hmac
import struct
import urllib.parse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# Grundeinstellungen
# --------------------------------------------------------------------------
APP_NAME = "Mein Überblick"
APP_VERSION = "22"

# Online-Updates: Hier liegt die neueste Version (öffentliches GitHub-Repository "besitzer/name").
# Leer = keine Online-Updates.
UPDATE_REPO = "Ewwwick/mein-ueberblick"
UPDATE_BRANCH = "main"
HOST = "127.0.0.1"
PORT = 8765

BASE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE, "web")
DATA_DIR = os.path.join(BASE, "daten")
os.makedirs(DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(DATA_DIR, "einstellungen.json")
SYNC_FILE = os.path.join(DATA_DIR, "eingetragen.json")
TOKEN_FILE = os.path.join(DATA_DIR, "microsoft_anmeldung.bin")
LOG_FILE = os.path.join(DATA_DIR, "protokoll.txt")
HA_FILE = os.path.join(DATA_DIR, "hausaufgaben.json")
EXTRAS_FILE = os.path.join(DATA_DIR, "extras.json")

KEYRING_SERVICE = "MeinUeberblick-iCloud"
GRAPH = "https://graph.microsoft.com/v1.0"
MS_AUTHORITY = "https://login.microsoftonline.com/organizations"
MS_SCOPES = ["User.Read", "EduAssignments.ReadBasic", "Team.ReadBasic.All"]
ICLOUD_URL = "https://caldav.icloud.com/"
UID_PREFIX = "teams-aufgabe-"

DEFAULTS = {
    "demo": True,               # Beispieldaten, bis alles eingerichtet ist
    "ms_client_id": "",         # Anwendungs-ID aus der Microsoft-App-Registrierung
    "apple_id": "",             # E-Mail-Adresse deiner Apple-ID
    "apple_kalender": "Schule", # In diesen Kalender kommen die Aufgaben
    "auto_eintragen": True,     # Neue Aufgaben automatisch eintragen
    "termin_art": "ganztags",   # "ganztags" oder "uhrzeit"
    "erinnerung": "vortag",     # "aus", "am_tag", "vortag", "zwei_tage"
    "intervall_minuten": 15,    # Wie oft nach neuen Aufgaben geschaut wird
    "wetter_ort": "",           # Stadt für das Wetter-Widget
    "teams_aktiv": False,       # Microsoft Teams nutzen (braucht Freigabe der Schule)
    "untis_aktiv": False,       # Stundenplan aus WebUntis holen
    "untis_url": "",            # Server, z. B. nessa.webuntis.com (oder Link der Anmeldeseite)
    "untis_schule": "",         # Schulname in Untis, z. B. gym-musterstadt
    "untis_modus": "passwort",  # "passwort" oder "schluessel" (Untis-Mobile-Schlüssel)
    "untis_user": "",
}

# Mit pythonw (ohne Konsolenfenster) gibt es kein stdout -> in Datei schreiben
if sys.stdout is None or sys.stderr is None or os.environ.get("MU_LOGDATEI"):
    _log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log if (sys.stdout is None or os.environ.get("MU_LOGDATEI")) else sys.stdout
    sys.stderr = _log if (sys.stderr is None or os.environ.get("MU_LOGDATEI")) else sys.stderr


def log(*teile):
    zeile = f"[{dt.datetime.now():%d.%m. %H:%M:%S}] " + " ".join(str(t) for t in teile)
    try:
        print(zeile, flush=True)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Dateien & Einstellungen
# --------------------------------------------------------------------------
def json_laden(pfad, standard):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return standard


def json_speichern(pfad, daten):
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
    os.replace(tmp, pfad)


def cfg_laden():
    cfg = dict(DEFAULTS)
    cfg.update(json_laden(CONFIG_FILE, {}))
    return cfg


def cfg_speichern(cfg):
    json_speichern(CONFIG_FILE, cfg)


def apple_passwort_holen(cfg):
    """App-spezifisches Passwort – liegt in der Windows-Anmeldeinformationsverwaltung."""
    if not cfg.get("apple_id"):
        return ""
    try:
        import keyring
        pw = keyring.get_password(KEYRING_SERVICE, cfg["apple_id"].strip())
        if pw:
            return pw
    except Exception:
        pass
    return cfg.get("apple_passwort_lokal", "")


def apple_passwort_setzen(cfg, pw):
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, cfg["apple_id"].strip(), pw)
        cfg.pop("apple_passwort_lokal", None)
    except Exception:
        # Notlösung, falls "keyring" nicht installiert ist: nur lokal auf diesem PC
        cfg["apple_passwort_lokal"] = pw


# --------------------------------------------------------------------------
# Hausaufgaben, Stundenplan, Countdowns
# --------------------------------------------------------------------------
STANDARD_STUNDEN = [("08:00", "08:45"), ("08:50", "09:35"), ("09:55", "10:40"), ("10:45", "11:30"),
                    ("11:50", "12:35"), ("12:40", "13:25"), ("14:00", "14:45"), ("14:50", "15:35")]


def naechstes(monat, tag):
    heute = dt.date.today()
    d = dt.date(heute.year, monat, tag)
    return d if d >= heute else dt.date(heute.year + 1, monat, tag)


def extras_laden(demo=False):
    e = json_laden(EXTRAS_FILE, {})
    e.setdefault("stunden", [{"von": v, "bis": b} for v, b in STANDARD_STUNDEN])
    e.setdefault("plan", {})
    e.setdefault("countdowns", [
        {"id": "c1", "titel": "Heiligabend", "emoji": "🎄", "datum": naechstes(12, 24).isoformat()},
        {"id": "c2", "titel": "Silvester", "emoji": "🎆", "datum": naechstes(12, 31).isoformat()},
    ])
    e.setdefault("noten", [])
    e.setdefault("gewicht_schriftlich", 50)
    e.setdefault("klassenarbeiten", [])
    e.setdefault("notizen", [])
    e.setdefault("widgets", {"reihenfolge": [], "aus": []})
    if demo and not e["plan"]:
        woche = {
            "1": ["Mathe", "Mathe", "Deutsch", "Englisch", "Bio", "Sport"],
            "2": ["Englisch", "Physik", "Geschichte", "Deutsch", "Kunst", "Kunst"],
            "3": ["Deutsch", "Mathe", "Englisch", "Erdkunde", "Musik", "Informatik"],
            "4": ["Bio", "Chemie", "Mathe", "Deutsch", "Sport", "Sport"],
            "5": ["Physik", "Englisch", "Mathe", "Religion", "Deutsch"],
        }
        raeume = {"Sport": "Halle", "Physik": "N1", "Chemie": "N2", "Bio": "N3", "Informatik": "PC1",
                  "Kunst": "K1", "Musik": "M1"}
        e["plan"] = {t: {str(i): {"fach": f, "raum": raeume.get(f, "A1" + str(i + 1))}
                         for i, f in enumerate(faecher)} for t, faecher in woche.items()}
    return e


def hausaufgaben_laden():
    return json_laden(HA_FILE, [])


def ha_als_aufgaben(liste):
    aus = []
    for h in liste:
        try:
            d = dt.date.fromisoformat(h["datum"])
            hh, mm = (int(x) for x in (h.get("zeit") or "08:00").split(":")[:2])
            faellig = dt.datetime(d.year, d.month, d.day, hh, mm).astimezone()
        except Exception:
            faellig = None
        aus.append({"id": "ha-" + h["id"], "ha_id": h["id"], "quelle": "eigene",
                    "titel": h.get("titel", "Hausaufgabe"), "klasse": h.get("fach", ""),
                    "faellig_dt": faellig, "link": "", "abgegeben": bool(h.get("erledigt")),
                    "abgabe_status": "", "im_kalender": False})
    return aus


def ka_als_aufgaben(extras):
    aus = []
    for k in extras.get("klassenarbeiten", []):
        try:
            d = dt.date.fromisoformat(k["datum"])
            hh, mm = (int(x) for x in (k.get("zeit") or "08:00").split(":")[:2])
            faellig = dt.datetime(d.year, d.month, d.day, hh, mm).astimezone()
        except Exception:
            continue
        aus.append({"id": "ka-" + k["id"], "quelle": "klassenarbeit", "titel": k.get("titel") or "Klassenarbeit",
                    "klasse": k.get("fach", ""), "faellig_dt": faellig, "link": "", "abgegeben": False,
                    "abgabe_status": "", "im_kalender": False})
    return aus


# --------------------------------------------------------------------------
# WebUntis: Stundenplan mit Ausfällen und Vertretungen (nur lesen)
# --------------------------------------------------------------------------
UNTIS_KEYRING = "MeinUeberblick-Untis"
untis_wochen_cache = {}


class UntisFehler(Exception):
    pass


def untis_geheim_holen(cfg):
    user = (cfg.get("untis_user") or "").strip()
    if not user:
        return ""
    try:
        import keyring
        g = keyring.get_password(UNTIS_KEYRING, user)
        if g:
            return g
    except Exception:
        pass
    return cfg.get("untis_geheim_lokal", "")


def untis_geheim_setzen(cfg, geheim):
    try:
        import keyring
        keyring.set_password(UNTIS_KEYRING, cfg["untis_user"].strip(), geheim)
        cfg.pop("untis_geheim_lokal", None)
    except Exception:
        cfg["untis_geheim_lokal"] = geheim


def untis_adresse(cfg):
    """Server und Schulname – auch direkt aus einem eingefügten Link der Untis-Anmeldeseite."""
    roh = (cfg.get("untis_url") or "").strip()
    m = re.search(r"(?:https?://)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)", roh, re.I)
    server = m.group(1).lower() if m else ""
    s = re.search(r"school=([^&#\s]+)", roh)
    schule = urllib.parse.unquote_plus(s.group(1)) if s else (cfg.get("untis_schule") or "").strip()
    return server, schule


def untis_freundlich(err):
    code, msg = err.get("code"), str(err.get("message", ""))
    return {-8504: "Benutzername oder Passwort falsch.", -8520: "Nicht angemeldet – bitte Zugangsdaten prüfen.",
            -8509: "Keine Berechtigung – deine Schule erlaubt diesen Zugriff wohl nicht.",
            -8998: "Benutzer gesperrt (zu viele Versuche?). Später nochmal probieren.",
            -8500: "Schule nicht gefunden – Schulname prüfen."}.get(code, f"Untis meldet: {msg[:160]} ({code})")


def untis_rpc(url, methode, params, cookie=None):
    body = json.dumps({"id": "mu", "method": methode, "params": params, "jsonrpc": "2.0"}).encode("utf-8")
    kopf = {"Content-Type": "application/json", "User-Agent": "MeinUeberblick", "Accept": "application/json"}
    if cookie:
        kopf["Cookie"] = cookie
    req = urllib.request.Request(url, data=body, headers=kopf, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise UntisFehler(f"Untis-Server antwortet mit Fehler {e.code} – Server-Adresse prüfen.")
    except urllib.error.URLError:
        raise UntisFehler("Untis-Server nicht erreichbar – Server-Adresse prüfen.")
    except ValueError:
        raise UntisFehler("Unerwartete Antwort von Untis – Server-Adresse prüfen.")
    if d.get("error"):
        raise UntisFehler(untis_freundlich(d["error"]))
    return d.get("result")


def hhmm_aus_int(t):
    t = int(t)
    return f"{t // 100:02d}:{t % 100:02d}"


def untis_passwort_holen(cfg, geheim, start, tage):
    server, schule = untis_adresse(cfg)
    url = f"https://{server}/WebUntis/jsonrpc.do?school={urllib.parse.quote(schule)}"
    res = untis_rpc(url, "authenticate", {"user": cfg["untis_user"].strip(), "password": geheim, "client": "MeinUeberblick"})
    sid = res.get("sessionId")
    cookie = f'JSESSIONID={sid}; schoolname="_{base64.b64encode(schule.encode("utf-8")).decode()}"'
    ptyp, pid = res.get("personType") or 5, res.get("personId")
    if not pid:
        ptyp, pid = 1, res.get("klasseId")
    try:
        raster_roh = untis_rpc(url, "getTimegridUnits", {}, cookie) or []
        ende = start + dt.timedelta(days=tage - 1)
        tt = untis_rpc(url, "getTimetable", {"options": {
            "element": {"id": pid, "type": ptyp}, "startDate": int(start.strftime("%Y%m%d")), "endDate": int(ende.strftime("%Y%m%d")),
            "showInfo": True, "showSubstText": True, "showLsText": True, "showStudentgroup": True,
            "klasseFields": ["id", "name"], "roomFields": ["id", "name", "longname"], "subjectFields": ["id", "name", "longname"]}}, cookie) or []
    finally:
        try:
            untis_rpc(url, "logout", {}, cookie)
        except Exception:
            pass
    raster = []
    for tag in raster_roh:
        for u in tag.get("timeUnits", []):
            e = {"nr": str(u.get("name", "")), "von": hhmm_aus_int(u["startTime"]), "bis": hhmm_aus_int(u["endTime"])}
            if e not in raster:
                raster.append(e)
    stunden = []
    for p in tt:
        d = str(p.get("date", ""))
        su = (p.get("su") or [{}])[0] or {}
        raeume = p.get("ro") or []
        code = p.get("code", "")
        geaendert = code == "irregular" or bool(p.get("substText")) or any(r.get("orgid") or r.get("orgname") for r in raeume) \
            or any(x.get("orgid") or x.get("orgname") for x in (p.get("su") or []) if x)
        status = "entfall" if code == "cancelled" else "pruefung" if str(p.get("activityType", "")).lower() in ("exam", "prüfung") \
            else "vertretung" if geaendert else "normal"
        stunden.append({"datum": f"{d[:4]}-{d[4:6]}-{d[6:8]}", "von": hhmm_aus_int(p.get("startTime", 0)), "bis": hhmm_aus_int(p.get("endTime", 0)),
                        "fach": su.get("name") or p.get("lstext") or "?", "fach_lang": su.get("longname", ""),
                        "raum": ", ".join(r.get("name", "") for r in raeume if r), "klasse": ", ".join(k.get("name", "") for k in (p.get("kl") or []) if k),
                        "status": status, "info": " · ".join(x for x in [p.get("substText"), p.get("info"), p.get("lstext") if su else ""] if x)})
    return stunden, raster


def totp(geheim):
    sauber = re.sub(r"[^A-Z2-7]", "", geheim.upper())
    schluessel = base64.b32decode(sauber + "=" * ((8 - len(sauber) % 8) % 8))
    h = hmac.new(schluessel, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = h[-1] & 15
    return (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000


def untis_intern(server, schule, methode, params):
    url = f"https://{server}/WebUntis/jsonrpc_intern.do?m={methode}&school={urllib.parse.quote(schule)}&v=i2.2"
    return untis_rpc(url, methode, [params])


def untis_schluessel_holen(cfg, geheim, start, tage):
    server, schule = untis_adresse(cfg)
    auth = lambda: {"user": cfg["untis_user"].strip(), "otp": totp(geheim), "clientTime": int(time.time() * 1000)}
    ud = untis_intern(server, schule, "getUserData2017", {"auth": auth()}) or {}
    benutzer, master = ud.get("userData") or {}, ud.get("masterData") or {}
    faecher = {f["id"]: f for f in master.get("subjects", [])}
    raeume = {r["id"]: r for r in master.get("rooms", [])}
    klassen = {k["id"]: k for k in master.get("klassen", [])}
    raster = []
    for tag in (master.get("timeGrid") or {}).get("days", []):
        for u in tag.get("units", []):
            e = {"nr": str(u.get("label", "")), "von": str(u.get("startTime", "")).lstrip("T")[:5], "bis": str(u.get("endTime", "")).lstrip("T")[:5]}
            if e not in raster:
                raster.append(e)
    ende = start + dt.timedelta(days=tage - 1)
    tt = untis_intern(server, schule, "getTimetable2017", {
        "id": benutzer.get("elemId"), "type": benutzer.get("elemType") or "STUDENT", "startDate": start.isoformat(), "endDate": ende.isoformat(),
        "masterDataTimestamp": 0, "timetableTimestamp": 0, "timetableTimestamps": [], "auth": auth()}) or {}
    stunden = []
    for p in (tt.get("timetable") or {}).get("periods", []):
        els = p.get("elements") or []
        su = next((faecher.get(e.get("id"), {}) for e in els if e.get("type") == "SUBJECT"), {})
        ro = [raeume.get(e.get("id"), {}).get("name", "") for e in els if e.get("type") == "ROOM"]
        kl = [klassen.get(e.get("id"), {}).get("name", "") for e in els if e.get("type") == "CLASS"]
        ist = [str(x).upper() for x in (p.get("is") or [])]
        geaendert = "IRREGULAR" in ist or any(e.get("orgId") for e in els) or any(str(e.get("state", "")).upper() in ("SUBSTITUTED", "ABSENT") for e in els)
        status = "entfall" if "CANCELLED" in ist else "pruefung" if "EXAM" in ist else "vertretung" if geaendert else "normal"
        txt = p.get("text") or {}
        a, b = str(p.get("startDateTime", "")), str(p.get("endDateTime", ""))
        stunden.append({"datum": a[:10], "von": a[11:16], "bis": b[11:16], "fach": su.get("name", "?"), "fach_lang": su.get("longName", ""),
                        "raum": ", ".join(x for x in ro if x), "klasse": ", ".join(x for x in kl if x), "status": status,
                        "info": " · ".join(x for x in [txt.get("substitution"), txt.get("info"), txt.get("lesson")] if x)})
    return stunden, raster


def untis_holen(cfg, start, tage=7):
    server, schule = untis_adresse(cfg)
    geheim = untis_geheim_holen(cfg)
    if not server or not schule or not cfg.get("untis_user") or not geheim:
        raise UntisFehler("Noch nicht vollständig eingerichtet (Server, Schule, Benutzer, Passwort/Schlüssel).")
    if cfg.get("untis_modus") == "schluessel":
        stunden, raster = untis_schluessel_holen(cfg, geheim, start, tage)
    else:
        stunden, raster = untis_passwort_holen(cfg, geheim, start, tage)
    einzeln, gesehen = [], set()
    for x in sorted(stunden, key=lambda x: (x["datum"], x["von"], x["status"] == "normal")):
        k = (x["datum"], x["von"], x["bis"], x["fach"], x["raum"])
        if k not in gesehen:
            gesehen.add(k)
            einzeln.append(x)
    raster.sort(key=lambda x: x["von"])
    return einzeln, raster


def montag_von(d):
    return d - dt.timedelta(days=d.weekday())


# --------------------------------------------------------------------------
# Hilfsfunktionen für Zeiten
# --------------------------------------------------------------------------
def jetzt():
    return dt.datetime.now().astimezone()


def graph_zeit(text):
    """'2026-11-27T22:59:00.0000000Z' -> lokale, zeitzonen-bewusste Zeit."""
    if not text:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$", text)
    if not m:
        return None
    tz = m.group(2) or "Z"
    if tz == "Z":
        tz = "+00:00"
    return dt.datetime.fromisoformat(m.group(1) + tz).astimezone()


def lokal(wert):
    """date/datetime aus einem Kalender -> (ist_ganztags, Wert in lokaler Zeit)."""
    if isinstance(wert, dt.datetime):
        if wert.tzinfo is None:
            wert = wert.astimezone()  # "schwebende" Zeit = Ortszeit
        return False, wert.astimezone()
    return True, wert


# --------------------------------------------------------------------------
# Microsoft Teams (über Microsoft Graph)
# --------------------------------------------------------------------------
class AnmeldungNoetig(Exception):
    pass


class GraphFehler(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


def ms_freundlich(text):
    t = text or ""
    if any(k in t for k in ("AADSTS90094", "AADSTS65001", "AADSTS90095", "admin", "Administrator")):
        return ("Deine Schule muss den Zugriff erst erlauben (Administrator-Zustimmung). "
                "Frag deine Schul-IT, ob sie die App freigeben kann.")
    if "AADSTS700016" in t or "AADSTS50011" in t:
        return "Die Client-ID oder die Umleitungs-URI stimmt nicht. Prüfe Schritt 5 der Anleitung."
    if "AADSTS50194" in t:
        return ("Die App-Registrierung ist nur für ein Verzeichnis eingestellt. Wähle bei "
                "'Unterstützte Kontotypen' die mehrinstanzenfähige Option (siehe Anleitung).")
    return t[:300] or "Unbekannter Fehler bei der Microsoft-Anmeldung."


def ms_app(cfg):
    import msal
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as f:
            cache.deserialize(f.read())
    app = msal.PublicClientApplication(
        cfg["ms_client_id"].strip(), authority=MS_AUTHORITY, token_cache=cache)
    return app, cache


def ms_cache_speichern(cache):
    if cache.has_state_changed:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(cache.serialize())


def ms_token(cfg, interaktiv=False):
    """Gibt (access_token, kontoname) zurück. Interaktiv öffnet den Browser zur Anmeldung."""
    app, cache = ms_app(cfg)
    ergebnis = None
    konten = app.get_accounts()
    if konten:
        ergebnis = app.acquire_token_silent(MS_SCOPES, account=konten[0])
    if not ergebnis and interaktiv:
        ergebnis = app.acquire_token_interactive(MS_SCOPES, prompt="select_account", timeout=300)
    ms_cache_speichern(cache)
    if not ergebnis:
        raise AnmeldungNoetig("Bitte mit deinem Schulkonto anmelden.")
    if "access_token" not in ergebnis:
        raise RuntimeError(ms_freundlich(ergebnis.get("error_description") or ergebnis.get("error")))
    konto = (ergebnis.get("id_token_claims") or {}).get("preferred_username") \
        or (konten[0].get("username") if konten else "")
    return ergebnis["access_token"], konto


def graph_get(token, url):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            info = json.loads(e.read().decode("utf-8")).get("error", {})
            text = info.get("message") or str(e)
        except Exception:
            text = str(e)
        if e.code in (401, 403):
            text = ("Kein Zugriff auf die Teams-Aufgaben. Wahrscheinlich erlaubt deine Schule "
                    "das nicht – frag deine Schul-IT. (" + text[:120] + ")")
        raise GraphFehler(e.code, text)


def graph_alle(token, url):
    eintraege = []
    while url:
        d = graph_get(token, url)
        eintraege.extend(d.get("value", []))
        url = d.get("@odata.nextLink")
    return eintraege


def teams_aufgaben(cfg):
    token, konto = ms_token(cfg)

    # Klassennamen: Eine Klasse in Teams hat dieselbe ID wie ihr Team
    klassen = {}
    try:
        for t in graph_alle(token, GRAPH + "/me/joinedTeams?$select=id,displayName"):
            klassen[t.get("id")] = t.get("displayName", "")
    except Exception as e:
        log("Klassennamen nicht lesbar:", e)

    try:
        roh = graph_alle(token, GRAPH + "/education/me/assignments?$expand=submissions")
    except GraphFehler as e:
        if e.code in (400, 501):  # falls $expand nicht unterstützt wird
            roh = graph_alle(token, GRAPH + "/education/me/assignments")
        else:
            raise

    aufgaben = []
    for a in roh:
        if a.get("status") not in (None, "published", "assigned"):
            continue
        subs = a.get("submissions") or []
        abgabe_status = subs[0].get("status") if subs else None
        aufgaben.append({
            "id": str(a.get("id")),
            "titel": (a.get("displayName") or "Aufgabe").strip(),
            "klasse": klassen.get(a.get("classId"), ""),
            "faellig_dt": graph_zeit(a.get("dueDateTime")),
            "link": a.get("webUrl") or "",
            "abgegeben": abgabe_status in ("submitted", "returned"),
            "abgabe_status": abgabe_status or "",
            "im_kalender": False,
            "quelle": "teams",
        })
    return aufgaben, konto


# --------------------------------------------------------------------------
# Apple-Kalender (iCloud über CalDAV)
# --------------------------------------------------------------------------
class AppleFehler(Exception):
    pass


def apple_verbinden(cfg):
    import caldav
    pw = apple_passwort_holen(cfg)
    if not cfg.get("apple_id") or not pw:
        raise AppleFehler("Noch nicht eingerichtet.")
    client = caldav.DAVClient(url=ICLOUD_URL, username=cfg["apple_id"].strip(), password=pw)
    try:
        return client.principal()
    except Exception as e:
        name = type(e).__name__
        if "Authorization" in name or "401" in str(e):
            raise AppleFehler("Apple-ID oder App-spezifisches Passwort ist falsch.")
        raise AppleFehler("iCloud nicht erreichbar: " + str(e)[:150])


def kal_name(kal):
    try:
        n = kal.name if hasattr(kal, "name") else kal.get_display_name()
        return n or "Kalender"
    except Exception:
        return "Kalender"


def kal_farbe(kal):
    try:
        from caldav.elements import ical
        f = kal.get_property(ical.CalendarColor())
        if f and str(f).startswith("#"):
            return str(f)[:7]
    except Exception:
        pass
    return None


def apple_termine(principal, tage=35):
    start = jetzt().replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=7)
    ende = start + dt.timedelta(days=tage + 7)
    termine = []
    for kal in principal.calendars():
        name, farbe = kal_name(kal), kal_farbe(kal)
        try:
            try:
                funde = kal.search(start=start, end=ende, event=True, expand=True)
            except (TypeError, AttributeError):
                funde = kal.date_search(start=start, end=ende, expand=True)
        except Exception as e:
            log(f"Kalender '{name}' übersprungen:", e)
            continue
        for ev in funde:
            try:
                for comp in ev.icalendar_instance.walk("VEVENT"):
                    uid = str(comp.get("uid", ""))
                    if uid.startswith(UID_PREFIX):
                        continue  # unsere eigenen Aufgaben-Einträge stehen schon bei "Aufgaben"
                    if not comp.get("dtstart"):
                        continue
                    ganztags, beginn = lokal(comp.get("dtstart").dt)
                    schluss = None
                    if comp.get("dtend"):
                        _, schluss = lokal(comp.get("dtend").dt)
                    t = {"titel": str(comp.get("summary", "(ohne Titel)")),
                         "ort": str(comp.get("location", "") or ""),
                         "kalender": name, "farbe": farbe, "ganztags": ganztags}
                    if ganztags:
                        bis = schluss if (isinstance(schluss, dt.date) and not isinstance(schluss, dt.datetime)
                                          and schluss > beginn) else beginn + dt.timedelta(days=1)
                        t["tag"], t["bis_tag"] = beginn.isoformat(), bis.isoformat()
                    else:
                        if not isinstance(schluss, dt.datetime):
                            schluss = beginn + dt.timedelta(hours=1)
                        t["start"], t["ende"] = beginn.isoformat(), schluss.isoformat()
                    termine.append(t)
            except Exception as e:
                log("Termin übersprungen:", e)
    termine.sort(key=lambda t: t.get("start") or t.get("tag"))
    return termine


def ziel_kalender(principal, name):
    name = (name or "Schule").strip()
    for kal in principal.calendars():
        if kal_name(kal).strip().lower() == name.lower():
            return kal
    try:
        log(f"Lege Kalender '{name}' an …")
        return principal.make_calendar(name=name)
    except Exception:
        raise AppleFehler(f"Kalender „{name}“ nicht gefunden. Lege ihn in der Kalender-App an.")


# ---- Kalendereintrag (iCalendar-Format) bauen ----
def ics_text(s):
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r\n", "\\n").replace("\n", "\\n"))


def ics_falten(zeile):
    """Zeilen dürfen höchstens 75 Bytes lang sein."""
    teile, aktuell = [], ""
    for zeichen in zeile:
        if len((aktuell + zeichen).encode("utf-8")) > 75:
            teile.append(aktuell)
            aktuell = " " + zeichen
        else:
            aktuell += zeichen
    teile.append(aktuell)
    return "\r\n".join(teile)


ERINNERUNG_GANZTAGS = {"am_tag": "PT7H", "vortag": "-PT8H", "zwei_tage": "-P1DT8H"}  # 7 Uhr / 16 Uhr
ERINNERUNG_UHRZEIT = {"am_tag": "-PT1H", "vortag": "-PT24H", "zwei_tage": "-PT48H"}


def aufgabe_uid(a):
    return UID_PREFIX + re.sub(r"[^A-Za-z0-9-]", "", a["id"])


def baue_ics(a, cfg):
    faellig = a["faellig_dt"]
    eigene = a.get("quelle") == "eigene"
    ka = a.get("quelle") == "klassenarbeit"
    titel = ("✅ " if a["abgegeben"] else ("📝 Klassenarbeit: " if ka else "✏️ " if eigene else "📚 ")) + a["titel"]
    if a.get("klasse"):
        titel += f" ({a['klasse']})"
    beschreibung = ("Klassenarbeit" if ka else "Hausaufgabe" if eigene else "Teams-Aufgabe") + (f" – {a['klasse']}" if a.get("klasse") else "")
    beschreibung += f"\nFällig: {faellig:%d.%m.%Y um %H:%M} Uhr"
    if a["abgegeben"]:
        beschreibung += "\nStatus: " + ("erledigt" if eigene else "abgegeben") + " ✅"
    if a.get("link"):
        beschreibung += "\n\nIn Teams öffnen:\n" + a["link"]
    beschreibung += "\n\n(Automatisch eingetragen von Mein Überblick)"

    z = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Mein Ueberblick//Teams Aufgaben//DE",
         "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
         f"UID:{aufgabe_uid(a)}",
         f"DTSTAMP:{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}",
         f"SUMMARY:{ics_text(titel)}",
         f"DESCRIPTION:{ics_text(beschreibung)}"]
    if a.get("link") and "\n" not in a["link"]:
        z.append(f"URL:{a['link']}")

    if cfg.get("termin_art") == "uhrzeit":
        ende = faellig.astimezone(dt.timezone.utc)
        beginn = ende - dt.timedelta(minutes=30)
        z += [f"DTSTART:{beginn:%Y%m%dT%H%M%SZ}", f"DTEND:{ende:%Y%m%dT%H%M%SZ}"]
        ausloeser = ERINNERUNG_UHRZEIT.get(cfg.get("erinnerung"))
    else:
        tag = faellig.date()
        z += [f"DTSTART;VALUE=DATE:{tag:%Y%m%d}",
              f"DTEND;VALUE=DATE:{tag + dt.timedelta(days=1):%Y%m%d}",
              "TRANSP:TRANSPARENT"]
        ausloeser = ERINNERUNG_GANZTAGS.get(cfg.get("erinnerung"))

    if ka:  # Klassenarbeit: Erinnerung 3 Tage vorher und am Vortag (jeweils 16 Uhr bzw. relativ zur Uhrzeit)
        for t in (["-P2DT8H", "-PT8H"] if cfg.get("termin_art") != "uhrzeit" else ["-P3D", "-P1D"]):
            z += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_text('Lernen für: ' + a['titel'])}",
                  f"TRIGGER:{t}", "END:VALARM"]
    elif ausloeser and not a["abgegeben"]:
        z += ["BEGIN:VALARM", "ACTION:DISPLAY",
              f"DESCRIPTION:{ics_text('Abgabe: ' + a['titel'])}",
              f"TRIGGER:{ausloeser}", "END:VALARM"]
    z += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(ics_falten(x) for x in z) + "\r\n"


def aufgabe_fingerabdruck(a, cfg):
    teile = [a.get("quelle", ""), a["titel"], a.get("klasse", ""), a["faellig_dt"].isoformat(), a["abgegeben"],
             a.get("link", ""), cfg.get("termin_art"), cfg.get("erinnerung"),
             (cfg.get("apple_kalender") or "").lower()]
    return hashlib.sha1(json.dumps(teile, ensure_ascii=False).encode("utf-8")).hexdigest()


def aufgaben_eintragen(cfg, principal, aufgaben):
    """Trägt neue/geänderte Aufgaben ein. Gibt (neu, aktualisiert) zurück."""
    stand = json_laden(SYNC_FILE, {})
    grenze = jetzt() - dt.timedelta(days=14)  # sehr alte Aufgaben nicht mehr eintragen
    kal, neu, aktualisiert = None, [], 0
    for a in aufgaben:
        if not a["faellig_dt"] or a["faellig_dt"] < grenze:
            continue
        fp = aufgabe_fingerabdruck(a, cfg)
        alt = stand.get(a["id"])
        if alt and alt.get("fingerabdruck") == fp:
            a["im_kalender"] = True
            continue
        if kal is None:
            kal = ziel_kalender(principal, cfg.get("apple_kalender"))
        kal.save_event(baue_ics(a, cfg))  # gleiche UID = vorhandener Eintrag wird ersetzt
        stand[a["id"]] = {"fingerabdruck": fp, "titel": a["titel"], "zeit": jetzt().isoformat()}
        a["im_kalender"] = True
        if alt:
            aktualisiert += 1
        else:
            neu.append(a["titel"])
        log(("Aktualisiert: " if alt else "Neu eingetragen: ") + a["titel"])

    # Gelöschte eigene Hausaufgaben auch aus dem Kalender entfernen
    vorhanden = {a["id"] for a in aufgaben}
    for aid in [k for k in stand if k.startswith(("ha-", "ka-")) and k not in vorhanden]:
        try:
            if kal is None:
                kal = ziel_kalender(principal, cfg.get("apple_kalender"))
            kal.event_by_uid(aufgabe_uid({"id": aid})).delete()
            log("Aus Kalender entfernt:", stand[aid].get("titel"))
        except Exception as e:
            log("Konnte Termin nicht entfernen (evtl. schon weg):", e)
        stand.pop(aid, None)
    json_speichern(SYNC_FILE, stand)
    return neu, aktualisiert


# --------------------------------------------------------------------------
# Demo-Daten
# --------------------------------------------------------------------------
def demo_daten():
    h = jetzt().replace(second=0, microsecond=0)
    heute = h.replace(hour=0, minute=0)

    def um(tage, std, mnt=0):
        return heute + dt.timedelta(days=tage, hours=std, minutes=mnt)

    def termin(titel, tage, std, mnt, dauer, kal, farbe, ort=""):
        s = um(tage, std, mnt)
        return {"titel": titel, "start": s.isoformat(), "ende": (s + dt.timedelta(minutes=dauer)).isoformat(),
                "ganztags": False, "kalender": kal, "farbe": farbe, "ort": ort}

    def ganztags(titel, tage, kal, farbe):
        d = (heute + dt.timedelta(days=tage)).date()
        return {"titel": titel, "tag": d.isoformat(), "bis_tag": (d + dt.timedelta(days=1)).isoformat(),
                "ganztags": True, "kalender": kal, "farbe": farbe, "ort": ""}

    termine = [
        termin("Nachhilfe Mathe", 0, 16, 0, 60, "Privat", "#34C759", "Bibliothek"),
        termin("Abendessen mit Familie", 0, 19, 0, 60, "Familie", "#FF9500"),
        termin("Fußballtraining", 1, 17, 30, 90, "Sport", "#007AFF", "Sportplatz"),
        termin("Kino mit Freunden", 2, 19, 30, 150, "Privat", "#34C759"),
        termin("Zahnarzt", 3, 10, 0, 45, "Privat", "#34C759", "Praxis Dr. Weber"),
        ganztags("Omas Geburtstag 🎂", 5, "Familie", "#FF9500"),
        termin("Fußball – Spiel", 6, 11, 0, 120, "Sport", "#007AFF"),
        termin("Fußballtraining", 8, 17, 30, 90, "Sport", "#007AFF", "Sportplatz"),
    ]
    aufgaben = [
        ("d1", "Arbeitsblatt Lineare Funktionen", "Mathematik", um(1, 18), False),
        ("d2", "Gedichtanalyse „Der Panther“", "Deutsch", um(2, 23, 59), False),
        ("d3", "Folien für Referat Photosynthese", "Biologie", um(6, 8), False),
        ("d4", "Lesetagebuch Kapitel 5–7", "Deutsch", um(9, 23, 59), False),
        ("d5", "Vokabeltest Unit 4 – Übung", "Englisch", um(-1, 20), True),
        ("d6", "Versuchsprotokoll Pendel", "Physik", um(-2, 23, 59), True),
    ]
    liste = [{"id": i, "titel": t, "klasse": k, "faellig_dt": f, "abgegeben": ab,
              "abgabe_status": "submitted" if ab else "working",
              "link": "", "im_kalender": True} for i, t, k, f, ab in aufgaben]
    return termine, liste


# --------------------------------------------------------------------------
# Hintergrund: regelmäßig aktualisieren
# --------------------------------------------------------------------------
lock = threading.RLock()
weckruf = threading.Event()
ZUSTAND = {"bereit": False}
anmeldung = {"laeuft": False, "fehler": ""}


def aufgaben_fuer_json(liste):
    aus = []
    for a in liste:
        b = {k: v for k, v in a.items() if k != "faellig_dt"}
        b["faellig"] = a["faellig_dt"].isoformat() if a.get("faellig_dt") else None
        aus.append(b)
    aus.sort(key=lambda x: x["faellig"] or "9999")
    return aus


def aktualisieren():
    cfg = cfg_laden()
    if cfg["demo"]:
        termine, aufgaben = demo_daten()
        if not cfg.get("teams_aktiv"):
            for a in aufgaben:
                a["quelle"] = "eigene"; a["ha_id"] = ""
        aufgaben += ha_als_aufgaben(hausaufgaben_laden())
        with lock:
            ZUSTAND.update({
                "bereit": True, "demo": True, "aktualisiert": jetzt().isoformat(),
                "termine": termine, "aufgaben": aufgaben_fuer_json(aufgaben),
                "teams": {"status": "demo" if cfg.get("teams_aktiv") else "aus", "nachricht": "Beispieldaten"},
                "apple": {"status": "demo", "nachricht": "Beispieldaten"},
                "sync": {"aktiv": True, "nachricht": "Demo", "neu": [], "letzte": jetzt().isoformat()},
            })
        return

    aufgaben, termine = [], []
    alter_sync = {} if ZUSTAND.get("demo") else (ZUSTAND.get("sync") or {})
    sync = {"aktiv": cfg["auto_eintragen"], "neu": [], "letzte": alter_sync.get("letzte"),
            "nachricht": alter_sync.get("nachricht", "")}

    # Teams
    if not cfg.get("teams_aktiv"):
        teams = {"status": "aus", "nachricht": "Ausgeschaltet"}
    elif not cfg["ms_client_id"].strip():
        teams = {"status": "nicht_eingerichtet", "nachricht": "Noch nicht eingerichtet"}
    else:
        try:
            aufgaben, konto = teams_aufgaben(cfg)
            teams = {"status": "verbunden", "nachricht": konto or "Verbunden", "konto": konto}
        except AnmeldungNoetig as e:
            teams = {"status": "anmelden", "nachricht": str(e)}
        except ImportError:
            teams = {"status": "fehler", "nachricht": "Zusatzpakete fehlen – bitte installieren.bat ausführen."}
        except Exception as e:
            log("Teams-Fehler:", traceback.format_exc())
            teams = {"status": "fehler", "nachricht": str(e)[:300]}

    # Apple
    principal = None
    if not cfg["apple_id"].strip():
        apple = {"status": "nicht_eingerichtet", "nachricht": "Noch nicht eingerichtet"}
    else:
        try:
            principal = apple_verbinden(cfg)
            termine = apple_termine(principal)
            try:
                namen = sorted({kal_name(k) for k in principal.calendars()})
            except Exception:
                namen = []
            apple = {"status": "verbunden", "nachricht": cfg["apple_id"], "kalender": namen}
        except ImportError:
            apple = {"status": "fehler", "nachricht": "Zusatzpakete fehlen – bitte installieren.bat ausführen."}
        except Exception as e:
            log("Apple-Fehler:", traceback.format_exc())
            apple = {"status": "fehler", "nachricht": str(e)[:300]}

    # Untis: diese und nächste Woche
    if cfg.get("untis_aktiv"):
        try:
            start = montag_von(dt.date.today())
            stunden, raster = untis_holen(cfg, start, 14)
            untis = {"status": "verbunden", "nachricht": f"{untis_adresse(cfg)[1]} · {len(stunden)} Stunden",
                     "stunden": stunden, "raster": raster, "von": start.isoformat()}
        except ImportError:
            untis = {"status": "fehler", "nachricht": "Zusatzpakete fehlen – bitte installieren.bat ausführen."}
        except UntisFehler as e:
            untis = {"status": "fehler", "nachricht": str(e)}
        except Exception as e:
            log("Untis-Fehler:", traceback.format_exc())
            untis = {"status": "fehler", "nachricht": "Untis-Abruf fehlgeschlagen (Details im Protokoll)."}
        if untis["status"] == "fehler" and (ZUSTAND.get("untis") or {}).get("stunden"):
            alt = ZUSTAND["untis"]  # letzte bekannte Daten behalten
            untis.update({"stunden": alt["stunden"], "raster": alt.get("raster", []), "von": alt.get("von")})
    else:
        untis = {"status": "aus"}

    # Eigene Hausaufgaben dazunehmen
    aufgaben += ha_als_aufgaben(hausaufgaben_laden())

    # Automatisch eintragen (Teams-Aufgaben nur, wenn Teams verbunden ist) + Klassenarbeiten
    if principal is not None and cfg["auto_eintragen"]:
        try:
            neu, akt = aufgaben_eintragen(cfg, principal, aufgaben + ka_als_aufgaben(extras_laden()))
            sync.update({"neu": neu, "letzte": jetzt().isoformat(),
                         "nachricht": (f"{len(neu)} neu eingetragen" if neu else "Alles eingetragen")
                         + (f", {akt} aktualisiert" if akt else "")})
        except Exception as e:
            log("Eintragen-Fehler:", traceback.format_exc())
            sync["nachricht"] = "Fehler beim Eintragen: " + str(e)[:200]
    else:
        stand = json_laden(SYNC_FILE, {})
        for a in aufgaben:
            a["im_kalender"] = a["id"] in stand
        if not cfg["auto_eintragen"]:
            sync["nachricht"] = "Ausgeschaltet"

    with lock:
        ZUSTAND.update({
            "bereit": True, "demo": False, "aktualisiert": jetzt().isoformat(),
            "termine": termine, "aufgaben": aufgaben_fuer_json(aufgaben),
            "teams": teams, "apple": apple, "sync": sync, "untis": untis,
        })


def aufgaben_neu_zusammenstellen():
    """Nach dem Bearbeiten von Hausaufgaben sofort die Liste aktualisieren (ohne Internet)."""
    stand = json_laden(SYNC_FILE, {})
    ha = ha_als_aufgaben(hausaufgaben_laden())
    for a in ha:
        a["im_kalender"] = a["id"] in stand and not ZUSTAND.get("demo")
    with lock:
        fremde = [a for a in ZUSTAND.get("aufgaben", []) if a.get("quelle") != "eigene"]
        ZUSTAND["aufgaben"] = sorted(fremde + aufgaben_fuer_json(ha), key=lambda x: x.get("faellig") or "9999")


def hintergrund():
    while True:
        try:
            aktualisieren()
        except Exception:
            log("Fehler beim Aktualisieren:", traceback.format_exc())
        minuten = max(5, int(cfg_laden().get("intervall_minuten") or 15))
        weckruf.wait(minuten * 60)
        weckruf.clear()


def teams_anmelden_im_hintergrund():
    def lauf():
        anmeldung.update({"laeuft": True, "fehler": ""})
        try:
            ms_token(cfg_laden(), interaktiv=True)
        except ImportError:
            anmeldung["fehler"] = "Zusatzpakete fehlen – bitte installieren.bat ausführen."
        except Exception as e:
            anmeldung["fehler"] = str(e)[:300]
        anmeldung["laeuft"] = False
        weckruf.set()
    if not anmeldung["laeuft"]:
        threading.Thread(target=lauf, daemon=True).start()


# --------------------------------------------------------------------------
# Kleiner Webserver (nur auf diesem PC erreichbar)
# --------------------------------------------------------------------------
ERLAUBTE_FELDER = {"demo", "ms_client_id", "apple_id", "apple_kalender", "auto_eintragen",
                   "termin_art", "erinnerung", "intervall_minuten", "wetter_ort", "teams_aktiv",
                   "untis_aktiv", "untis_url", "untis_schule", "untis_modus", "untis_user"}


def text(v, n=120):
    return str(v or "").strip()[:n]


def zeit_ok(v):
    return bool(re.match(r"^\d{1,2}:\d{2}$", str(v or "")))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _antwort(self, code, daten, typ="application/json; charset=utf-8"):
        roh = daten if isinstance(daten, bytes) else json.dumps(daten, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(roh)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(roh)

    def _lokal(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        herkunft = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost"):
            return False
        if herkunft and herkunft not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return False
        return True

    def do_GET(self):
        if not self._lokal():
            return self._antwort(403, {"fehler": "nicht erlaubt"})
        pfad = self.path.split("?")[0]
        if pfad in ("/", "/index.html"):
            with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                return self._antwort(200, f.read(), "text/html; charset=utf-8")
        statisch = {"/icon.svg": "image/svg+xml", "/icon-192.png": "image/png", "/icon-512.png": "image/png",
                    "/sw.js": "text/javascript; charset=utf-8"}
        if pfad in statisch:
            with open(os.path.join(WEB_DIR, pfad.lstrip("/")), "rb") as f:
                return self._antwort(200, f.read(), statisch[pfad])
        if pfad == "/manifest.json":
            m = {"id": "/", "name": APP_NAME, "short_name": APP_NAME, "start_url": "/", "scope": "/",
                 "display": "standalone", "display_override": ["window-controls-overlay", "standalone"],
                 "background_color": "#0B1020", "theme_color": "#0B1020", "lang": "de",
                 "description": "Kalender, Hausaufgaben, Stundenplan und mehr im iOS-Stil",
                 "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                           {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}]}
            return self._antwort(200, json.dumps(m, ensure_ascii=False).encode("utf-8"), "application/manifest+json")
        if pfad == "/api/version":
            return self._antwort(200, {"version": APP_VERSION, "datei": version_auf_platte(), "online_aktiv": bool(UPDATE_REPO),
                                       "online": update_info.get("online"), "update": update_verfuegbar(),
                                       "notiz": update_info.get("notiz", ""), "geprueft": update_info.get("geprueft"),
                                       "fehler": update_info.get("fehler", "")})
        if pfad == "/api/daten":
            with lock:
                d = dict(ZUSTAND)
            d["anmeldung"] = dict(anmeldung)
            d["extras"] = extras_laden(demo=bool(d.get("demo")))
            d["eingetragen"] = list(json_laden(SYNC_FILE, {}).keys())
            d["wetter_ort"] = cfg_laden().get("wetter_ort", "")
            return self._antwort(200, d)
        if pfad == "/api/untis":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                start = montag_von(dt.date.fromisoformat(q.get("start", [""])[0]))
            except Exception:
                return self._antwort(400, {"fehler": "Datum fehlt"})
            cfg = cfg_laden()
            if not cfg.get("untis_aktiv"):
                return self._antwort(400, {"fehler": "Untis ist aus"})
            c = untis_wochen_cache.get(start.isoformat())
            if c and time.time() - c[0] < 600:
                return self._antwort(200, c[1])
            try:
                stunden, raster = untis_holen(cfg, start, 7)
                antwort = {"stunden": stunden, "raster": raster, "von": start.isoformat()}
                untis_wochen_cache[start.isoformat()] = (time.time(), antwort)
                return self._antwort(200, antwort)
            except UntisFehler as e:
                return self._antwort(502, {"fehler": str(e)})
            except Exception:
                log("Untis-Woche:", traceback.format_exc())
                return self._antwort(502, {"fehler": "Abruf fehlgeschlagen"})
        if pfad == "/api/einstellungen":
            cfg = cfg_laden()
            aus = {k: cfg[k] for k in ERLAUBTE_FELDER}
            aus["apple_passwort_gesetzt"] = bool(apple_passwort_holen(cfg))
            aus["teams_angemeldet"] = os.path.exists(TOKEN_FILE)
            aus["untis_geheim_gesetzt"] = bool(untis_geheim_holen(cfg))
            return self._antwort(200, aus)
        self._antwort(404, {"fehler": "nicht gefunden"})

    def do_POST(self):
        if not self._lokal():
            return self._antwort(403, {"fehler": "nicht erlaubt"})
        laenge = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(laenge).decode("utf-8") or "{}") if laenge else {}
        except Exception:
            body = {}
        pfad = self.path.split("?")[0]

        if pfad == "/api/einstellungen":
            cfg = cfg_laden()
            for k, v in body.items():
                if k in ERLAUBTE_FELDER:
                    cfg[k] = v
            cfg["intervall_minuten"] = max(5, int(cfg.get("intervall_minuten") or 15))
            pw = (body.get("apple_passwort") or "").strip()
            if pw and cfg.get("apple_id"):
                apple_passwort_setzen(cfg, pw)
            ug = (body.get("untis_geheim") or "").strip()
            if ug and cfg.get("untis_user"):
                untis_geheim_setzen(cfg, ug)
            untis_wochen_cache.clear()
            cfg_speichern(cfg)
            weckruf.set()
            return self._antwort(200, {"ok": True})
        if pfad == "/api/aktualisieren":
            weckruf.set()
            return self._antwort(200, {"ok": True})
        if pfad == "/api/hausaufgabe":
            liste = hausaufgaben_laden()
            aktion = body.get("aktion")
            if aktion == "neu":
                try:
                    datum = dt.date.fromisoformat(str(body.get("datum"))).isoformat()
                except Exception:
                    return self._antwort(400, {"fehler": "Bitte ein Datum angeben."})
                titel = text(body.get("titel"))
                if not titel:
                    return self._antwort(400, {"fehler": "Bitte eintragen, was zu tun ist."})
                liste.append({"id": uuid.uuid4().hex[:12], "titel": titel, "fach": text(body.get("fach"), 40),
                              "datum": datum, "zeit": body.get("zeit") if zeit_ok(body.get("zeit")) else "08:00",
                              "erledigt": False, "erstellt": jetzt().isoformat()})
            elif aktion == "umschalten":
                for h in liste:
                    if h["id"] == body.get("id"):
                        h["erledigt"] = not h.get("erledigt")
            elif aktion == "loeschen":
                liste = [h for h in liste if h["id"] != body.get("id")]
            else:
                return self._antwort(400, {"fehler": "unbekannte Aktion"})
            json_speichern(HA_FILE, liste)
            aufgaben_neu_zusammenstellen()
            weckruf.set()
            return self._antwort(200, {"ok": True})
        if pfad == "/api/stundenplan":
            e = extras_laden()
            stunden = [{"von": s["von"], "bis": s["bis"]} for s in body.get("stunden", [])
                       if isinstance(s, dict) and zeit_ok(s.get("von")) and zeit_ok(s.get("bis"))][:12]
            plan = {}
            for tag, zellen in (body.get("plan") or {}).items():
                if tag in ("1", "2", "3", "4", "5") and isinstance(zellen, dict):
                    plan[tag] = {str(i): {"fach": text(z.get("fach"), 30), "raum": text(z.get("raum"), 20)}
                                 for i, z in zellen.items() if isinstance(z, dict) and text(z.get("fach"))
                                 and str(i).isdigit() and int(i) < len(stunden)}
            e["stunden"], e["plan"] = stunden or e["stunden"], plan
            json_speichern(EXTRAS_FILE, e)
            return self._antwort(200, {"ok": True})
        if pfad == "/api/extras":
            e = extras_laden()
            k, w = body.get("key"), body.get("wert")

            def datum_ok(x):
                try:
                    return dt.date.fromisoformat(str(x)).isoformat()
                except Exception:
                    return None
            if k == "noten" and isinstance(w, list):
                e["noten"] = []
                for n in w[:500]:
                    try:
                        note = float(n.get("note"))
                    except Exception:
                        continue
                    if 0.5 <= note <= 6.0 and text(n.get("fach"), 30):
                        e["noten"].append({"id": text(n.get("id"), 20) or uuid.uuid4().hex[:10], "fach": text(n.get("fach"), 30),
                                           "note": round(note, 2), "art": "muendlich" if n.get("art") == "muendlich" else "schriftlich",
                                           "titel": text(n.get("titel"), 60), "datum": datum_ok(n.get("datum")) or dt.date.today().isoformat()})
            elif k == "gewicht_schriftlich":
                e["gewicht_schriftlich"] = max(0, min(100, int(w or 50)))
            elif k == "klassenarbeiten" and isinstance(w, list):
                e["klassenarbeiten"] = []
                for a in w[:100]:
                    d = datum_ok(a.get("datum"))
                    if not d:
                        continue
                    schritte = [{"text": text(x.get("text"), 60), "datum": datum_ok(x.get("datum")) or d, "erledigt": bool(x.get("erledigt"))}
                                for x in (a.get("schritte") or [])[:8] if isinstance(x, dict)]
                    e["klassenarbeiten"].append({"id": text(a.get("id"), 20) or uuid.uuid4().hex[:10], "fach": text(a.get("fach"), 30),
                                                 "titel": text(a.get("titel"), 80), "datum": d,
                                                 "zeit": a.get("zeit") if zeit_ok(a.get("zeit")) else "08:00", "schritte": schritte})
                weckruf.set()
            elif k == "notizen" and isinstance(w, list):
                e["notizen"] = [{"id": text(n.get("id"), 20) or uuid.uuid4().hex[:10], "text": str(n.get("text") or "")[:2000],
                                 "farbe": n.get("farbe") if n.get("farbe") in ("gelb", "pink", "blau", "gruen", "lila", "glas") else "gelb",
                                 "erstellt": text(n.get("erstellt"), 40)} for n in w[:60] if isinstance(n, dict)]
            elif k == "widgets" and isinstance(w, dict):
                e["widgets"] = {"reihenfolge": [text(x, 20) for x in (w.get("reihenfolge") or [])][:20],
                                "aus": [text(x, 20) for x in (w.get("aus") or [])][:20]}
            else:
                return self._antwort(400, {"fehler": "unbekannt"})
            json_speichern(EXTRAS_FILE, e)
            return self._antwort(200, {"ok": True})
        if pfad == "/api/countdowns":
            e = extras_laden()
            cds = []
            for c in body.get("countdowns", [])[:20]:
                try:
                    cds.append({"id": text(c.get("id"), 20) or uuid.uuid4().hex[:8], "titel": text(c.get("titel"), 40),
                                "emoji": text(c.get("emoji"), 4) or "📅",
                                "datum": dt.date.fromisoformat(str(c.get("datum"))).isoformat()})
                except Exception:
                    pass
            e["countdowns"] = cds
            json_speichern(EXTRAS_FILE, e)
            return self._antwort(200, {"ok": True})
        if pfad == "/api/teams/anmelden":
            if not cfg_laden()["ms_client_id"].strip():
                return self._antwort(400, {"fehler": "Bitte zuerst die Client-ID eintragen."})
            teams_anmelden_im_hintergrund()
            return self._antwort(200, {"ok": True})
        if pfad == "/api/teams/abmelden":
            try:
                os.remove(TOKEN_FILE)
            except FileNotFoundError:
                pass
            weckruf.set()
            return self._antwort(200, {"ok": True})
        if pfad == "/api/update/pruefen":
            update_pruefen()
            return self._antwort(200, {"online_aktiv": bool(UPDATE_REPO), "online": update_info.get("online"),
                                       "update": update_verfuegbar(), "fehler": update_info.get("fehler", "")})
        if pfad == "/api/update/installieren":
            try:
                if not update_info.get("online"):
                    update_pruefen()
                if not update_verfuegbar():
                    return self._antwort(400, {"fehler": "Kein Update verfügbar."})
                update_installieren()
            except Exception as e:
                log("Update fehlgeschlagen:", traceback.format_exc())
                return self._antwort(500, {"fehler": "Update fehlgeschlagen – es wurde nichts verändert."})
            self._antwort(200, {"ok": True})
            threading.Timer(0.4, neu_starten).start()
            return
        if pfad == "/api/kalender/test":
            cfg = cfg_laden()
            try:
                principal = apple_verbinden(cfg)
                kal = ziel_kalender(principal, cfg.get("apple_kalender"))
                beginn = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)).replace(second=0, microsecond=0)
                ics = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Mein Ueberblick//Test//DE", "BEGIN:VEVENT",
                                    f"UID:mu-test-{int(time.time())}", f"DTSTAMP:{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}",
                                    f"DTSTART:{beginn:%Y%m%dT%H%M%SZ}", f"DTEND:{beginn + dt.timedelta(minutes=15):%Y%m%dT%H%M%SZ}",
                                    ics_falten("SUMMARY:" + ics_text("✅ Test von Mein Überblick – kann gelöscht werden")),
                                    "END:VEVENT", "END:VCALENDAR"]) + "\r\n"
                kal.save_event(ics)
                log(f"Test-Termin in '{kal_name(kal)}' eingetragen.")
                return self._antwort(200, {"ok": True, "kalender": kal_name(kal)})
            except ImportError:
                return self._antwort(500, {"fehler": "Zusatzpakete fehlen – bitte 1_installieren.bat ausführen."})
            except Exception as e:
                log("Test-Termin fehlgeschlagen:", traceback.format_exc())
                return self._antwort(500, {"fehler": str(e)[:200] or "Unbekannter Fehler"})
        if pfad == "/api/neustart":
            self._antwort(200, {"ok": True})
            threading.Timer(0.4, neu_starten).start()
            return
        if pfad == "/api/beenden":
            self._antwort(200, {"ok": True})
            threading.Timer(0.5, lambda: os._exit(0)).start()
            return
        self._antwort(404, {"fehler": "nicht gefunden"})


# --------------------------------------------------------------------------
# Start
# --------------------------------------------------------------------------
SERVER = None

# ---------------------------------------------------------------- Online-Updates
ERLAUBTE_ENDUNGEN = (".py", ".html", ".js", ".png", ".svg", ".ico", ".bat", ".txt", ".json")
update_info = {"online": None, "dateien": [], "notiz": "", "geprueft": None, "fehler": ""}


def roh_url(pfad):
    return f"https://raw.githubusercontent.com/{UPDATE_REPO}/{UPDATE_BRANCH}/{pfad}"


def http_holen(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "MeinUeberblick-Updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def update_pruefen():
    if not UPDATE_REPO:
        return
    try:
        info = json.loads(http_holen(roh_url("version.json") + f"?t={int(time.time())}").decode("utf-8"))
        update_info.update({"online": str(info.get("version", "")), "dateien": list(info.get("dateien", [])),
                            "notiz": str(info.get("notiz", ""))[:300], "geprueft": jetzt().isoformat(), "fehler": ""})
    except Exception as e:
        update_info.update({"geprueft": jetzt().isoformat(), "fehler": "Update-Server nicht erreichbar"})
        log("Update-Prüfung fehlgeschlagen:", e)


def update_verfuegbar():
    try:
        return bool(update_info.get("online")) and int(update_info["online"]) > int(APP_VERSION)
    except Exception:
        return False


def pfad_ok(p):
    p = str(p).replace("\\", "/")
    teile = p.split("/")
    return bool(p) and not p.startswith("/") and ":" not in p and ".." not in teile \
        and teile[0] != "daten" and p.lower().endswith(ERLAUBTE_ENDUNGEN)


def update_installieren():
    """Lädt alle Dateien der neuen Version herunter, prüft sie und ersetzt dann die alten. Der Ordner 'daten' bleibt unberührt."""
    dateien = [p for p in update_info.get("dateien", []) if pfad_ok(p)]
    if "app.py" not in dateien:
        raise RuntimeError("Update unvollständig")
    inhalte = {p: http_holen(roh_url(p)) for p in dateien}   # erst alles laden …
    ast.parse(inhalte["app.py"].decode("utf-8"))              # … und prüfen, dass app.py in Ordnung ist
    for p, daten in inhalte.items():                           # … dann erst ersetzen
        ziel = os.path.join(BASE, *p.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel + ".neu", "wb") as f:
            f.write(daten)
        os.replace(ziel + ".neu", ziel)
    log(f"Update auf Version {update_info.get('online')} installiert ({len(inhalte)} Dateien).")


def update_schleife():
    time.sleep(8)
    while True:
        update_pruefen()
        time.sleep(6 * 3600)


def version_auf_platte():
    """Welche Version liegt gerade als Datei vor? (Unterschied = Update bereit)"""
    try:
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            m = re.search(r'^APP_VERSION = "([^"]+)"', f.read(), re.M)
        return m.group(1) if m else APP_VERSION
    except Exception:
        return APP_VERSION


NEUSTART = threading.Event()


def neu_starten():
    """Beendet den Server; main() startet danach das Programm frisch (ohne neues Fenster)."""
    log("Starte neu …")
    NEUSTART.set()
    if SERVER is not None:
        SERVER.shutdown()


def neuen_prozess_starten():
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        extra = {"creationflags": flags}
    else:
        extra = {"start_new_session": True}
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--ohne-fenster"], cwd=BASE, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=dict(os.environ, MU_LOGDATEI="1"), **extra)
    except Exception as e:
        log("Neustart fehlgeschlagen:", e)


def laufende_version():
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/version", timeout=2) as r:
            return json.loads(r.read().decode("utf-8")).get("version")
    except Exception:
        return None


def alte_version_beenden():
    """Läuft noch eine ältere Version im Hintergrund, wird sie beendet."""
    if laufende_version() == APP_VERSION:
        return False
    log("Ältere Version läuft noch – wird beendet …")
    try:
        req = urllib.request.Request(f"http://{HOST}:{PORT}/api/beenden", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    for _ in range(30):
        time.sleep(0.3)
        if not laeuft_schon():
            return True
    return False


def laeuft_schon():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def installierte_app():
    """Sucht die Verknüpfung der als App installierten Version (von Edge angelegt)."""
    if sys.platform != "win32":
        return None
    for basis in (os.environ.get("APPDATA"), os.environ.get("ProgramData")):
        if not basis:
            continue
        ordner = os.path.join(basis, "Microsoft", "Windows", "Start Menu", "Programs")
        for wurzel, _, dateien in os.walk(ordner):
            if "Startup" in wurzel or "Autostart" in wurzel:
                continue
            for d in dateien:
                if d.lower() == (APP_NAME + ".lnk").lower():
                    pfad = os.path.join(wurzel, d)
                    try:  # nur echte Edge-App-Verknüpfungen (sonst Endlosschleife mit eigener Verknüpfung)
                        with open(pfad, "rb") as f:
                            roh = f.read()
                        if b"msedge" in roh.lower() or "msedge".encode("utf-16-le") in roh.lower():
                            return pfad
                    except Exception:
                        pass
    return None


def fenster_oeffnen():
    url = f"http://{HOST}:{PORT}/"
    app = installierte_app()
    if app:
        try:
            os.startfile(app)  # installierte App: Fensterleiste passt sich dem Design an
            return
        except Exception as e:
            log("Installierte App ließ sich nicht öffnen:", e)
    if sys.platform == "win32":
        kandidaten = []
        for basis in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                      os.environ.get("LOCALAPPDATA")):
            if basis:
                kandidaten.append(os.path.join(basis, "Microsoft", "Edge", "Application", "msedge.exe"))
                kandidaten.append(os.path.join(basis, "Google", "Chrome", "Application", "chrome.exe"))
        for exe in kandidaten:
            if os.path.exists(exe):
                # App-Modus: eigenes Fenster ohne Adressleiste – wirkt wie ein echtes Programm
                subprocess.Popen([exe, f"--app={url}", "--window-size=1300,900"])
                return
    webbrowser.open(url)


def main():
    ohne_fenster = "--ohne-fenster" in sys.argv
    if "--nur-starten" in sys.argv:
        # Von NEU_STARTEN.bat: alte Version beenden, neue unsichtbar im Hintergrund starten, Fenster öffnen
        if laeuft_schon():
            alte_version_beenden()
        if not laeuft_schon():
            neuen_prozess_starten()
            for _ in range(40):
                time.sleep(0.25)
                if laeuft_schon():
                    break
        print("Läuft:", laufende_version() or "?")
        fenster_oeffnen()
        return
    if laeuft_schon():
        alte_version_beenden()
    if laeuft_schon():
        if not ohne_fenster:
            fenster_oeffnen()
        return
    global SERVER
    server = SERVER = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=hintergrund, daemon=True).start()
    threading.Thread(target=update_schleife, daemon=True).start()
    log(f"{APP_NAME} läuft auf http://{HOST}:{PORT}/  (Fenster schließen beendet es NICHT – "
        f"zum Beenden: Einstellungen → Programm beenden)")
    if not ohne_fenster:
        threading.Timer(0.8, fenster_oeffnen).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    if NEUSTART.is_set():
        server.server_close()
        neuen_prozess_starten()
        os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log("Programm konnte nicht starten:", traceback.format_exc())
        raise
