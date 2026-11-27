"""Only the current independently re-proven compile recipe and pinned bytes may reuse WASM."""
from scripts import plan_freerdp_wasm_build as plan


VERIFIED_RECIPE_SHA256 = "ee2d166fc21f366119374da9698d003ddc3c7f4fb3ac694184646c57b6fc547d"
PREVIOUS_RECIPE_SHA256 = "8abeb743dba723f5dba1e00fb2a498703ca904a72a4a667050950ef710b393e6"


def test_current_verified_inputs_reuse_but_manual_dispatch_rebuilds():
    workflow = (plan.ROOT / plan.WORKFLOW).read_text()
    assert plan.digest(plan.build_recipe(workflow).encode()) == VERIFIED_RECIPE_SHA256
    assert VERIFIED_RECIPE_SHA256 == plan.RECIPE_SHA256
    assert not plan.needs_rebuild(plan.ROOT)
    assert plan.needs_rebuild(plan.ROOT, manual=True)


def test_every_input_and_compile_recipe_drift_requires_rebuild(tmp_path):
    workflow = tmp_path / plan.WORKFLOW
    workflow.parent.mkdir(parents=True)
    original = (plan.ROOT / plan.WORKFLOW).read_text()
    workflow.write_text(original)
    for relative in plan.PINS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((plan.ROOT / relative).read_bytes())
    assert not plan.needs_rebuild(tmp_path)
    assert plan.needs_rebuild(tmp_path, manual=True)
    for relative in plan.PINS:
        path = tmp_path / relative
        data = path.read_bytes()
        path.write_bytes(data + b"changed")
        assert plan.needs_rebuild(tmp_path), relative
        path.write_bytes(data)
    for changed in (
        original.replace("./scripts/emscripten.sh --with-tests", "./scripts/emscripten.sh"),
        original.replace("container: emscripten/emsdk:6.0.12", "container: emscripten/emsdk:changed"),
        original.replace("actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4", "actions/checkout@v4"),
    ):
        assert changed != original
        workflow.write_text(changed)
        assert plan.needs_rebuild(tmp_path)
    previous = original.replace(
        "      - name: Checkout PlanIQ browser pilot\n"
        "        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4\n"
        "        with:\n          persist-credentials: false",
        "      - name: Checkout PlanIQ browser pilot\n        uses: actions/checkout@v4",
    )
    previous = previous.replace("uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4", "uses: actions/checkout@v4")
    previous = previous.replace("uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4", "uses: actions/upload-artifact@v4")
    previous = previous.replace("uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4", "uses: actions/download-artifact@v4")
    assert plan.digest(plan.build_recipe(previous).encode()) == PREVIOUS_RECIPE_SHA256
    workflow.write_text(previous)
    assert plan.needs_rebuild(tmp_path)
    workflow.write_text(original)
    (tmp_path / next(iter(plan.PINS))).unlink()
    assert plan.needs_rebuild(tmp_path)


def test_workflow_action_references_are_immutable():
    import re

    for workflow in sorted((plan.ROOT / ".github" / "workflows").glob("*.yml")):
        for line in workflow.read_text().splitlines():
            match = re.match(r"\s*(?:-\s+)?uses:\s+([^\s#]+)", line)
            if not match:
                continue
            reference = match.group(1)
            if reference.startswith("./"):
                continue
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference), (workflow.name, reference)
