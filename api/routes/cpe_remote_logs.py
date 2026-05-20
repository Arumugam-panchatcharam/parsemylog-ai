"""
Admin-only remote CPE bundle download (two-phase Celery orchestration).

Tokens are supplied per request — never persisted in the DB.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from api.app import dbm
from api.auth import admin_required, get_user_id
from api.services.cpe_remote_log.bulk_device_list import (
    build_device_list_from_serials,
    iso_bounds_from_ranges_payload,
    parse_bulk_device_list_json,
    parse_serial_numbers_text,
)
from api.services.cpe_remote_log.range_datetime import (
    DEFAULT_END_TIME,
    DEFAULT_START_TIME,
    canonical_range_bound,
)
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

cpe_remote_logs_bp = Blueprint("cpe_remote_logs", __name__)



def _verify_project_owned(project_id: str, user_id: int):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if getattr(project, "user_id", None) != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _resolve_tenant_id(project) -> str | None:
    if not project.natco_id:
        return None
    natco = dbm.db.session.get(dbm.Natco, int(project.natco_id))
    if not natco:
        return None
    tid = (getattr(natco, "remote_log_tenant_id", None) or "").strip().lower()
    if tid:
        return tid
    fallback = natco.code.strip().lower()
    if fallback:
        logger.warning(
            "[RemoteFetch] NATCO %s has no remote_log_tenant_id; using code %r as x-tenant-id. "
            "Set Admin → NATCO → Remote log tenant id to the x-tenant-id header value if registry returns HTTP 403.",
            getattr(natco, "code", "?"),
            fallback,
        )
    return fallback


def _serialize_unit(u) -> dict[str, Any]:
    requested_from: str | None = None
    requested_to: str | None = None
    try:
        dj = json.loads(u.ranges_json)
        rf, rt = iso_bounds_from_ranges_payload(dj)
        requested_from = rf
        requested_to = rt
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    return {
        "id": u.id,
        "ordinal": u.ordinal,
        "serial_number": u.serial_number,
        "ranges_json": u.ranges_json,
        "requested_date_from": requested_from,
        "requested_date_to": requested_to,
        "download_status": u.download_status,
        "process_status": u.process_status,
        "bundle_relpath": u.bundle_relpath,
        "last_error": u.last_error,
    }


@cpe_remote_logs_bp.route("/<project_id>/cpe-remote-logs/jobs", methods=["GET"])
@admin_required
def list_remote_jobs(project_id: str):
    user_id = int(get_user_id())
    _, err = _verify_project_owned(project_id, user_id)
    if err:
        return err
    jobs = dbm.list_remote_log_fetch_jobs(project_id, limit=80)
    return (
        jsonify(
            [
                {
                    "id": j.id,
                    "batch_job_id": j.batch_job_id,
                    "status": j.status,
                    "staging_relpath": j.staging_relpath,
                    "created_at": str(j.created_at) if j.created_at else None,
                    "error_message": j.error_message,
                }
                for j in jobs
            ]
        ),
        200,
    )


@cpe_remote_logs_bp.route("/<project_id>/cpe-remote-logs/jobs/<fetch_job_id>", methods=["GET"])
@admin_required
def get_remote_job(project_id: str, fetch_job_id: str):
    user_id = int(get_user_id())
    _, err = _verify_project_owned(project_id, user_id)
    if err:
        return err
    j = dbm.get_remote_log_fetch_job(fetch_job_id)
    if not j or j.project_id != project_id:
        return jsonify({"error": "Fetch job not found"}), 404
    units = dbm.get_remote_log_fetch_units_ordered(fetch_job_id)
    return (
        jsonify(
            {
                "job": {
                    "id": j.id,
                    "batch_job_id": j.batch_job_id,
                    "status": j.status,
                    "staging_relpath": j.staging_relpath,
                    "created_at": str(j.created_at) if getattr(j, "created_at", None) else None,
                    "error_message": j.error_message,
                },
                "units": [_serialize_unit(u) for u in units],
            }
        ),
        200,
    )


@cpe_remote_logs_bp.route("/<project_id>/cpe-remote-logs/start-normal", methods=["POST"])
@admin_required
def start_normal_remote_fetch(project_id: str):
    user_id = int(get_user_id())
    project, err = _verify_project_owned(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    serial = str(data.get("serial_number") or "").strip()
    dre = str(data.get("device_registry_bearer") or "").strip()
    cpe = str(data.get("crash_portal_bearer") or "").strip()

    ranges_in = data.get("ranges")
    ranges_json: str
    if isinstance(ranges_in, list) and len(ranges_in) > 0:
        cleaned: list[dict[str, str]] = []
        for item in ranges_in:
            if not isinstance(item, dict):
                continue
            start_raw = str(item.get("start") or "").strip()
            end_raw = str(item.get("end") or "").strip()
            if not start_raw or not end_raw:
                continue
            try:
                cleaned.append(
                    {
                        "start": canonical_range_bound(start_raw, DEFAULT_START_TIME),
                        "end": canonical_range_bound(end_raw, DEFAULT_END_TIME),
                    }
                )
            except ValueError:
                continue
        if not cleaned:
            return (
                jsonify(
                    {
                        "error": "ranges must include objects with start, end "
                        "(YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
                    }
                ),
                400,
            )
        ranges_json = json.dumps(cleaned)
    else:
        date_start = str(data.get("date_start") or "").strip()
        date_end = str(data.get("date_end") or "").strip()
        if not date_start or not date_end:
            return (
                jsonify(
                    {
                        "error": "serial_number, date_start, date_end required, or use ranges[] "
                        "(dates may include time: YYYY-MM-DDTHH:MM:SS)"
                    }
                ),
                400,
            )
        try:
            ranges_json = json.dumps(
                [
                    {
                        "start": canonical_range_bound(date_start, DEFAULT_START_TIME),
                        "end": canonical_range_bound(date_end, DEFAULT_END_TIME),
                    }
                ]
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    if not serial:
        return jsonify({"error": "serial_number required"}), 400
    if not dre:
        return jsonify({"error": "device_registry_bearer required"}), 400

    if getattr(project, "project_type", "normal") != "normal":
        return jsonify({"error": "Project must be normal type"}), 400

    tenant = _resolve_tenant_id(project)
    natco_row = dbm.db.session.get(dbm.Natco, project.natco_id) if project.natco_id else None
    if not tenant or not natco_row:
        return jsonify({"error": "NATCO with remote_log_tenant_id required for remote fetch"}), 400

    fetch_id = str(uuid.uuid4())
    staging_rel = Path(".remote_logs") / fetch_id

    uid = dbm.create_remote_log_fetch_single_normal(
        fetch_job_id=fetch_id,
        project_id=project_id,
        user_id=user_id,
        staging_relpath=str(staging_rel),
        serial=serial,
        ranges_json=ranges_json,
    )

    staging_abs = Path(UPLOAD_DIRECTORY) / str(user_id) / project_id / staging_rel
    staging_abs.mkdir(parents=True, exist_ok=True)

    cred = {
        "device_registry_bearer": dre,
        "crash_portal_bearer": cpe,
        "tenant_id": tenant,
        "natco_code": natco_row.code.strip(),
    }
    try:
        from services.celery_worker.tasks import advance_remote_log_fetch_job

        advance_remote_log_fetch_job.delay(fetch_id, cred)
    except Exception as exc:
        logger.exception("[RemoteFetch] Failed to enqueue: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"fetch_job_id": fetch_id, "unit_id": uid}), 202


@cpe_remote_logs_bp.route("/<project_id>/cpe-remote-logs/start-bulk", methods=["POST"])
@admin_required
def start_bulk_remote_fetch(project_id: str):
    user_id = int(get_user_id())
    project, err = _verify_project_owned(project_id, user_id)
    if err:
        return err

    if getattr(project, "project_type", "normal") != "batch":
        return jsonify({"error": "Project must be batch type"}), 400

    tenant = _resolve_tenant_id(project)
    natco_row = dbm.db.session.get(dbm.Natco, project.natco_id) if project.natco_id else None
    if not tenant or not natco_row:
        return jsonify({"error": "NATCO with remote_log_tenant_id required for remote fetch"}), 400

    dre = str(request.form.get("device_registry_bearer") or "").strip()
    cpe = str(request.form.get("crash_portal_bearer") or "").strip()
    bulk_input_mode = str(request.form.get("bulk_input_mode") or "json_file").strip().lower()
    ds = request.form.get("default_date_start")
    de = request.form.get("default_date_end")
    ds_time = request.form.get("default_date_start_time")
    de_time = request.form.get("default_date_end_time")
    if not dre:
        return jsonify({"error": "device_registry_bearer field required"}), 400

    payload: Any
    if bulk_input_mode == "serial_list":
        serials_raw = str(request.form.get("serial_numbers") or "")
        range_start = str(request.form.get("range_start") or "").strip()
        range_end = str(request.form.get("range_end") or "").strip()
        serials, serial_err = parse_serial_numbers_text(serials_raw)
        if serial_err:
            return jsonify({"error": serial_err}), 400
        if not range_start or not range_end:
            return jsonify({"error": "range_start and range_end are required for serial list mode"}), 400
        try:
            canonical_range_bound(range_start, DEFAULT_START_TIME)
            canonical_range_bound(range_end, DEFAULT_END_TIME)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        assert serials is not None
        payload = build_device_list_from_serials(serials, range_start, range_end)
    else:
        f = request.files.get("device_list_json")
        if not f:
            return jsonify({"error": "device_list_json file required"}), 400
        try:
            raw = f.read()
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return jsonify({"error": f"Invalid JSON: {exc}"}), 400

    parsed, parse_err = parse_bulk_device_list_json(
        payload,
        str(ds or "").strip()[:10] if ds else None,
        str(de or "").strip()[:10] if de else None,
        default_start_time=str(ds_time or "").strip() or None,
        default_end_time=str(de_time or "").strip() or None,
    )
    if parse_err:
        return jsonify({"error": parse_err}), 400

    fetch_id = str(uuid.uuid4())
    batch_id = str(uuid.uuid4())

    staging_rel = Path(".remote_logs") / fetch_id

    staging_abs = Path(UPLOAD_DIRECTORY) / str(user_id) / project_id / staging_rel
    staging_abs.mkdir(parents=True, exist_ok=True)

    cpe_zips_abs = staging_abs / "cpe_zips"
    cpe_zips_abs.mkdir(parents=True, exist_ok=True)

    entries = [(ord_i, serial, rj) for ord_i, serial, rj in parsed]

    dbm.create_batch_job(project_id, user_id, len(entries), job_id=batch_id)

    dbm.create_remote_log_fetch_bundle(
        fetch_job_id=fetch_id,
        project_id=project_id,
        user_id=user_id,
        batch_job_id=batch_id,
        staging_relpath=str(Path(staging_rel) / "cpe_zips"),
        entries=[(ordinal, serial, rj) for ordinal, serial, rj in entries],
    )

    cred = {
        "device_registry_bearer": dre,
        "crash_portal_bearer": cpe,
        "tenant_id": tenant,
        "natco_code": natco_row.code.strip(),
    }

    try:
        from services.celery_worker.tasks import advance_remote_log_fetch_job

        advance_remote_log_fetch_job.delay(fetch_id, cred)
    except Exception as exc:
        logger.exception("[RemoteFetch] Failed to enqueue bulk: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return (
        jsonify(
            {"fetch_job_id": fetch_id, "batch_job_id": batch_id, "unit_count": len(entries)}
        ),
        202,
    )


@cpe_remote_logs_bp.route(
    "/<project_id>/cpe-remote-logs/jobs/<fetch_job_id>/retry-failed",
    methods=["POST"],
)
@admin_required
def retry_failed_remote_job(project_id: str, fetch_job_id: str):
    user_id = int(get_user_id())
    _, err = _verify_project_owned(project_id, user_id)
    if err:
        return err
    fj = dbm.get_remote_log_fetch_job(fetch_job_id)
    if not fj or fj.project_id != project_id:
        return jsonify({"error": "Fetch job not found"}), 404

    data = request.get_json(silent=True) or {}
    dre = str(data.get("device_registry_bearer") or "").strip()
    cpe = str(data.get("crash_portal_bearer") or "").strip()
    if not dre:
        return jsonify({"error": "device_registry_bearer required"}), 400

    proj = dbm.get_project_by_id(project_id)
    tenant = _resolve_tenant_id(proj)
    natco_row = dbm.db.session.get(dbm.Natco, proj.natco_id) if proj and proj.natco_id else None
    if not tenant or not natco_row:
        return jsonify({"error": "NATCO configuration missing"}), 400

    n = dbm.reset_remote_log_fetch_units_for_retry_failed(fetch_job_id)
    if n <= 0:
        return jsonify({"message": "No failed rows to retry", "reset_count": 0}), 200

    cred = {
        "device_registry_bearer": dre,
        "crash_portal_bearer": cpe,
        "tenant_id": tenant,
        "natco_code": natco_row.code.strip(),
    }
    try:
        from services.celery_worker.tasks import advance_remote_log_fetch_job

        advance_remote_log_fetch_job.delay(fetch_job_id, cred)
    except Exception as exc:
        logger.exception("[RemoteFetch] retry enqueue failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"message": "Retry scheduled", "reset_count": n}), 202


@cpe_remote_logs_bp.route(
    "/<project_id>/cpe-remote-logs/jobs/<fetch_job_id>/restart",
    methods=["POST"],
)
@admin_required
def restart_remote_job(project_id: str, fetch_job_id: str):
    user_id = int(get_user_id())
    _, err = _verify_project_owned(project_id, user_id)
    if err:
        return err
    fj = dbm.get_remote_log_fetch_job(fetch_job_id)
    if not fj or fj.project_id != project_id:
        return jsonify({"error": "Fetch job not found"}), 404

    data = request.get_json(silent=True) or {}
    dre = str(data.get("device_registry_bearer") or "").strip()
    cpe = str(data.get("crash_portal_bearer") or "").strip()
    wipe = bool(data.get("wipe_artifacts"))

    if not dre:
        return jsonify({"error": "device_registry_bearer required"}), 400

    proj = dbm.get_project_by_id(project_id)
    tenant = _resolve_tenant_id(proj)
    natco_row = dbm.db.session.get(dbm.Natco, proj.natco_id) if proj and proj.natco_id else None
    if not tenant or not natco_row:
        return jsonify({"error": "NATCO configuration missing"}), 400

    if wipe:
        bucket = Path(UPLOAD_DIRECTORY) / str(user_id) / project_id / ".remote_logs" / fetch_job_id
        shutil.rmtree(bucket, ignore_errors=True)

    dbm.reset_remote_log_fetch_job_restart_all(fetch_job_id)

    staging_target = Path(UPLOAD_DIRECTORY) / str(user_id) / project_id / fj.staging_relpath
    staging_target.parent.mkdir(parents=True, exist_ok=True)
    staging_target.mkdir(parents=True, exist_ok=True)

    cred = {
        "device_registry_bearer": dre,
        "crash_portal_bearer": cpe,
        "tenant_id": tenant,
        "natco_code": natco_row.code.strip(),
    }
    try:
        from services.celery_worker.tasks import advance_remote_log_fetch_job

        advance_remote_log_fetch_job.delay(fetch_job_id, cred)
    except Exception as exc:
        logger.exception("[RemoteFetch] restart enqueue failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"message": "Restart scheduled"}), 202
