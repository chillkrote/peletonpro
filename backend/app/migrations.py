"""Schema-Migrationen: nummerierte .sql-Dateien plus Versionstabelle.

WARUM KEIN ALEMBIC
------------------
Alembics Wert liegt in der Autogenerierung aus SQLAlchemy-Modellen. Dieses
Projekt hat kein ORM - es schreibt SQL direkt mit psycopg. Jede
Alembic-Revision wäre hier ein `op.execute("...")` mit demselben SQL darin,
nur in einer Python-Datei mit Boilerplate obendrüber. Dazu käme eine
Abhängigkeit, die SQLAlchemy mitzieht, auf einer 512-MB-Instanz.

Was hier stattdessen steht, sind rund 150 Zeilen: eine Tabelle, eine
Reihenfolge, ein Lock. Der Preis ist, dass Alembics selten gebrauchte
Fähigkeiten fehlen (Verzweigungen, Autogenerierung, `stamp`). Kommt später
ein ORM dazu, ist der Wechsel zu Alembic ein `alembic stamp` auf den dann
erreichten Stand - diese Entscheidung verbaut nichts.

KEIN RÜCKWEG, ABSICHTLICH
-------------------------
Es gibt kein `downgrade`. Ein Rückweg, der nur auf dem Papier existiert,
ist gefährlicher als keiner: die meisten Schema-Rückwärtsschritte verlieren
Daten (eine gelöschte Spalte kommt nicht zurück), und niemand probt sie.
Der ehrliche Rückweg dieses Projekts ist das Backup (app/backup.py, siehe
README) - vor einer Migration, die Daten anfasst, ein Dump; geht sie
schief, ein Restore.

WANN ES LÄUFT
-------------
Im FastAPI-lifespan beim Start, vor dem Scheduler - dort, wo vorher
db.init_schema() und db_races.init_schema() standen. Render bietet auf dem
Free-Plan keinen Shell-Zugriff und kein preDeployCommand, ein Aufruf beim
Start ist also der einzige Weg, der ohne Handarbeit funktioniert.

Damit zwei gleichzeitig startende Instanzen nicht dieselbe Migration
fahren, hält der Lauf ein Advisory Lock (pg_advisory_lock). Der Zweite
wartet, sieht danach die Versionstabelle auf dem neuen Stand und tut
nichts. Auf dem Free-Plan läuft nur eine Instanz - aber ein Upgrade des
Plans soll nicht stillschweigend zu zwei parallelen Migrationsläufen
führen.
"""
import hashlib
import logging
import pathlib

import psycopg

from psycopg.rows import dict_row

from .db import DATABASE_URL, _connect

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"

# Frei gewählte Konstante für pg_advisory_lock. Sie identifiziert nur
# "PelotonPro-Migrationslauf" und muss lediglich projektweit dieselbe sein.
LOCK_KEY = 8_147_230_591

_VERSIONSTABELLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _eigene_verbindung() -> psycopg.Connection:
    """Eine eigene Verbindung für den Migrationslauf, NICHT aus dem Pool.

    Der Lauf braucht Autocommit (Begründung in run_migrations). Setzt man das
    auf einer Verbindung aus dem Pool, bleibt es dort hängen: psycopg_pool
    stellt autocommit beim Zurückgeben nicht wieder her, und der nächste
    Nutzer derselben Verbindung steht in Autocommit. Was dann bricht, sind
    die server-side Cursor des CSV-Exports - "DECLARE CURSOR can only be
    used in transaction blocks".

    Nachgemessen, bevor das hier stand: vier von sieben CSV-Exporten lieferten
    HTTP 200 mit leerem Rumpf, weil sie die vergiftete Verbindung erwischt
    hatten. Genau die Art Fehler, die man in einem Backup erst merkt, wenn
    man es braucht.

    Eine eigene Verbindung kostet hier nichts: der Lauf passiert einmal beim
    Start, und sie wird sofort wieder geschlossen."""
    return psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row)


