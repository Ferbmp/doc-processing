import time

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Block until the default database accepts connections."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, *args, **options):
        deadline = time.monotonic() + options["timeout"]
        while True:
            try:
                connections["default"].cursor().close()
            except OperationalError as exc:
                if time.monotonic() >= deadline:
                    raise
                self.stdout.write(f"database not ready ({exc.__class__.__name__}), waiting...")
                time.sleep(1)
            else:
                self.stdout.write(self.style.SUCCESS("database is ready"))
                return
