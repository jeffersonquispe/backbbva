from src.application.ports.backup_task_dispatcher_port import BackupTaskDispatcher
from src.infrastructure.queues.celery.app import app


class CeleryBackupTaskDispatcher(BackupTaskDispatcher):
    def dispatch(self, backup_id: str) -> None:
        app.send_task("backups.create", args=[backup_id])
