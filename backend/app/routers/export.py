"""CSV-Export der Fahrer-Datenbank (eine Datei pro Tabelle).

Liefert die Rohdaten roh als CSV zum Download - nützlich für eigene
Auswertungen (Excel, Pandas, ...) unabhängig von der JSON-API.
"""
import csv
import io
from typing import Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import db

router = APIRouter(prefix="/api/export", tags=["export"])


def _serialize(value):
    # psycopg liefert date/datetime-Objekte - für CSV als ISO-String ausgeben
    return value.isoformat() if hasattr(value, "isoformat") else value


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _serialize(value) for key, value in row.items()})
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _export(fetch_rows: Callable[[], list[dict]], filename: str) -> StreamingResponse:
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Fahrer-Datenbank nicht konfiguriert (DATABASE_URL fehlt)")
    return _csv_response(fetch_rows(), filename)


@router.get("/teams.csv")
def export_teams_csv():
    return _export(db.export_teams, "teams.csv")


@router.get("/riders.csv")
def export_riders_csv():
    return _export(db.export_riders, "riders.csv")


@router.get("/stints.csv")
def export_stints_csv():
    return _export(db.export_stints, "rider_team_stints.csv")


@router.get("/seasons.csv")
def export_seasons_csv():
    return _export(db.export_seasons, "rider_seasons.csv")
