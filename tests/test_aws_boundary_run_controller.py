import os
import signal
import subprocess
import textwrap
import time
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_aws_boundary_validation.sh"


def _run_sourced(
    body: str, tmp_path: Path, *, timeout: float = 10, session: bool = False
) -> subprocess.CompletedProcess[str]:
    trace = tmp_path / "trace"
    command = textwrap.dedent(
        f"""
        set -Eeuo pipefail
        source {SCRIPT}
        aws_cli() {{ printf 'aws %s\\n' "$*" >> "$TRACE"; }}
        docker_cli() {{ printf 'docker %s\\n' "$*" >> "$TRACE"; }}
        {body}
        """
    )
    return subprocess.run(
        ["setsid", "bash", "-c", command] if session else ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "TRACE": str(trace),
            "AWS_PROFILE": "tehsil-sandbox",
            "AWS_REGION": "eu-central-1",
            "AWS_BOUNDARY_CONTROLLER_SESSION": "1" if session else "",
        },
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_controller_has_bounded_private_cleanup_contract() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "infra/template.yaml").read_text(encoding="utf-8")
    for fragment in (
        "set -Eeuo pipefail",
        "umask 077",
        'EXPECTED_PROFILE="tehsil-sandbox"',
        'EXPECTED_REGION="eu-central-1"',
        "trap finish EXIT",
        "trap 'exit 124' INT TERM",
        "Project=tehsil-agent",
        "Purpose=aws-boundary-validation",
        "--cleanup-only",
        "--preflight-only",
        "--metric-timeout-seconds 900",
        "delete-repository --repository-name",
        "--force",
        "wait stack-delete-complete",
    ):
        assert fragment in source
    assert "get-login-password" in source
    assert "--password-stdin" in source
    for fragment in (
        'LogGroupName: !Sub "/tehsil/validation/${AWS::StackName}/flow"',
        'ClusterName: !Sub "${AWS::StackName}-probe"',
        'LogGroupName: !Sub "/tehsil/validation/${AWS::StackName}/probe"',
    ):
        assert fragment in template


def test_probe_failure_still_runs_cleanup(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        preflight() { :; }
        select_docker_command() { :; }
        publish_image() { :; }
        deploy_stack() { :; }
        run_controlled_probe() { return 7; }
        stack_count() { printf '0\\n'; }
        repository_count() { printf '0\\n'; }
        delete_owned_stack() { printf 'stack-delete\\n' >> "$TRACE"; }
        delete_owned_repo() { printf 'repo-delete\\n' >> "$TRACE"; }
        audit_absence() { printf 'audit\\n' >> "$TRACE"; }
        write_run_summary() { :; }
        main
        """,
        tmp_path,
    )
    assert completed.returncode != 0
    assert (tmp_path / "trace").read_text(encoding="utf-8").splitlines()[-3:] == [
        "stack-delete",
        "repo-delete",
        "audit",
    ]


def test_success_runs_both_probes_then_cleanup(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        preflight() { :; }
        select_docker_command() { :; }
        publish_image() { printf 'image\\n' >> "$TRACE"; }
        deploy_stack() { printf 'stack\\n' >> "$TRACE"; }
        run_controlled_probe() { printf 'controlled\\n' >> "$TRACE"; }
        run_sqs_probe() { printf 'sqs\\n' >> "$TRACE"; }
        stack_count() { printf '0\\n'; }
        repository_count() { printf '0\\n'; }
        delete_owned_stack() { printf 'stack-delete\\n' >> "$TRACE"; }
        delete_owned_repo() { printf 'repo-delete\\n' >> "$TRACE"; }
        audit_absence() { printf 'audit\\n' >> "$TRACE"; }
        write_run_summary() { :; }
        main
        """,
        tmp_path,
    )
    assert completed.returncode == 0
    assert (tmp_path / "trace").read_text(encoding="utf-8").splitlines() == [
        "image",
        "stack",
        "controlled",
        "sqs",
        "stack-delete",
        "repo-delete",
        "audit",
    ]


