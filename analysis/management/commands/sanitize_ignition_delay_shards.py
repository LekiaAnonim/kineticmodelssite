from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analysis.services import sanitize_shard_csvs


class Command(BaseCommand):
    help = (
        'Sanitize ignition-delay shard CSVs by collapsing multi-line '
        'Cantera error tracebacks into single-line summaries. '
        'Safe to run repeatedly while Slurm tasks are still writing shards.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--input-dir',
            default='analysis/run_results/adversarial_idt',
            help='Base directory containing run-label subdirectories.',
        )
        parser.add_argument(
            '--run-label',
            required=True,
            help='Run subdirectory to sanitize.',
        )

    def handle(self, *args, **options):
        input_dir = Path(options['input_dir']).expanduser().resolve()
        run_dir = input_dir / options['run_label']

        if not run_dir.exists():
            raise CommandError(f'Run directory does not exist: {run_dir}')

        self.stdout.write(f'Sanitizing shard CSVs in {run_dir} ...')

        stats = sanitize_shard_csvs(run_dir)

        if stats['rows_sanitized']:
            self.stdout.write(
                self.style.WARNING(
                    f'Sanitized {stats["rows_sanitized"]} multi-line error '
                    f'fields across {stats["shards_processed"]} shards.'
                )
            )
            for name, count in sorted(stats['shard_details'].items()):
                if count:
                    self.stdout.write(f'  {name}: {count}')
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'All {stats["shards_processed"]} shards already clean.'
                )
            )
