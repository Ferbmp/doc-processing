from django.core.management.base import BaseCommand

from documents.services.processing import recover_stale_jobs


class Command(BaseCommand):
    help = (
        "Requeue jobs abandoned by workers that died mid-attempt. The worker "
        "loop already does this periodically; this command exists for manual "
        "intervention and for demonstrating crash recovery."
    )

    def add_arguments(self, parser):
        parser.add_argument("--worker-id", default="reaper")
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        recovered = recover_stale_jobs(
            worker_id=options["worker_id"], limit=options["limit"]
        )
        self.stdout.write(self.style.SUCCESS(f"recovered {recovered} stale job(s)"))
