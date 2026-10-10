from hybrid_resilience import ToolLoopGuard


def test_different_arguments_are_not_a_loop():
    guard=ToolLoopGuard(limit=3)
    for index in range(20):
        assert not guard.blocked('computer:computer_click',{'x':index,'y':20})


def test_duplicate_mutations_cool_down_without_permanent_lockout():
    clock=[0.0]
    guard=ToolLoopGuard(limit=3,window=60,clock=lambda:clock[0])
    for _ in range(3):assert not guard.blocked('computer:computer_type',{'text':'private text'})
    assert guard.blocked('computer:computer_type',{'text':'private text'})
    assert not guard.blocked('computer:computer_type',{'text':'different text'})
    assert 'private text' not in repr(guard.calls)
    clock[0]=61
    assert not guard.blocked('computer:computer_type',{'text':'private text'})


def test_monitoring_does_not_trip_guard():
    guard=ToolLoopGuard(limit=3)
    for _ in range(50):
        assert not guard.blocked('worker:api_worker_result',{'worker_id':'one'})
        assert not guard.blocked('computer:computer_screenshot',{})
