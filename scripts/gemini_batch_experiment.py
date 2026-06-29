from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.genai import types

from reddit2video.cli import _load_env_file
from reddit2video.gemini import GeminiClient


COMPLETED_STATES = {
    "JOB_STATE_SUCCEEDED",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",
    "JOB_STATE_PAUSED",
    "JOB_STATE_PARTIALLY_SUCCEEDED",
    "JOB_STATE_EXPIRED",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Small Vertex Gemini batch experiment: prepare JSONL, submit, poll, and optionally download output."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--local-jsonl", default="outputs/gemini-batch-experiment/input.jsonl")
    parser.add_argument("--local-output-dir", default="outputs/gemini-batch-experiment/result")
    parser.add_argument("--input-uri", default=None, help="Existing gs://... JSONL input. Skips upload.")
    parser.add_argument("--output-uri", default=None, help="gs://... output prefix for Vertex batch result.")
    parser.add_argument("--bucket", default=None, help="gs://bucket-or-prefix used with --upload.")
    parser.add_argument("--upload", action="store_true", help="Upload local JSONL to --bucket with gcloud storage cp.")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--job-name", default=None, help="Existing job name for --poll/--download.")
    parser.add_argument("--poll-interval", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--image-gcs-uri", default=None, help="Optional gs:// image URI for one multimodal JSONL row.")
    parser.add_argument("--image-mime-type", default="image/jpeg")
    parser.add_argument("--dry-run", action="store_true", help="Only write JSONL and print next command hints.")
    args = parser.parse_args()

    _load_env_file(Path(args.env_file))
    if not args.bucket:
        args.bucket = os.getenv("GEMINI_BATCH_GCS_PREFIX")
    if args.submit and not args.output_uri and args.bucket:
        args.output_uri = f"{args.bucket.rstrip('/')}/gemini-batch-output/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    local_jsonl = Path(args.local_jsonl)
    local_jsonl.parent.mkdir(parents=True, exist_ok=True)
    rows = _build_rows(image_gcs_uri=args.image_gcs_uri, image_mime_type=args.image_mime_type)
    _write_jsonl(local_jsonl, rows)
    print(json.dumps({"local_jsonl": str(local_jsonl), "rows": len(rows)}, ensure_ascii=False))

    input_uri = args.input_uri
    if args.upload:
        if not args.bucket:
            print("Error: --upload requires --bucket gs://...", file=sys.stderr)
            return 2
        input_uri = _upload_jsonl(local_jsonl, args.bucket)
        print(json.dumps({"uploaded_input_uri": input_uri}, ensure_ascii=False))

    if args.dry_run or not (args.submit or args.poll or args.download):
        _print_hints(local_jsonl=local_jsonl, input_uri=input_uri, output_uri=args.output_uri)
        return 0

    client_wrapper = GeminiClient.from_env(model=args.model, vertex=True)
    client = client_wrapper._ensure_client()
    try:
        job_name = args.job_name
        job = None
        if args.submit:
            if not input_uri:
                print("Error: --submit requires --input-uri or --upload --bucket.", file=sys.stderr)
                return 2
            if not args.output_uri:
                print("Error: --submit requires --output-uri gs://... or bq://...", file=sys.stderr)
                return 2
            job = client.batches.create(
                model=args.model,
                src=input_uri,
                config=types.CreateBatchJobConfig(
                    display_name=args.display_name or _default_display_name(),
                    dest=args.output_uri,
                    http_options=types.HttpOptions(api_version="v1"),
                ),
            )
            job_name = job.name
            print(_job_json(job))

        if args.poll:
            if not job_name:
                print("Error: --poll requires --job-name or --submit.", file=sys.stderr)
                return 2
            job = _poll(client, job_name, args.poll_interval, args.timeout_seconds)
            print(_job_json(job))

        if args.download:
            if not args.output_uri and job is not None:
                args.output_uri = _job_dest_uri(job)
            if not args.output_uri:
                print("Error: --download requires --output-uri or a submitted/polled job with GCS dest.", file=sys.stderr)
                return 2
            if not args.output_uri.startswith("gs://"):
                print("Download helper only supports GCS output. BigQuery output stays in the destination table.")
                return 0
            _download_output(args.output_uri, Path(args.local_output_dir))
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    return 0


def _build_rows(*, image_gcs_uri: str | None, image_mime_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "request": {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": "Answer in one short sentence: what is the purpose of this batch test?"}],
                    }
                ],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 64},
            }
        }
    ]
    if image_gcs_uri:
        rows.append(
            {
                "request": {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": "Describe this image in one short sentence."},
                                {"fileData": {"fileUri": image_gcs_uri, "mimeType": image_mime_type}},
                            ],
                        }
                    ],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 64},
                }
            }
        )
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _upload_jsonl(path: Path, bucket: str) -> str:
    prefix = bucket.rstrip("/")
    if not prefix.startswith("gs://"):
        raise SystemExit("--bucket must start with gs://")
    remote = f"{prefix}/gemini-batch-experiment/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}/input.jsonl"
    _run(["gcloud", "storage", "cp", str(path), remote])
    return remote


