"""bot_service 单实例锁测试（用真实的仓库根 data/bot.lock，测试结束清理）"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _lock_path() -> str:
    """真实锁文件路径：仓库根 data/bot.lock（与 bot_service._acquire_single_instance_lock 一致）"""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/tests -> backend
    project_root = os.path.dirname(backend_dir)  # 仓库根
    return os.path.join(project_root, "data", "bot.lock")


@pytest.fixture
def fresh_lock_file():
    """测试前后清理锁文件，确保测试隔离"""
    path = _lock_path()
    if os.path.exists(path):
        os.remove(path)
    yield path
    # 收尾：清理
    try:
        os.remove(path)
    except OSError:
        pass


class TestSingleInstanceLock:
    def test_first_acquire_returns_fd(self, fresh_lock_file):
        import bot_service
        fd = bot_service._acquire_single_instance_lock()
        try:
            assert isinstance(fd, int) and fd >= 0
            assert os.path.exists(fresh_lock_file)
            # 锁文件应记录当前 PID（用 fd 自身读取；Windows 下锁定区域无法用新句柄打开读取）
            os.lseek(fd, 0, os.SEEK_SET)
            content = os.read(fd, 256).decode("utf-8")
            assert str(os.getpid()) in content
        finally:
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            os.close(fd)

    def test_second_acquire_raises_systemexit(self, fresh_lock_file):
        """重复启动应被拦截，抛 SystemExit(2)"""
        import bot_service
        fd1 = bot_service._acquire_single_instance_lock()
        try:
            with pytest.raises(SystemExit) as exc_info:
                bot_service._acquire_single_instance_lock()
            assert exc_info.value.code == 2
        finally:
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(fd1, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            os.close(fd1)