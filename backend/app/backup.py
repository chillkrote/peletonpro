"""Backup und Restore der Postgres-Datenbank (Dump, Restore, Verify).

Hintergrund: Die Produktionsdatenbank läuft auf Renders kostenlosem Plan und
läuft dort 30 Tage nach Anlage ersatzlos ab (`expiresAt`), ohne Backups. Der
komplette Bestand - Teams, Fahrer mit Team-Historie, mehrere tausend Rennen mit
Ergebnissen und Etappen - wäre damit weg, und ein Wiederaufbau per Scraper
dauert (respektvoll ratenlimitiert) Tage. Dieses Modul ist die Absicherung
dagegen; die eigentliche Lösung ist ein bezahlter Plan (siehe README,
Abschnitt "Backup").

ZWEI VERFAHREN, automatisch gewählt:

1. "pgdump" - `pg_dump -Fc` (Custom Format, komprimiert, Restore per
   `pg_restore`). Schnell und vollständig (Schema + Daten + Sequenzen), aber
   setzt die postgresql-client-Binaries voraus UND eine pg_dump-Version, die
   nicht älter ist als der Server (pg_dump verweigert neuere Server).
2. "csv" - reines psycopg: pro Tabelle ein `COPY ... TO STDOUT (FORMAT csv)`
   in eine gzip-komprimierte Datei. Braucht nichts außer psycopg (steht
   ohnehin in requirements.txt) und läuft damit auch dort, wo keine
   Client-Binaries installiert sind - auf Renders Python-Image ist pg_dump
   NICHT enthalten, dieser Weg ist dort also der reale.

Das CSV-Verfahren sichert nur DATEN, nicht das Schema. Das ist Absicht: das
Schema entsteht beim Start aus app/db.py und app/db_races.py (init_schema),
ist also im Repository versioniert und braucht kein Backup. Ein Restore läuft
deshalb gegen eine Datenbank, in der das Schema bereits angelegt ist.

Tabellen-Reihenfolge wird NICHT hart codiert, sondern bei jedem Lauf aus den
Fremdschlüssel-Beziehungen topologisch sortiert (siehe _table_order). Neue
Tabellen - etwa für Frauen-Radsport oder weitere Kategorien - werden damit
automatisch mitgesichert und in korrekter Reihenfolge zurückgeschrieben, ohne
dass hier etwas angepasst werden muss.

Aufrufe:
    python -m app.backup dump                  # nach BACKUP_DIR
    python -m app.backup dump --keep 7         # alte Läufe aufräumen
    python -m app.backup verify <pfad>         # Manifest gegen die DB prüfen
    python -m app.backup restore <pfad> --force

Für einen Render Cron Job siehe backend/README.md, Abschnitt "Backup".
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
DUMP_NAME = "dump.pgcustom"
SCHEMA = "public"


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit(
            "DATABASE_URL ist nicht gesetzt - ohne Datenbank kein Backup.\n"
            "Lokal: DATABASE_URL=postgresql://user@host:port/db python -m app.backup dump"
        )
    return url


def backup_dir() -> Path:
    """Zielverzeichnis für Dumps. Bewusst per Env-Var konfigurierbar und ohne
    Cloud-Zugangsdaten im Code - wohin die Dateien danach wandern (S3, B2,
    rsync), entscheidet der aufrufende Cron Job, nicht dieses Modul."""
    default = Path(__file__).resolve().parent.parent / "backups"
    return Path(os.environ.get("BACKUP_DIR", str(default)))


# ---------------------------------------------------------------------------
# Schema-Introspektion
# ---------------------------------------------------------------------------


def _tables(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        (SCHEMA,),
    ).fetchall()
    return [r["table_name"] for r in rows]


def _fk_edges(conn: psycopg.Connection) -> list[tuple[str, str]]:
    """(kind, eltern) - eine Kante pro Fremdschlüssel. Selbstreferenzen werden
    weggelassen, sie sagen nichts über die Reihenfolge ZWISCHEN Tabellen."""
    rows = conn.execute(
        """
        SELECT src.relname AS child, tgt.relname AS parent
        FROM pg_constraint c
        JOIN pg_class src ON src.oid = c.conrelid
        JOIN pg_class tgt ON tgt.oid = c.confrelid
        JOIN pg_namespace n ON n.oid = src.relnamespace
        WHERE c.contype = 'f' AND n.nspname = %s
        """,
        (SCHEMA,),
    ).fetchall()
    return [(r["child"], r["parent"]) for r in rows if r["child"] != r["parent"]]


def _table_order(conn: psycopg.Connection) -> list[str]:
    """Tabellen so sortiert, dass jede Tabelle nach allen Tabellen kommt, auf
    die sie per Fremdschlüssel verweist - die Einfüge-Reihenfolge für einen
    Restore. Kahn-Algorithmus; bei einem Zyklus (gibt es im aktuellen Schema
    nicht, könnte aber entstehen) wird der Rest alphabetisch angehängt statt
    abzubrechen, damit ein Dump auf jeden Fall zustande kommt."""
    tables = _tables(conn)
    parents: dict[str, set[str]] = {t: set() for t in tables}
    for child, parent in _fk_edges(conn):
        if child in parents and parent in parents:
            parents[child].add(parent)

    ordered: list[str] = []
    remaining = dict(parents)
    while remaining:
        ready = sorted(t for t, deps in remaining.items() if not (deps - set(ordered)))
        if not ready:
            leftover = sorted(remaining)
            logger.warning(
                "Fremdschlüssel-Zyklus zwischen %s - Reihenfolge alphabetisch angehängt",
                ", ".join(leftover),
            )
            ordered.extend(leftover)
            break
        ordered.extend(ready)
        for t in ready:
            remaining.pop(t)
    return ordered


def _row_counts(conn: psycopg.Connection, tables: list[str]) -> dict[str, int]:
    """Exakte Zeilenzahlen (count(*), nicht die Schätzung aus pg_class) - sie
    sind das Prüfmerkmal, an dem ein Restore gemessen wird."""
    counts: dict[str, int] = {}
    for table in tables:
        row = conn.execute(f'SELECT count(*) AS n FROM "{table}"').fetchone()
        counts[table] = row["n"]
    return counts


def _sequences(conn: psycopg.Connection) -> dict[str, Optional[int]]:
    rows = conn.execute(
        "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = %s",
        (SCHEMA,),
    ).fetchall()
    return {r["sequencename"]: r["last_value"] for r in rows}


def _serial_columns(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    """(tabelle, spalte, sequenz) für jede Spalte, die an einer Sequenz hängt.
    Nach einem CSV-Restore mit expliziten IDs steht die Sequenz sonst noch auf
    1 und das nächste INSERT kollidiert - der klassische Fehler bei
    CSV-Backups."""
    rows = conn.execute(
        """
        SELECT c.relname AS table_name, a.attname AS column_name,
               s.relname AS sequence_name
        FROM pg_depend d
        JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
        JOIN pg_class c ON c.oid = d.refobjid
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.refobjsubid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE d.deptype IN ('a', 'i') AND n.nspname = %s
        """,
        (SCHEMA,),
    ).fetchall()
    return [(r["table_name"], r["column_name"], r["sequence_name"]) for r in rows]


def _server_version(conn: psycopg.Connection) -> int:
    return conn.info.server_version


# ---------------------------------------------------------------------------
# Verfahrenswahl
# ---------------------------------------------------------------------------


def _pg_dump_major() -> Optional[int]:
    """Major-Version von pg_dump, oder None wenn nicht vorhanden/unlesbar."""
    exe = shutil.which("pg_dump")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=15, check=True
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("pg_dump --version fehlgeschlagen: %s", exc)
        return None
    for token in out.split():
        head = token.split(".")[0]
        if head.isdigit():
            return int(head)
    return None


def choose_method(server_version: int) -> str:
    """'pgdump' wenn die Binaries da und nicht älter als der Server sind, sonst
    'csv'. pg_dump bricht gegen einen neueren Server ab ("server version
    mismatch"), deshalb der Vergleich - eine vorhandene, aber zu alte
    Installation ist schlimmer als keine, weil sie stillschweigend scheitern
    würde."""
    server_major = server_version // 10000
    dump_major = _pg_dump_major()
    if dump_major is None:
        logger.info("pg_dump nicht gefunden - CSV-Verfahren (reines psycopg)")
        return "csv"
    if dump_major < server_major:
        logger.warning(
            "pg_dump %d ist älter als der Server (%d) und würde abbrechen - CSV-Verfahren",
            dump_major,
            server_major,
        )
        return "csv"
    logger.info("pg_dump %d gefunden, Server %d - pg_dump-Verfahren", dump_major, server_major)
    return "pgdump"


# ---------------------------------------------------------------------------
# Dump
# ---------------------------------------------------------------------------


def dump(target_parent: Optional[Path] = None, method: Optional[str] = None,
         keep: Optional[int] = None) -> Path:
    url = database_url()
    parent = target_parent or backup_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = parent / f"peletonpro-{stamp}"
    target.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(url, row_factory=dict_row) as conn:
        server_version = _server_version(conn)
        order = _table_order(conn)
        counts = _row_counts(conn, order)
        seqs = _sequences(conn)

    chosen = method or choose_method(server_version)
    if chosen == "pgdump":
        _dump_pgdump(url, target)
    else:
        _dump_csv(url, target, order)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": chosen,
        # Bewusst OHNE DATABASE_URL/Host/Benutzer - ein Manifest soll keine
        # Verbindungsdaten mitschleppen.
        "server_version": server_version,
        "table_order": order,
        "row_counts": counts,
        "sequences": seqs,
        "total_rows": sum(counts.values()),
    }
    (target / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    logger.info(
        "Dump fertig: %s (%s, %d Tabellen, %d Zeilen, %.1f KiB)",
        target,
        chosen,
        len(order),
        manifest["total_rows"],
        size / 1024,
    )
    if keep:
        _prune(parent, keep)
    return target


def _dump_pgdump(url: str, target: Path) -> None:
    out = target / DUMP_NAME
    cmd = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
           "--file", str(out), url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump fehlgeschlagen (exit {result.returncode}): {result.stderr.strip()}")
    if result.stderr.strip():
        logger.info("pg_dump: %s", result.stderr.strip())


def _dump_csv(url: str, target: Path, order: list[str]) -> None:
    with psycopg.connect(url, row_factory=dict_row) as conn:
        for table in order:
            path = target / f"{table}.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
                with conn.cursor().copy(
                    f'COPY "{table}" TO STDOUT (FORMAT csv, HEADER true)'
                ) as copy:
                    for chunk in copy:
                        fh.write(bytes(chunk).decode("utf-8"))
            logger.debug("  %s -> %s", table, path.name)


def _prune(parent: Path, keep: int) -> None:
    runs = sorted((p for p in parent.glob("peletonpro-*") if p.is_dir()), reverse=True)
    for old in runs[keep:]:
        shutil.rmtree(old)
        logger.info("Alten Dump entfernt: %s", old.name)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict:
    manifest_path = path / MANIFEST_NAME if path.is_dir() else path
    if not manifest_path.exists():
        raise SystemExit(f"Kein {MANIFEST_NAME} unter {path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def verify(path: Path) -> bool:
    """Vergleicht die Zeilenzahlen im Manifest mit der aktuellen Datenbank.
    Gedacht als Selbstprüfung direkt nach einem Dump oder Restore."""
    manifest = load_manifest(path)
    expected: dict[str, int] = manifest["row_counts"]
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        actual = _row_counts(conn, _tables(conn))

    ok = True
    for table in sorted(set(expected) | set(actual)):
        exp, act = expected.get(table), actual.get(table)
        if exp == act:
            logger.info("  %-24s %6s  ok", table, act)
        else:
            ok = False
            logger.error("  %-24s erwartet %s, gefunden %s", table, exp, act)
    logger.info("Verify: %s", "alle Zeilenzahlen stimmen" if ok else "ABWEICHUNGEN gefunden")
    return ok


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore(path: Path, force: bool = False) -> None:
    if not force:
        raise SystemExit(
            "Restore überschreibt ALLE Daten der Zieldatenbank.\n"
            "Wenn das gewollt ist, mit --force erneut aufrufen."
        )
    manifest = load_manifest(path)
    url = database_url()
    method = manifest["method"]
    logger.info("Restore aus %s (Verfahren: %s, %d Zeilen)", path, method, manifest["total_rows"])

    if method == "pgdump":
        _restore_pgdump(url, path)
    else:
        _restore_csv(url, path, manifest["table_order"])

    if not verify(path):
        raise SystemExit("Restore abgeschlossen, aber die Zeilenzahlen stimmen nicht - bitte prüfen.")


def _restore_pgdump(url: str, path: Path) -> None:
    dump_file = path / DUMP_NAME
    if not dump_file.exists():
        raise SystemExit(f"{DUMP_NAME} fehlt in {path}")
    cmd = ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges",
           "--dbname", url, str(dump_file)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # pg_restore meldet bei --clean auf einer leeren DB harmlose "does not
    # exist"-Hinweise als Warnung und liefert dann exit 1. Das ist kein
    # Fehlschlag, deshalb wird stderr geloggt statt blind abgebrochen.
    if result.stderr.strip():
        logger.info("pg_restore: %s", result.stderr.strip())
    if result.returncode != 0:
        logger.warning("pg_restore exit %d - Zeilenzahlen werden unten geprüft", result.returncode)


def _restore_csv(url: str, path: Path, order: list[str]) -> None:
    missing = [t for t in order if not (path / f"{t}.csv.gz").exists()]
    if missing:
        raise SystemExit(f"CSV-Dateien fehlen für: {', '.join(missing)}")

    with psycopg.connect(url, row_factory=dict_row) as conn:
        existing = set(_tables(conn))
        unknown = [t for t in order if t not in existing]
        if unknown:
            raise SystemExit(
                "Diese Tabellen fehlen in der Zieldatenbank: "
                + ", ".join(unknown)
                + "\nDas CSV-Verfahren sichert nur Daten, kein Schema - erst das Schema "
                "anlegen lassen (App starten oder init_schema aufrufen), dann restaurieren."
            )

        # Ein TRUNCATE über alle Tabellen zugleich, CASCADE löst die
        # Fremdschlüssel-Reihenfolge selbst; RESTART IDENTITY setzt die
        # Sequenzen zurück, bevor die IDs explizit wieder eingefügt werden.
        quoted = ", ".join(f'"{t}"' for t in order)
        conn.execute(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")

        for table in order:
            with gzip.open(path / f"{table}.csv.gz", "rt", encoding="utf-8", newline="") as fh:
                with conn.cursor().copy(
                    f'COPY "{table}" FROM STDIN (FORMAT csv, HEADER true)'
                ) as copy:
                    while chunk := fh.read(1 << 16):
                        copy.write(chunk)
            logger.debug("  %s eingelesen", table)

        _reset_sequences(conn)
        conn.commit()


def _reset_sequences(conn: psycopg.Connection) -> None:
    """Sequenzen auf den höchsten vorhandenen Wert setzen. Bewusst aus den
    DATEN abgeleitet und nicht aus dem Manifest übernommen - so stimmt es auch
    dann, wenn ein Dump von Hand beschnitten wurde."""
    for table, column, sequence in _serial_columns(conn):
        conn.execute(
            f"""
            SELECT setval(
                %s,
                COALESCE((SELECT MAX("{column}") FROM "{table}"), 1),
                (SELECT MAX("{column}") IS NOT NULL FROM "{table}")
            )
            """,
            (f'{SCHEMA}.{sequence}',),
        )
        logger.debug("  Sequenz %s auf max(%s.%s) gesetzt", sequence, table, column)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.backup",
        description="Backup und Restore der PelotonPro-Datenbank.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_dump = sub.add_parser("dump", help="Datenbank nach BACKUP_DIR sichern")
    p_dump.add_argument("--dir", type=Path, default=None, help="Zielverzeichnis (überschreibt BACKUP_DIR)")
    p_dump.add_argument("--method", choices=["pgdump", "csv"], default=None,
                        help="Verfahren erzwingen statt automatisch wählen")
    p_dump.add_argument("--keep", type=int, default=int(os.environ.get("BACKUP_KEEP", "0")) or None,
                        help="nur die letzten N Läufe behalten (0/weglassen = alle)")

    p_verify = sub.add_parser("verify", help="Manifest gegen die aktuelle Datenbank prüfen")
    p_verify.add_argument("path", type=Path)

    p_restore = sub.add_parser("restore", help="Dump zurückschreiben (überschreibt alles)")
    p_restore.add_argument("path", type=Path)
    p_restore.add_argument("--force", action="store_true", help="Überschreiben bestätigen")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.command == "dump":
        dump(target_parent=args.dir, method=args.method, keep=args.keep)
        return 0
    if args.command == "verify":
        return 0 if verify(args.path) else 1
    if args.command == "restore":
        restore(args.path, force=args.force)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
