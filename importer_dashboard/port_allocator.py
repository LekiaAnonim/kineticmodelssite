"""
Dynamic port allocation for import jobs' web interfaces.

Each running importChemkin.py serves a CherryPy UI on its own port, which
nginx exposes at /importer/<port>/. Ports used to be hard-coded in each
import.sh, so two jobs with the same port collided. Now a port is reserved
from IMPORTER_PORT_RANGE when the job actually starts and released when it ends.
"""
import logging
import re
import socket

from django.conf import settings
from django.db import IntegrityError, transaction

from .models import PortReservation

logger = logging.getLogger(__name__)


class NoFreePortError(RuntimeError):
    pass


def _port_range():
    start, end = getattr(settings, 'IMPORTER_PORT_RANGE', (8100, 8999))
    return range(start, end + 1)


def _is_port_free(port):
    """True if nothing on this host is listening on the port (e.g. an orphaned importer)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('0.0.0.0', port))
        except OSError:
            return False
    return True


def reserve_port(job):
    """
    Reserve a free port for `job` and store it on job.port.

    The unique constraint on PortReservation.port arbitrates races between
    workers: if another worker grabs the same port first, the insert fails
    and we move on to the next candidate.
    """
    # Re-starting a job: drop any reservation left over from its last run
    PortReservation.objects.filter(job=job).delete()

    taken = set(PortReservation.objects.values_list('port', flat=True))
    for port in _port_range():
        if port in taken or not _is_port_free(port):
            continue
        try:
            with transaction.atomic():
                PortReservation.objects.create(port=port, job=job)
        except IntegrityError:
            continue  # lost the race for this port
        job.port = port
        job.save(update_fields=['port'])
        logger.info(f"Reserved port {port} for job {job.name}")
        return port

    raise NoFreePortError(
        f"No free importer port in {_port_range().start}-{_port_range().stop - 1}"
    )


def release_port(job):
    deleted, _ = PortReservation.objects.filter(job=job).delete()
    if deleted:
        logger.info(f"Released port {job.port} for job {job.name}")


def release_stale_ports(active_statuses):
    """Free reservations whose job is no longer active (e.g. the worker was killed)."""
    PortReservation.objects.exclude(job__status__in=active_statuses).delete()


def apply_port_to_command(command, port):
    """Replace the --port argument from import.sh with the reserved port, or add one."""
    if re.search(r'--port[\s=]+\d+', command):
        return re.sub(r'--port[\s=]+\d+', f'--port {port}', command)
    return f'{command} --port {port}'
