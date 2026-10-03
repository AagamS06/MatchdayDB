"""Run `python app.py` to serve MatchdayDB at http://localhost:8000."""

import argparse
import asyncio
import json
import logging
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import uvicorn
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from config import ROOT, Settings
from database import Database
from embeddings import LocalEmbedder, index_players, valid_index
from errors import MatchdayError
from ingestion import ingest
from models import Filters, Ranking, SyncRequest, utc_now
from scout import Scout, public_player

LOGGER = logging.getLogger("matchdaydb")


class SyncManager:
    """One durable sync job at a time, protected across local processes."""

    def __init__(self, settings: Settings, database: Database, embedder: LocalEmbedder) -> None:
        self.settings, self.database, self.embedder = settings, database, embedder
        self.stop = threading.Event()
        self.guard = threading.Lock()
        self.file_lock = FileLock(str(database.path) + ".sync.lock", timeout=0, thread_local=False)
        self.thread: threading.Thread | None = None
        self.run_id: str | None = None

    def _save(self, run_id: str, state: str, report: dict[str, Any]) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE sync_runs SET state=?,finished_at=?,report_json=? WHERE run_id=?",
                (
                    state,
                    None if state == "running" else utc_now(),
                    json.dumps(report, allow_nan=False),
                    run_id,
                ),
            )

    def start(self, request: SyncRequest) -> str:
        with self.guard:
            if self.stop.is_set():
                raise MatchdayError("SHUTTING_DOWN", "The application is shutting down.", 503)
            if self.thread and self.thread.is_alive():
                raise MatchdayError(
                    "SYNC_IN_PROGRESS",
                    "A synchronization is already running.",
                    409,
                    details={"run_id": self.run_id},
                )
            try:
                self.file_lock.acquire()
            except Timeout as exc:
                raise MatchdayError(
                    "SYNC_IN_PROGRESS", "Another local process owns synchronization.", 409
                ) from exc
            run_id = str(uuid.uuid4())
            try:
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE sync_runs SET state='interrupted',finished_at=? WHERE state='running'",
                        (utc_now(),),
                    )
                    connection.execute(
                        "INSERT INTO sync_runs(run_id,state,started_at,report_json) VALUES (?,'running',?,?)",
                        (run_id, utc_now(), json.dumps({"stage": "ingesting"})),
                    )
                self.run_id = run_id
                self.thread = threading.Thread(
                    target=self._work, args=(run_id, request), daemon=True, name="matchday-sync"
                )
                self.thread.start()
            except BaseException:
                self.file_lock.release()
                raise
            return run_id

    def _work(self, run_id: str, request: SyncRequest) -> None:
        report: dict[str, Any] = {}
        state = "failed"
        try:
            report = ingest(self.settings, self.database, request, self.stop)
            state = report.get("state", "succeeded")
            self._save(run_id, "running", {**report, "stage": "indexing"})
            try:
                report["index"] = index_players(self.database, self.embedder, self.stop)
            except MatchdayError as exc:
                report["index_error"] = {"code": exc.code, "message": exc.message}
                state = "partial"
            if self.stop.is_set():
                state = "interrupted"
        except MatchdayError as exc:
            state = "interrupted" if exc.code == "INTERRUPTED" else "failed"
            report["error"] = {"code": exc.code, "message": exc.message}
        except Exception as exc:
            LOGGER.error("Synchronization %s failed (%s)", run_id, type(exc).__name__)
            report["error"] = {
                "code": "SYNC_FAILED",
                "message": "Synchronization failed; inspect local logs and retry.",
            }
        finally:
            try:
                self._save(run_id, state, {**report, "stage": "complete"})
            except sqlite3.Error as exc:
                LOGGER.error("Could not persist job state (%s)", type(exc).__name__)
            finally:
                self.file_lock.release()

    def close(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive() and self.run_id:
                self._save(
                    self.run_id,
                    "interrupted",
                    {
                        "error": {
                            "code": "INTERRUPTED",
                            "message": "Application shut down before this run finished.",
                        }
                    },
                )


def create_app(
    settings: Settings | None = None, *, bootstrap: bool = True, embedder: LocalEmbedder | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.db_path, settings.source, settings.season)
    engine = embedder or LocalEmbedder(settings)
    scout = Scout(database, engine)
    manager = SyncManager(settings, database, engine)

    async def poll() -> None:
        while not manager.stop.is_set():
            await asyncio.sleep(settings.poll_seconds)
            try:
                await asyncio.to_thread(manager.start, SyncRequest())
            except MatchdayError as exc:
                if exc.code != "SYNC_IN_PROGRESS":
                    LOGGER.warning("Scheduled sync unavailable (%s)", exc.code)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        if bootstrap:
            try:
                manager.start(SyncRequest(index_only=settings.offline and settings.source == "api"))
            except MatchdayError as exc:
                LOGGER.warning("Startup sync unavailable (%s)", exc.code)
        task = asyncio.create_task(poll()) if settings.poll_seconds and not settings.offline else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    LOGGER.debug("Polling task stopped")
            await asyncio.to_thread(manager.close)

    application = FastAPI(
        title="MatchdayDB",
        version="0.1.0",
        lifespan=lifespan,
        description="Local football data ingestion and semantic scouting.",
        docs_url=None,
        redoc_url=None,
    )
    application.state.database, application.state.engine = database, engine
    application.state.manager = manager
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @application.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        request.state.request_id = str(uuid.uuid4())
        if request.method == "POST":
            origin = request.headers.get("origin")
            expected = urlsplit(str(request.base_url))
            if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (
                expected.scheme,
                expected.netloc,
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "ORIGIN_REJECTED",
                            "message": "Use the dashboard's own origin.",
                            "retryable": False,
                            "request_id": request.state.request_id,
                            "details": {},
                        }
                    },
                )
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse(
                    status_code=415,
                    content={
                        "error": {
                            "code": "JSON_REQUIRED",
                            "message": "Send application/json.",
                            "retryable": False,
                            "request_id": request.state.request_id,
                            "details": {},
                        }
                    },
                )
        try:
            response = await call_next(request)
        except Exception as exc:
            LOGGER.error("Request %s failed (%s)", request.state.request_id, type(exc).__name__)
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An internal error occurred.",
                        "retryable": False,
                        "request_id": request.state.request_id,
                        "details": {},
                    }
                },
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        )
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def error_response(request: Request, error: MatchdayError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "retryable": error.retryable,
                    "details": error.details,
                    "request_id": getattr(request.state, "request_id", "unknown"),
                }
            },
        )

    @application.exception_handler(MatchdayError)
    async def domain_error(request: Request, exc: MatchdayError) -> JSONResponse:
        return error_response(request, exc)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = {"fields": [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]}
        return error_response(
            request, MatchdayError("VALIDATION_ERROR", "Check the request fields.", 422, details=details)
        )

    @application.exception_handler(sqlite3.Error)
    async def storage_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        LOGGER.error("Storage operation failed (%s)", type(exc).__name__)
        return error_response(
            request,
            MatchdayError("STORAGE_UNAVAILABLE", "Local storage is temporarily unavailable.", 503, True),
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(request, MatchdayError("HTTP_ERROR", str(exc.detail), exc.status_code))

    def filter_params(
        max_age: Annotated[int | None, Query(ge=14, le=60)] = None,
        position: str | None = None,
        nationality: str | None = None,
        team_id: Annotated[int | None, Query(gt=0)] = None,
        league: str | None = None,
        as_of: date | None = None,
    ) -> Filters:
        from pydantic import ValidationError

        fields = dict(
            max_age=max_age, position=position, nationality=nationality, team_id=team_id, league=league
        )
        if as_of is not None:
            fields["as_of"] = as_of
        try:
            return Filters(**fields)
        except ValidationError as exc:
            raise MatchdayError(
                "INVALID_FILTER", "Check position, country, league, and age filters.", 422
            ) from exc

    @application.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(ROOT / "static" / "index.html")

    @application.get("/search")
    def search(
        q: Annotated[str, Query(min_length=3, max_length=1000)],
        filters: Annotated[Filters, Depends(filter_params)],
        top_k: Annotated[int, Query(ge=1, le=50)] = 12,
    ) -> dict[str, Any]:
        return scout.search(q, filters, top_k)

    @application.get("/similar/{player_name}")
    def similar(
        player_name: str,
        filters: Annotated[Filters, Depends(filter_params)],
        top_k: Annotated[int, Query(ge=1, le=50)] = 5,
        player_id: Annotated[int | None, Query(gt=0)] = None,
        ranking: Ranking = "semantic",
        cross_role: bool = False,
    ) -> dict[str, Any]:
        return scout.similar(player_name, filters, top_k, player_id, ranking, cross_role)

    @application.get("/players")
    def players(
        filters: Annotated[Filters, Depends(filter_params)],
        limit: Annotated[int, Query(ge=1, le=100)] = 12,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        rows = sorted(database.candidates(filters), key=lambda row: (row["name_key"], row["player_id"]))
        return {
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "items": [
                public_player(row, filters.as_of, valid_index(row, engine, settings.season))
                for row in rows[offset : offset + limit]
            ],
        }

    @application.get("/options")
    def options() -> dict[str, Any]:
        rows = sorted(database.candidates(), key=lambda row: (row["name_key"], row["player_id"]))
        return {
            "players": [
                {key: row[key] for key in ("player_id", "name", "position", "team_name")} for row in rows
            ],
            "positions": sorted({r["position"] for r in rows}),
            "nationalities": sorted({r["nationality"] for r in rows if r["nationality"]}),
            "leagues": sorted({r["league"] for r in rows if r["league"]}),
        }

    @application.get("/fixtures")
    def fixtures() -> dict[str, Any]:
        with database.read() as connection:
            rows = connection.execute("""SELECT f.match_id,f.kickoff,f.status,f.home_score,f.away_score,
                h.short_name AS home,h.name AS home_name,a.short_name AS away,a.name AS away_name,
                f.observed_at FROM fixtures f JOIN teams h ON h.team_id=f.home_team_id
                JOIN teams a ON a.team_id=f.away_team_id ORDER BY f.kickoff DESC LIMIT 6""").fetchall()
        return {"synthetic": settings.source == "demo", "items": [dict(row) for row in rows]}

    def job_record(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["report"] = json.loads(result.pop("report_json"))
        return result

    @application.get("/health")
    def health() -> dict[str, Any]:
        rows = database.candidates()
        with database.read() as connection:
            latest = connection.execute(
                "SELECT * FROM sync_runs ORDER BY started_at DESC,rowid DESC LIMIT 1"
            ).fetchone()
            teams = connection.execute("SELECT count(*) FROM teams").fetchone()[0]
            matches = connection.execute("SELECT count(*) FROM fixtures").fetchone()[0]
        indexed = sum(valid_index(row, engine, settings.season) for row in rows)
        return {
            "status": "ok",
            "source": settings.source,
            "synthetic": settings.source == "demo",
            "offline": settings.offline,
            "season": settings.season,
            "players": len(rows),
            "teams": teams,
            "fixtures": matches,
            "indexed": indexed,
            "model_ready": engine.ready,
            "search_ready": engine.ready and indexed > 0,
            "model_id": engine.model_id,
            "model_version": engine.version,
            "last_sync": job_record(latest) if latest else None,
            "reference_date": database.meta("reference_date") or None,
        }

    @application.post("/sync", status_code=202)
    def sync(body: SyncRequest) -> dict[str, str]:
        run_id = manager.start(body)
        return {"run_id": run_id, "status_url": f"/sync/{run_id}"}

    @application.get("/sync/{run_id}")
    def sync_status(run_id: uuid.UUID) -> dict[str, Any]:
        with database.read() as connection:
            row = connection.execute("SELECT * FROM sync_runs WHERE run_id=?", (str(run_id),)).fetchone()
        if row is None:
            raise MatchdayError("JOB_NOT_FOUND", "No synchronization has this ID.", 404)
        return job_record(row)

    application.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return application


def main() -> None:
    parser = argparse.ArgumentParser(description="MatchdayDB local scouting dashboard")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1")
    parser.add_argument(
        "--prepare-model", action="store_true", help="Download and verify the model, then exit"
    )
    parser.add_argument(
        "--no-bootstrap", action="store_true", help="Serve existing data without startup synchronization"
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
        if args.prepare_model:
            engine = LocalEmbedder(settings)
            engine.prepare()
            print(f"Model ready: {engine.model_id}\nFingerprint: {engine.version}")
        else:
            uvicorn.run(
                create_app(settings, bootstrap=not args.no_bootstrap),
                host=args.host,
                port=args.port,
                access_log=False,
            )
    except (ValueError, MatchdayError) as exc:
        parser.exit(1, f"MatchdayDB: {exc}\n")


if __name__ == "__main__":
    main()
