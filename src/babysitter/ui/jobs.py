"""One background job at a time.

A burst of clicks used to start a second Qt thread and drop the first.
Qt closes the whole program if a thread is destroyed while it is still running.
"""

from __future__ import annotations


def take_turn(busy: bool) -> str:
    """'start' when nothing is running. 'wait' when a burst should keep the newest request."""
    return "wait" if busy else "start"


def retain_until_finished(job, held: list) -> None:
    """Keep a Qt thread referenced until its finished signal."""
    if job in held:
        return
    held.append(job)

    def release() -> None:
        try:
            held.remove(job)
        except ValueError:
            pass

    job.finished.connect(release)
