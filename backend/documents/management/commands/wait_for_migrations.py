import time

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = (
        "Block until all migrations have been applied. Used by the worker so "
        "that only the API container ever runs migrate."
    )

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=120)

    def handle(self, *args, **options):
        deadline = time.monotonic() + options["timeout"]
        while True:
            connection = connections["default"]
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            pending = executor.migration_plan(targets)
            if not pending:
                self.stdout.write(self.style.SUCCESS("schema is up to date"))
                return
            if time.monotonic() >= deadline:
                raise SystemExit(f"timed out waiting for {len(pending)} migration(s)")
            self.stdout.write(f"waiting for {len(pending)} migration(s) to be applied...")
            time.sleep(1)