def test_image_publication_uses_substituted_commands_without_printing_registry(
    tmp_path: Path,
) -> None:
    completed = _run_sourced(
        """
        aws_cli() {
          printf 'aws %s %s\\n' "$1" "$2" >> "$TRACE"
          case "$1 $2" in
            "ecr create-repository") printf 'private-registry.example/repository\\n' ;;
            "ecr get-login-password") printf 'temporary-password\\n' ;;
            "ecr describe-images")
              printf 'sha256:%s\\n' \
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
              ;;
          esac
        }
        docker_cli() { printf 'docker %s\\n' "$1" >> "$TRACE"; cat >/dev/null || true; }
        publish_image
        """,
        tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert "private-registry.example" not in completed.stdout
    assert "temporary-password" not in completed.stdout
    trace = (tmp_path / "trace").read_text(encoding="utf-8").splitlines()
    assert trace[0] == "aws ecr create-repository"
    # Unordered, because these two race and nothing can make them not race:
    # `aws_cli ecr get-login-password | docker_cli login` is a pipeline, and
    # bash runs both sides concurrently in subshells that both append to
    # $TRACE. Measured at ~21% reversed over 400 runs, which is a fifth of all
    # CI runs failing on a blocking check for no reason.
    #
    # The pipe stays. Piping the token to --password-stdin is exactly what
    # keeps it out of the process table and shell history, which is the
    # property the two stdout assertions above exist to protect. Asserting an
    # order the shell never promised is the test's mistake, not the script's.
    assert sorted(trace[1:3]) == ["aws ecr get-login-password", "docker login"]
    assert trace[3:] == [
        "docker build",
        "docker tag",
        "docker push",
        "aws ecr describe-images",
    ]


def test_image_publication_hides_registry_on_docker_tag_failure(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        aws_cli() {
          case "$1 $2" in
            "ecr create-repository") printf 'private-registry.example/repository\n' ;;
            "ecr get-login-password") printf 'temporary-password\n' ;;
          esac
        }
        docker_cli() {
          case "$1" in
            login) cat >/dev/null ;;
            tag)
              printf 'docker tag failed: %s\n' "$*" >&2
              return 7
              ;;
          esac
        }
        publish_image
        """,
        tmp_path,
    )
    assert completed.returncode != 0
    assert "private-registry.example" not in completed.stdout
    assert "private-registry.example" not in completed.stderr
    assert "temporary-password" not in completed.stdout
    assert "temporary-password" not in completed.stderr


def test_sigterm_still_runs_cleanup(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    command = textwrap.dedent(
        f"""
        set -Eeuo pipefail
        source {SCRIPT}
        preflight() {{ :; }}
        select_docker_command() {{ :; }}
        publish_image() {{ :; }}
        deploy_stack() {{ :; }}
        run_controlled_probe() {{ printf 'controlled-start\\n' >> "$TRACE"; sleep 30; }}
        stack_count() {{ printf '0\\n'; }}
        repository_count() {{ printf '0\\n'; }}
        delete_owned_stack() {{ printf 'stack-delete\\n' >> "$TRACE"; }}
        delete_owned_repo() {{ printf 'repo-delete\\n' >> "$TRACE"; }}
        audit_absence() {{ printf 'audit\\n' >> "$TRACE"; }}
        write_run_summary() {{ :; }}
        main
        """
    )
    process = subprocess.Popen(
        ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "TRACE": str(trace),
            "AWS_PROFILE": "tehsil-sandbox",
            "AWS_REGION": "eu-central-1",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if trace.exists() and "controlled-start" in trace.read_text(encoding="utf-8"):
            break
        time.sleep(0.01)
    else:
        process.kill()
        raise AssertionError("controller did not reach the probe")
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=10)
    assert process.returncode != 0
    assert trace.read_text(encoding="utf-8").splitlines()[-3:] == [
        "stack-delete",
        "repo-delete",
        "audit",
    ]


def test_run_deadline_terminates_probe_then_cleans_up(tmp_path: Path) -> None:
    started_at = time.monotonic()
    completed = _run_sourced(
        """
        preflight() { :; }
        select_docker_command() { :; }
        publish_image() { :; }
        deploy_stack() { :; }
        run_controlled_probe() { printf 'controlled-start\\n' >> "$TRACE"; sleep 1; }
        run_sqs_probe() { :; }
        stack_count() { printf '0\\n'; }
        repository_count() { printf '0\\n'; }
        delete_owned_stack() { printf 'stack-delete\\n' >> "$TRACE"; }
        delete_owned_repo() { printf 'repo-delete\\n' >> "$TRACE"; }
        audit_absence() { printf 'audit\\n' >> "$TRACE"; }
        write_run_summary() { :; }
        RUN_TIMEOUT_SECONDS=0.05
        main
        """,
        tmp_path,
        timeout=2,
    )

    assert completed.returncode != 0
    assert time.monotonic() - started_at < 0.5
    assert (tmp_path / "trace").read_text(encoding="utf-8").splitlines()[-3:] == [
        "stack-delete",
        "repo-delete",
        "audit",
    ]


def test_run_deadline_terminates_foreground_publish_then_cleans_up(tmp_path: Path) -> None:
    started_at = time.monotonic()
    completed = _run_sourced(
        """
        preflight() { :; }
        select_docker_command() { :; }
        publish_image() { printf 'publish-start\\n' >> "$TRACE"; sleep 1; }
        deploy_stack() { :; }
        run_controlled_probe() { :; }
        run_sqs_probe() { :; }
        stack_count() { printf '0\\n'; }
        repository_count() { printf '0\\n'; }
        delete_owned_stack() { printf 'stack-delete\\n' >> "$TRACE"; }
        delete_owned_repo() { printf 'repo-delete\\n' >> "$TRACE"; }
        audit_absence() { printf 'audit\\n' >> "$TRACE"; }
        write_run_summary() { :; }
        RUN_TIMEOUT_SECONDS=0.05
        main
        """,
        tmp_path,
        timeout=2,
        session=True,
    )

    assert completed.returncode != 0
    assert time.monotonic() - started_at < 0.5
    assert (tmp_path / "trace").read_text(encoding="utf-8").splitlines()[-3:] == [
        "stack-delete",
        "repo-delete",
        "audit",
    ]


def test_run_summary_fingerprints_dirty_source(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        git() {
          case "$*" in
            "rev-parse HEAD") printf 'revision\\n' ;;
            "diff --quiet HEAD") return 1 ;;
            "diff --binary HEAD") printf 'change\\n' ;;
          esac
        }
        source_provenance
        """,
        tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == f"revision+dirty:{sha256(b'change\n').hexdigest()}"


