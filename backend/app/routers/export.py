"""CSV-Export der Datenbank (eine Datei pro Tabelle).

Liefert die Rohdaten roh als CSV zum Download - nützlich für eigene
Auswertungen (Excel, Pandas, ...) unabhängig von der JSON-API.

ECHTES Streaming: die Zeilen kommen über einen server-side Cursor
(db.stream_query) und werden blockweise als CSV ausgegeben. Vorher war die
`StreamingResponse` nur Kosmetik - `fetchall()` holte alle Zeilen in eine
Liste, danach baute `io.StringIO` das komplette CSV im Speicher, und
`iter([buffer.getvalue()])` gab es als einen einzigen Block aus. Bei
`race_results` (jede Platzierung über alle Rennen und Etappen) lag der
Bestand damit zweimal im Speicher der 512-MB-Instanz und wächst mit jedem
Jahrgang weiter.

Optionaler Zugriffsschutz: ist EXPORT_TOKEN gesetzt, verlangen alle
Export-Routen `Authorization: Bearer <token>`. Ohne die Variable bleiben sie
offen wie bisher, damit nichts still bricht.
"""
import csv
import io
import logging
import os
import secrets
from typing import Callable, Iterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from .. import db, db_races
from .messages import RIDERS_NOT_CONFIGURED

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["export"])

EXPORT_TOKEN = os.environ.get("EXPORT_TOKEN")

# Ab dieser Puffergröße wird ein Block ausgeliefert. Klein genug, dass der
# Speicherverbrauch flach bleibt, groß genug, um nicht pro Zeile zu senden.
CHUNK_BYTES = 64 * 1024


def _check_token(authorization: str | None) -> None:
    if not EXPORT_TOKEN:
        return
    expected = f"Bearer {EXPORT_TOKEN}"
    # secrets.compare_digest statt == : konstante Laufzeit, damit sich das
    # Token nicht zeichenweise erraten lässt.
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Nicht autorisiert")


def _serialize(value) -> object:
    # psycopg liefert date/datetime-Objekte - für CSV als ISO-String ausgeben
    return value.isoformat() if hasattr(value, "isoformat") else value


def _csv_stream(open_export: Callable[[], object]) -> Iterator[str]:
    """Erzeugt das CSV blockweise. Der Cursor bleibt offen, solange dieser
    Generator läuft - deshalb liegt der with-Block INNERHALB des Generators
    und nicht außen herum."""
    buffer = io.StringIO()
    with open_export() as (fields, rows):
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _serialize(value) for key, value in row.items()})
            if buffer.tell() >= CHUNK_BYTES:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
    if buffer.tell():
        yield buffer.getvalue()


def _export(open_export: Callable[[], object], filename: str) -> StreamingResponse:
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=RIDERS_NOT_CONFIGURED)
    return StreamingResponse(
        _csv_stream(open_export),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/teams.csv")
def export_teams_csv(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return _export(db.export_teams, "teams.csv")


@router.get("/riders.csv")
def export_riders_csv(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return _export(db.export_riders, "riders.csv")


@router.get("/stints.csv")
def export_stints_csv(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return _export(db.export_stints, "rider_team_stints.csv")


@router.get("/seasons.csv")
def export_seasons_csv(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return _export(db.export_seasons, "rider_seasons.csv")


@router.get("/races.csv")
def export_races_csv(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return _export(db_races.export_races, "races.csv")


@router.get("/race_results.csv")
def export_race_results_csv(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return _export(db_races.export_race_results, "race_results.csv")


@router.get("/race_stages.csv")
def export_race_stages_csv(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return _export(db_races.export_race_stages, "race_stages.csv")
