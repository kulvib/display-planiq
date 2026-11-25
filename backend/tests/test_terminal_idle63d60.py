from service1.routers.terminal import TerminalDeadline


def test_standard_terminal_idle_resets_but_never_extends_hard_limit():
    deadline = TerminalDeadline("session", 600, 1800)
    assert deadline.next_check() == 540
    deadline.warned = True
    assert deadline.touch(550)
    assert deadline.deadline == 1150 and not deadline.warned
    assert deadline.touch(1100)
    assert deadline.touch(1650)
    assert deadline.deadline == 1800 and deadline.reason == "limit"
    assert not deadline.touch(1800)


def test_admin_terminal_limit_never_renewed():
    deadline = TerminalDeadline("root", 600, 599)
    assert deadline.next_check() == 539
    assert deadline.reason == "limit"
    deadline.warned = True
    assert deadline.touch(550)
    assert deadline.deadline == 599 and deadline.warned
    assert not deadline.touch(599)