def _poll(client: Any, job_name: str, interval: int, timeout: int) -> Any:
    deadline = time.monotonic() + timeout
    job = client.batches.get(name=job_name, config=types.GetBatchJobConfig(http_options=types.HttpOptions(api_version="v1")))
    while _state_name(job.state) not in COMPLETED_STATES:
        print(json.dumps({"job": job.name, "state": _state_name(job.state), "update_time": str(job.update_time)}, ensure_ascii=False))
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for {job_name}; last state={_state_name(job.state)}")
        time.sleep(interval)
        job = client.batches.get(
            name=job_name,
            config=types.GetBatchJobConfig(http_options=types.HttpOptions(api_version="v1")),
        )
    return job


def _download_output(output_uri: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _run(["gcloud", "storage", "cp", "--recursive", output_uri.rstrip("/") + "/", str(output_dir)])
    print(json.dumps({"downloaded_to": str(output_dir)}, ensure_ascii=False))


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise SystemExit("gcloud CLI is required for upload/download helpers.") from exc


def _state_name(state: Any) -> str:
    return getattr(state, "name", str(state))


def _job_dest_uri(job: Any) -> str | None:
    dest = getattr(job, "dest", None)
    if dest is None:
        return None
    return getattr(dest, "gcs_uri", None) or getattr(dest, "bigquery_uri", None)


def _job_json(job: Any) -> str:
    payload = {
        "name": getattr(job, "name", None),
        "state": _state_name(getattr(job, "state", None)),
        "model": getattr(job, "model", None),
        "dest": _job_dest_uri(job),
        "create_time": str(getattr(job, "create_time", None)),
        "update_time": str(getattr(job, "update_time", None)),
        "end_time": str(getattr(job, "end_time", None)),
        "error": str(getattr(job, "error", None)),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _default_display_name() -> str:
    return "reddit2video-gemini-batch-experiment-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _print_hints(*, local_jsonl: Path, input_uri: str | None, output_uri: str | None) -> None:
    print("Prepared local JSONL. Vertex batch submit needs GCS or BigQuery input/output.")
    if input_uri and output_uri:
        print(f"Submit example: python3 scripts/gemini_batch_experiment.py --submit --poll --download --input-uri {input_uri} --output-uri {output_uri}")
    else:
        print(f"Upload+submit example: python3 scripts/gemini_batch_experiment.py --upload --bucket gs://YOUR_BUCKET --submit --poll --download --output-uri gs://YOUR_BUCKET/gemini-batch-output")
    print(f"Inspect JSONL: {local_jsonl}")


if __name__ == "__main__":
    raise SystemExit(main())
