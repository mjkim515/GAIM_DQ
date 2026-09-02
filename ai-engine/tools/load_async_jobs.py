#!/usr/bin/env python3
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from urllib import error, request


TERMINAL_STATUSES = {"completed", "failed"}


@dataclass
class Job:
    kind: str
    index: int
    job_id: str
    queued_ms: int
    status_url: str


def post_json(url: str, payload: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, Any], int]:
    started = time.monotonic()
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data, elapsed_ms(started)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        data = json.loads(raw) if raw else {"error": str(exc)}
        return exc.code, data, elapsed_ms(started)


def get_json(url: str, timeout: float) -> Tuple[int, Dict[str, Any], int]:
    started = time.monotonic()
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data, elapsed_ms(started)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        data = json.loads(raw) if raw else {"error": str(exc)}
        return exc.code, data, elapsed_ms(started)


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def image_payload(index: int) -> Dict[str, Any]:
    return {
        "purpose": "홍보",
        "visual_mood": "bright",
        "channels": ["인스타"],
        "image_prompt": f"동시성 테스트용 로컬 카페 홍보 이미지 {index}",
        "n": 1,
    }


def video_payload(index: int) -> Dict[str, Any]:
    return {
        "prompt": f"동시성 테스트용 로컬 카페 신메뉴 숏폼 영상 {index}",
        "model": "fast",
        "platform": "instagram_reels",
        "task": "textToVideo",
        "aspectRatio": "9:16",
        "durationSeconds": 4,
        "advanced": {
            "generateAudio": True,
        },
        "metadata": {
            "loadTestIndex": index,
        },
    }


def submit_job(base_url: str, kind: str, index: int, timeout: float) -> Job:
    if kind == "image":
        path = "/api/ai/image/async/generate"
        payload = image_payload(index)
        status_path = "/api/ai/image/async/job"
    else:
        path = "/api/ai/video/async/generate"
        payload = video_payload(index)
        status_path = "/api/ai/video/async/job"

    status, data, queued_ms = post_json(f"{base_url}{path}", payload, timeout)
    if status != 200:
        raise RuntimeError(f"{kind.upper()} {index} enqueue failed HTTP {status}: {data}")

    job_id = data.get("jobId")
    if not job_id:
        raise RuntimeError(f"{kind.upper()} {index} missing jobId in response: {data}")

    print(f"{kind.upper()} {index} queued in {queued_ms}ms jobId={job_id}")
    return Job(
        kind=kind,
        index=index,
        job_id=job_id,
        queued_ms=queued_ms,
        status_url=f"{base_url}{status_path}/{job_id}",
    )


def submit_jobs(base_url: str, image_jobs: int, video_jobs: int, concurrency: int, timeout: float) -> List[Job]:
    specs = [("image", idx) for idx in range(1, image_jobs + 1)]
    specs.extend(("video", idx) for idx in range(1, video_jobs + 1))
    if not specs:
        return []

    jobs: List[Job] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(submit_job, base_url, kind, idx, timeout) for kind, idx in specs]
        for future in as_completed(futures):
            jobs.append(future.result())
    return jobs


def poll_jobs(jobs: List[Job], interval: float, max_wait: float, timeout: float) -> int:
    pending = {job.job_id: job for job in jobs}
    started = time.monotonic()
    last_status: Dict[str, str] = {}

    while pending:
        if time.monotonic() - started > max_wait:
            print("Polling timed out.")
            for job in pending.values():
                print(f"{job.kind.upper()} {job.index} still pending jobId={job.job_id}")
            return 1

        for job_id, job in list(pending.items()):
            status, data, fetch_ms = get_json(job.status_url, timeout)
            if status != 200:
                print(f"{job.kind.upper()} {job.index} status HTTP {status} in {fetch_ms}ms: {data}")
                continue

            state = data.get("status", "unknown")
            progress = data.get("progressPct")
            marker = f"{state}:{progress}"
            if last_status.get(job_id) != marker:
                print(f"{job.kind.upper()} {job.index} status={state} progress={progress} jobId={job_id}")
                last_status[job_id] = marker

            if state in TERMINAL_STATUSES:
                elapsed = elapsed_ms(started)
                if state == "completed":
                    result = data.get("images") or data.get("videoUrl")
                    print(f"{job.kind.upper()} {job.index} completed in {elapsed}ms result={result}")
                else:
                    print(f"{job.kind.upper()} {job.index} failed in {elapsed}ms error={data.get('error')}")
                del pending[job_id]

        if pending:
            time.sleep(interval)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit concurrent async image/video jobs through the backend WAS.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="Backend base URL")
    parser.add_argument("--image-jobs", type=int, default=3, help="Number of image jobs to enqueue")
    parser.add_argument("--video-jobs", type=int, default=3, help="Number of video jobs to enqueue")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent enqueue request workers")
    parser.add_argument("--poll", action="store_true", help="Poll backend status endpoints until terminal status")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval seconds")
    parser.add_argument("--max-wait", type=float, default=120.0, help="Max polling wait seconds")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP request timeout seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    jobs = submit_jobs(
        base_url=base_url,
        image_jobs=args.image_jobs,
        video_jobs=args.video_jobs,
        concurrency=args.concurrency,
        timeout=args.timeout,
    )

    print(f"Submitted {len(jobs)} jobs.")
    if not args.poll:
        return 0
    return poll_jobs(jobs, args.poll_interval, args.max_wait, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