def test_cleanup_only_refuses_unowned_resources(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        stack_count() { printf '1\\n'; }
        repository_count() { printf '0\\n'; }
        stack_is_owned() { return 9; }
        delete_owned_stack() { printf 'unexpected-delete\\n' >> "$TRACE"; }
        cleanup_only
        """,
        tmp_path,
    )
    assert completed.returncode != 0
    assert "ownership tags do not match" in completed.stderr
    assert not (tmp_path / "trace").exists()


def test_audit_absence_accumulates_all_predicate_failures(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        stack_count() { printf 'stack\n' >> "$TRACE"; printf '1\n'; }
        repository_count() { printf 'repository\n' >> "$TRACE"; printf '1\n'; }
        aws_cli() { printf 'aws %s\n' "$*" >> "$TRACE"; printf '0\n'; }
        if audit_absence; then
          exit 0
        fi
        exit 9
        """,
        tmp_path,
    )
    assert completed.returncode == 9
    assert (tmp_path / "trace").read_text(encoding="utf-8").splitlines() == [
        "stack",
        "repository",
        "aws ec2 describe-nat-gateways --filter "
        "Name=tag:aws:cloudformation:stack-name,Values=tehsil-phase1-validation "
        "--query length(NatGateways[?State!='deleted']) --output text",
        "aws ec2 describe-vpc-endpoints --filters "
        "Name=tag:aws:cloudformation:stack-name,Values=tehsil-phase1-validation "
        "--query length(VpcEndpoints) --output text",
        "aws ec2 describe-addresses --filters "
        "Name=tag:aws:cloudformation:stack-name,Values=tehsil-phase1-validation "
        "--query length(Addresses) --output text",
        "aws logs describe-log-groups --log-group-name-prefix "
        "/tehsil/validation/tehsil-phase1-validation/ --query length(logGroups) "
        "--output text",
        "aws ecs describe-clusters --clusters tehsil-phase1-validation-probe "
        "--query length(clusters[?status=='ACTIVE']) --output text",
    ]
