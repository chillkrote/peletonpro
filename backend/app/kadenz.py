"""Wie oft eine Quelle wirklich neu abgerufen werden muss.

DAS PROBLEM WAR NICHT DAS INTERVALL
-----------------------------------
`REFRESH_INTERVAL_ROSTERS` stand auf 24 Stunden. Gemessen am 14.09.2026
liefen die Kader trotzdem **14 Mal** an einem Tag, jedes Mal mit dem
Ergebnis `0 von 517 Fahrern geändert`:

    06:49  07:43  08:01  09:12  09:44  11:06  11:50
    12:14  12:27  13:04  14:25  15:34  15:59  16:35

Jede Zeile kam von einer anderen Instanz-ID, also von einem frischen
Prozessstart. Die Ursache ist `next_run_time=datetime.now() + stagger` in
`scheduler.start_scheduler()`: APScheduler führt jeden Job beim Start
einmal aus. Eine Instanz auf Renders kostenlosem Plan schläft nach 15
Minuten ohne Anfrage ein und startet beim nächsten Besuch neu - also
mehrmals pro Stunde.

Ein Intervall, das an die Prozesslaufzeit gebunden ist, greift damit nie.
Der Takt war faktisch "bei jedem Aufwachen": rund 500 Wikipedia-Anfragen
an einem Tag, um nichts zu erfahren.

DIE LÖSUNG: FÄLLIGKEIT AUS DER DATENBANK, NICHT AUS DER LAUFZEIT
----------------------------------------------------------------
Der Job fragt vor der Arbeit, wann er das letzte Mal ERFOLGREICH gelaufen
ist (Tabelle `job_runs`, Migration 0007), und vergleicht das mit dem Takt
für den heutigen Tag. Das ist robuster als ein Kalenderplan: ein
verpasstes Zeitfenster geht nicht verloren, sondern wird beim nächsten
Aufwachen nachgeholt - genau das Verhalten, das ein Dienst braucht, der
schläft.

DER TAKT FOLGT DER QUELLE, NICHT DER UHR
----------------------------------------
Kader ändern sich nicht gleichmäßig über das Jahr, sondern in Sprüngen:

    Januar      die neuen Kader treten in Kraft. Wikipedia wird darüber
                Tage und Wochen nachgetragen, nicht an einem Tag - deshalb
                der engste Takt.
    Februar     die Nachzügler: Fahrer, die erst im Januar oder Februar
                einen Vertrag finden.
    Aug + Sep   Stagiaires. Ab 1. August dürfen Teams Nachwuchsfahrer
                aufnehmen, und die erscheinen dann in den Kaderlisten.
                Der zweite systematische Sprung im Jahr.
    sonst       Wechsel mitten in der Saison gibt es (Vertragsauflösung,
                Rücktritt), aber unvorhersehbar und selten. Dafür reicht
                der Grundtakt.

März ist bewusst NICHT dabei: dort passiert nichts Systematisches.
"""
from datetime import date, datetime, timedelta
from typing import Optional

# Monat (1-12) -> Tage zwischen zwei Abrufen. Nicht genannte Monate
# bekommen GRUNDTAKT_TAGE.
_TEAMS = {1: 7}
_KADER = {1: 3, 2: 7, 8: 7, 9: 7}

GRUNDTAKT_TAGE = 30

# Job-ID (wie in scheduler.JOBS) -> Monatsplan. Nur Jobs, die eine Quelle
# VOLLSTÄNDIG neu lesen, stehen hier. Die Rückstands-Jobs
# (refresh_rider_details, refresh_race_history) gehören ausdrücklich nicht
# dazu: sie holen je Eintrag einmal und sollen so oft laufen wie möglich,
# damit der Rückstand abfließt. refresh_news auch nicht - News sind die
# einzige Quelle, die Frequenz rechtfertigt.
PLAN: dict[str, dict[int, int]] = {
    "refresh_teams": _TEAMS,
    "refresh_rosters": _KADER,
}


def takt_tage(job: str, heute: Optional[date] = None) -> int:
    """Tage zwischen zwei Abrufen, für den Monat von `heute`.

    Maßgeblich ist der HEUTIGE Monat, nicht der des letzten Laufs: am
    1. Januar gilt sofort der Januar-Takt, auch wenn zuletzt im Dezember
    abgerufen wurde. Damit öffnet sich das enge Fenster genau dann, wenn
    die Daten sich ändern."""
    if job not in PLAN:
        raise KeyError(
            f"Kein Takt für Job {job!r} hinterlegt (bekannt: {', '.join(sorted(PLAN))})"
        )
    heute = heute or date.today()
    return PLAN[job].get(heute.month, GRUNDTAKT_TAGE)


def ist_faellig(
    job: str, letzter_lauf: Optional[datetime], jetzt: Optional[datetime] = None
) -> bool:
    """Ob der Job jetzt arbeiten soll.

    Ohne vermerkten Lauf: ja. Das gilt auch beim ersten Start nach dem
    Einbau dieser Prüfung - einmal abrufen, danach ist Ruhe."""
    if letzter_lauf is None:
        return True
    jetzt = jetzt or datetime.now(tz=letzter_lauf.tzinfo)
    return (jetzt - letzter_lauf) >= timedelta(days=takt_tage(job, jetzt.date()))


def naechster_lauf_in(
    job: str, letzter_lauf: Optional[datetime], jetzt: Optional[datetime] = None
) -> timedelta:
    """Wie lange es noch dauert - nur für die Log-Meldung beim Überspringen.
    Eine Nachricht "nicht fällig" ohne "bis wann" wäre eine Sackgasse für
    jeden, der wissen will, ob der Job noch lebt."""
    if letzter_lauf is None:
        return timedelta(0)
    jetzt = jetzt or datetime.now(tz=letzter_lauf.tzinfo)
    faellig_am = letzter_lauf + timedelta(days=takt_tage(job, jetzt.date()))
    return max(faellig_am - jetzt, timedelta(0))