def _pruefsumme(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verfuegbare_migrationen() -> list[tuple[str, str, str]]:
    """Alle Migrationsdateien als (version, sql, pruefsumme), aufsteigend.

    Die Version ist der Dateiname ohne Endung; die Nummer vorne bestimmt die
    Reihenfolge. Sortiert wird über den ganzen Namen, weil die Nummern
    vierstellig und damit gleich lang sind.
    """
    dateien = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    migrationen = []
    for pfad in dateien:
        sql = pfad.read_text(encoding="utf-8")
        migrationen.append((pfad.stem, sql, _pruefsumme(sql)))
    return migrationen


def _versionstabelle_anlegen(conn) -> None:
    """Legt schema_migrations an, falls sie fehlt.

    `CREATE TABLE IF NOT EXISTS` ist in Postgres NICHT gegen gleichzeitige
    Erzeugung abgesichert: die Existenzprüfung und das Anlegen sind zwei
    Schritte, und dazwischen kann eine andere Sitzung die Tabelle erzeugen -
    dann schlägt das Anlegen mit DuplicateTable fehl, trotz IF NOT EXISTS.
    Nachgemessen mit zwei gleichzeitig gestarteten Läufen: der zweite ist
    genau daran gescheitert.

    Das Advisory Lock unten verhindert das inzwischen, weil der Aufruf in
    Autocommit läuft und damit einen frischen Katalog-Schnappschuss sieht.
    Der Fall wird hier trotzdem abgefangen: dass die Tabelle schon da ist,
    war ja das Ziel."""
    try:
        conn.execute(_VERSIONSTABELLE)
    except psycopg.errors.DuplicateTable:
        logger.debug("schema_migrations existierte bereits (paralleler Lauf).")


def _angewendete(conn) -> dict[str, str]:
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {r["version"]: r["checksum"] for r in rows}


def status() -> list[tuple[str, str]]:
    """(version, "angewendet"|"offen"|"GEÄNDERT") für jede Migration."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL nicht gesetzt")
    with _connect() as conn:
        _versionstabelle_anlegen(conn)
        angewendet = _angewendete(conn)
    ergebnis = []
    for version, _sql, pruefsumme in verfuegbare_migrationen():
        if version not in angewendet:
            ergebnis.append((version, "offen"))
        elif angewendet[version] != pruefsumme:
            ergebnis.append((version, "GEÄNDERT"))
        else:
            ergebnis.append((version, "angewendet"))
    return ergebnis


def run_migrations() -> int:
    """Wendet alle offenen Migrationen an. Gibt deren Zahl zurück.

    Ersetzt db.init_schema() und db_races.init_schema(). Ohne DATABASE_URL
    wird gewarnt und übersprungen - die App muss ohne Datenbank startbar
    bleiben (siehe app/db.py), sie liefert dann leere Listen.
    """
    if not DATABASE_URL:
        logger.warning("DATABASE_URL nicht gesetzt - Migrationen werden übersprungen.")
        return 0

    migrationen = verfuegbare_migrationen()
    if not migrationen:
        logger.error("Keine Migrationsdateien in %s gefunden.", MIGRATIONS_DIR)
        return 0

    # Eigene Verbindung in Autocommit, nicht aus dem Pool (siehe
    # _eigene_verbindung). Autocommit, weil sonst der ganze Lauf in EINER
    # Transaktion läge, und das hätte zwei schlechte Folgen: alle
    # Migrationen würden zusammen am Ende committen - bricht das ab, ist
    # auch die erste, längst erfolgreiche Migration weg - und eine lang
    # offene Transaktion sieht den Katalog nicht frisch, woran der zweite
    # von zwei gleichzeitig gestarteten Läufen gescheitert ist (siehe
    # _versionstabelle_anlegen).
    #
    # Jede einzelne Migration bekommt unten ihre eigene explizite
    # Transaktion und committet für sich.
    with _eigene_verbindung() as conn:
        # Das Lock hängt an dieser Verbindung und fällt mit ihr weg, auch
        # wenn der Prozess abstürzt - anders als ein selbstgebautes
        # "Sperre"-Feld in einer Tabelle, das dann hängen bleibt.
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            _versionstabelle_anlegen(conn)
            angewendet = _angewendete(conn)

            # Eine schon angewendete Migration nachträglich zu ändern macht
            # den Stand in Produktion und den im Repository verschieden,
            # ohne dass es auffällt. Deshalb harter Abbruch statt Warnung:
            # die Korrektur ist eine NEUE Migration.
            geaendert = [
                v for v, _sql, pruef in migrationen
                if v in angewendet and angewendet[v] != pruef
            ]
            if geaendert:
                raise RuntimeError(
                    "Bereits angewendete Migrationen wurden nachträglich geändert: "
                    f"{', '.join(geaendert)}. Änderungen gehören in eine neue "
                    "Migrationsdatei, nicht in eine alte."
                )

            offen = [(v, sql, p) for v, sql, p in migrationen if v not in angewendet]
            if not offen:
                logger.info(
                    "Schema aktuell: %d Migrationen angewendet.", len(angewendet)
                )
                return 0

            for version, sql, pruefsumme in offen:
                logger.info("Migration %s wird angewendet ...", version)
                # Eintrag in die Versionstabelle in DERSELBEN Transaktion wie
                # das SQL: bricht die Migration ab, ist auch der Eintrag weg.
                # Ein halb angewendeter Stand, der als angewendet gilt, wäre
                # das schlimmere Ergebnis.
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (version, pruefsumme),
                    )
                logger.info("Migration %s angewendet.", version)

            logger.info("%d Migration(en) angewendet.", len(offen))
            return len(offen)
        finally:
            # Das Freigeben darf den eigentlichen Fehler nicht verdecken.
            # Vorher stand hier ein nackter execute(): schlug die Migration
            # fehl, warf das Freigeben einen Folgefehler, und im Log stand
            # nur noch der - nicht die Ursache. Nachgemessen.
            # Verloren geht nichts, wenn es scheitert: das Lock hängt an der
            # Verbindung und fällt mit ihr weg.
            try:
                conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Advisory Lock konnte nicht freigegeben werden (%s) - es "
                    "fällt mit der Verbindung weg.", exc
                )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Schema-Migrationen anzeigen oder anwenden."
    )
    parser.add_argument("befehl", choices=["status", "upgrade"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.befehl == "status":
        for version, zustand in status():
            print(f"  {version:40} {zustand}")
        return 0

    anzahl = run_migrations()
    print(f"{anzahl} Migration(en) angewendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
