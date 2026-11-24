"""No expensive rebuild is bypassed unless all approved inputs match."""
from scripts import plan_freerdp_wasm_build as plan


def test_current_verified_inputs_reuse_but_manual_dispatch_rebuilds():
    assert not plan.needs_rebuild(plan.ROOT)
    assert plan.needs_rebuild(plan.ROOT, manual=True)


def test_every_input_and_compile_recipe_drift_requires_rebuild(tmp_path):
    workflow = tmp_path / plan.WORKFLOW
    workflow.parent.mkdir(parents=True)
    original = (plan.ROOT / plan.WORKFLOW).read_bytes()
    workflow.write_bytes(original)
    for relative in plan.PINS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((plan.ROOT / relative).read_bytes())
    assert not plan.needs_rebuild(tmp_path)
    for relative in plan.PINS:
        path = tmp_path / relative
        data = path.read_bytes()
        path.write_bytes(data + b"changed")
        assert plan.needs_rebuild(tmp_path), relative
        path.write_bytes(data)
    workflow.write_bytes(original.replace(b"./scripts/emscripten.sh --with-tests", b"./scripts/emscripten.sh"))
    assert plan.needs_rebuild(tmp_path)
    workflow.write_bytes(original)
    (tmp_path / next(iter(plan.PINS))).unlink()
    assert plan.needs_rebuild(tmp_path)
