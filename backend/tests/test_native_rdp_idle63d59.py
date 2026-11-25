"""Server monotonic idle policy; no real transport or host mutations."""
from service1.routers.remote_desktop_v2 import NativeIdle, NATIVE_IDLE_SECONDS


def test_warning_and_exact_deadline():
    idle = NativeIdle("generation", 600)
    assert idle.next_check() == 540
    assert not idle.expired(599.999)
    assert idle.expired(600)
    idle.warned = True
    assert idle.next_check() == 600


def test_only_current_unexpired_generation_can_reset():
    idle = NativeIdle("generation", 600, warned=True)
    assert not idle.touch("old", 550)
    assert idle.deadline == 600 and idle.warned
    assert idle.touch("generation", 550)
    assert idle.deadline == 550 + NATIVE_IDLE_SECONDS
    assert not idle.warned
    assert not idle.touch("generation", 1150)
    assert idle.expired(1150)
