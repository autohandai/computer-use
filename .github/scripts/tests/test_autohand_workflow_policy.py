"""Keep upstream release/cloud automation separate from the Autohand fork."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
UPSTREAM = "trycua/cua"
GUARD = "github.repository == 'trycua/cua'"
BUILD = "needs.plan.outputs.should_build == 'true'"
PUBLISH = BUILD + " && needs.build.result == 'success'"
RELEASE = (
    "github.event_name != 'release' || "
    "startsWith(github.event.release.tag_name, 'cua-driver-rs-v')"
)
MERGED = "github.event.pull_request.merged == true"
ORIGINAL = {
    "release-please.yml": {"release-please": ""},
    "release-on-merge.yml": {"auto-release": MERGED},
    "nightly-lume.yml": {"plan": "", "build": BUILD, "publish": PUBLISH},
    "nightly-cua-driver.yml": {"plan": "", "build": BUILD, "publish": PUBLISH},
    "ci-py-cli-fleets-wif-smoke.yml": {"smoke": ""},
    "ci-test-models.yml": {"test-all-models": "", "test-summary": "always()"},
    "ci-distro-compat-cua-driver.yml": {
        "resolve-version": RELEASE,
        "distro-smoke": "",
        "distro-compat-summary": "always()",
    },
}


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def expression(value):
    text = str(value or "").strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    return " ".join(text.split())


def scoped_forms(original):
    if not original:
        return {GUARD}
    forms = {f"{GUARD} && ({original})", f"({original}) && {GUARD}"}
    if "||" not in original:
        forms.update({f"{GUARD} && {original}", f"{original} && {GUARD}"})
    return forms


def original_enabled(original, *, event="schedule", tag="", build="true", result="success", merged=True):
    # These are the five existing predicates, not an Actions expression interpreter.
    if original in ("", "always()"):
        return True
    if original == BUILD:
        return build == "true"
    if original == PUBLISH:
        return build == "true" and result == "success"
    if original == RELEASE:
        return event != "release" or tag.startswith("cua-driver-rs-v")
    if original == MERGED:
        return merged
    raise AssertionError(f"Unreviewed workflow predicate: {original}")


def scoped_enabled(condition, repository, **facts):
    for original in ("", "always()", BUILD, PUBLISH, RELEASE, MERGED):
        if condition in scoped_forms(original):
            return repository == UPSTREAM and original_enabled(original, **facts)
    raise AssertionError(f"Unreviewed scoped workflow predicate: {condition}")


@pytest.mark.parametrize("name", ORIGINAL)
def test_every_upstream_job_is_scoped_without_changing_its_existing_predicate(name):
    jobs = workflow(name)["jobs"]
    assert set(jobs) == set(ORIGINAL[name]), "Review the ownership of every executable job"
    invalid = {
        job: expression(jobs[job].get("if"))
        for job, original in ORIGINAL[name].items()
        if expression(jobs[job].get("if")) not in scoped_forms(original)
    }
    assert not invalid, f"Unscoped or changed upstream job conditions in {name}: {invalid}"

    cases = [
        {},
        {"event": "workflow_dispatch"},
        {"build": "false"},
        {"result": "failure"},
        {"merged": False},
        {"event": "release", "tag": "cua-driver-rs-v1.2.3"},
        {"event": "release", "tag": "computer-use-v1.2.3"},
    ]
    for job, original in ORIGINAL[name].items():
        for case in cases:
            previous = original_enabled(original, **case)
            for repository in (UPSTREAM, "autohandai/computer-use", "someone/computer-use"):
                enabled = scoped_enabled(expression(jobs[job].get("if")), repository, **case)
                assert enabled is (previous if repository == UPSTREAM else False)


@pytest.mark.parametrize(
    ("name", "events"),
    [
        ("release-please.yml", {"push", "workflow_dispatch"}),
        ("release-on-merge.yml", {"pull_request"}),
        ("nightly-lume.yml", {"schedule", "workflow_dispatch"}),
        ("nightly-cua-driver.yml", {"schedule", "workflow_dispatch"}),
        ("ci-py-cli-fleets-wif-smoke.yml", {"schedule", "workflow_dispatch"}),
        ("ci-test-models.yml", {"schedule", "workflow_dispatch"}),
        ("ci-distro-compat-cua-driver.yml", {"pull_request", "push", "release", "workflow_dispatch"}),
    ],
)
def test_upstream_event_entrypoints_remain_available(name, events):
    assert set(workflow(name)["on"]) == events


def test_nightly_dependencies_and_publishing_evidence_remain_required():
    for name in ("nightly-lume.yml", "nightly-cua-driver.yml"):
        jobs = workflow(name)["jobs"]
        assert jobs["build"]["needs"] == "plan"
        assert jobs["publish"]["needs"] == ["plan", "build"]
        assert any(step.get("name") == "Verify release visibility and exact assets" for step in jobs["publish"]["steps"])


def test_autohand_product_ci_and_explicit_signing_workflow_remain_enabled():
    product = workflow("ci-autohand-computer-use.yml")
    assert set(product["on"]) == {"pull_request", "push"}
    host = product["jobs"]["macos-host"]
    assert not host.get("if")
    assert any(step.get("run") == "./autohand/tests/test-macos-host.sh" for step in host["steps"])

    release = workflow("release-autohand-computer-use.yml")
    assert set(release["on"]) == {"workflow_dispatch"}
    assert release["on"]["workflow_dispatch"]["inputs"]["publish"]["default"] == "false"
    signing = release["jobs"]["notarize"]
    assert not signing.get("if")
    steps = {step.get("name"): step for step in signing["steps"] if "name" in step}
    credentials = steps["Import Autohand Developer ID and notarization credentials"]
    assert set(credentials["env"]) == {
        "CSC_LINK", "CSC_KEY_PASSWORD", "APPLE_TEAM_ID", "APPLE_API_KEY", "APPLE_API_KEY_ID", "APPLE_API_ISSUER"
    }
    assert credentials["run"] == "bash autohand/scripts/import-apple-signing.sh"
    assert steps["Sign and notarize the complete native distribution"]["run"].startswith("python3 autohand/scripts/sign-macos-distribution.py")
    assert steps["Publish an immutable signed revision"]["if"] == "inputs.publish"


def test_generic_attribution_and_release_metadata_checks_are_not_scoped_to_upstream():
    attribution = workflow("ci-contributor-attribution.yml")
    assert "pull_request_target" in attribution["on"]
    job = attribution["jobs"]["contributor-attribution"]
    assert not job.get("if")
    assert any("release_attribution.py validate-pr" in step.get("run", "") for step in job["steps"])
    metadata = workflow("ci-release-metadata.yml")
    assert metadata["jobs"]["validate"]["if"] == "always()"
    assert not metadata["jobs"]["installer-compatibility"].get("if")


def test_model_summary_reads_current_run_artifacts_without_a_matrix_context():
    summary = workflow("ci-test-models.yml")["jobs"]["test-summary"]
    downloads = [step for step in summary["steps"] if step.get("uses", "").startswith("actions/download-artifact@")]
    assert len(downloads) == 1
    assert downloads[0]["with"]["pattern"] == "test-summary-*"
    assert not {"run-id", "repository", "github-token"}.intersection(downloads[0]["with"])
    assert "matrix.model" not in str(summary)
