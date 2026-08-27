"""The worker.

Run one pass with ``--once`` (used by the tests) or stay resident with
``--loop`` (used by the docker compose ``worker`` service). Multiple instances
are safe to run at the same time; job claiming uses SKIP LOCKED.
"""

import logging
import os
import signal
import socket
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from documents.services.processing import (
    execute_job,
    fail_job_with_unexpected_error,
    recover_stale_jobs,
)
from documents.services.queue import claim_next_job

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Claim and execute queued document extraction jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop", action="store_true", help="Keep polling until interrupted."
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Drain everything currently due, then exit (default).",
        )
        parser.add_argument("--worker-id", default="")
        parser.add_argument(
            "--max-jobs", type=int, default=0, help="Stop after N jobs (0 = unlimited)."
        )
        parser.add_argument(
            "--no-sleep",
            action="store_true",
            help="Skip the simulated extraction latency.",
        )

    def handle(self, *args, **options):
        worker_id = options["worker_id"] or f"{socket.gethostname()}:{os.getpid()}"
        poll_interval = float(settings.PROCESSING["WORKER_POLL_INTERVAL_SECONDS"])
        stale_check_interval = max(
            5.0, float(settings.PROCESSING["STALE_JOB_TIMEOUT_SECONDS"]) / 2
        )
        sleep_for_latency = not options["no_sleep"]
        max_jobs = options["max_jobs"]
        loop = options["loop"]

        self._shutting_down = False
        if loop:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self._request_shutdown)

        self.stdout.write(
            self.style.SUCCESS(
                f"worker {worker_id} started ({'loop' if loop else 'single pass'} mode)"
            )
        )

        processed = 0
        next_stale_check = 0.0

        while True:
            if self._shutting_down:
                self.stdout.write("shutdown requested, exiting cleanly")
                break

            if time.monotonic() >= next_stale_check:
                try:
                    recovered = recover_stale_jobs(worker_id=worker_id)
                    if recovered:
                        self.stdout.write(f"recovered {recovered} stale job(s)")
                except Exception:
                    logger.exception("stale job recovery failed")
                next_stale_check = time.monotonic() + stale_check_interval

            job = claim_next_job(worker_id)

            if job is None:
                if not loop:
                    break
                time.sleep(poll_interval)
                close_old_connections()
                continue

            outcome = self._run(job, worker_id, sleep_for_latency)
            processed += 1
            self.stdout.write(
                f"doc={job.document_id} job={job.pk} attempt={job.attempt} -> {outcome}"
            )

            if max_jobs and processed >= max_jobs:
                break

        self.stdout.write(self.style.SUCCESS(f"worker {worker_id} processed {processed} job(s)"))

    def _run(self, job, worker_id, sleep_for_latency):
        try:
            return execute_job(job, worker_id=worker_id, sleep=sleep_for_latency)
        except Exception as exc:  # noqa: BLE001 - a bug must not wedge the queue
            logger.exception("unexpected failure on job %s", job.pk)
            try:
                return fail_job_with_unexpected_error(job, exc, worker_id=worker_id)
            except Exception:
                # Leave the job RUNNING; the stale job reaper will recover it.
                logger.exception("could not record failure for job %s", job.pk)
                return "error"

    def _request_shutdown(self, *_args):
        self._shutting_down = True
