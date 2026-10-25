"""Static shape assertions for infra/template.yaml (Task 17).

No AWS API calls: this loads the template file and asserts on its parsed
structure only. Tasks 4/5 (queue, DLQ, VPC endpoints, NAT) and Task 16
(GuardDuty malware plan, EvidenceBucket base shape) already have their own
grounding elsewhere in this file's history and are intentionally not
re-asserted here — this module covers only what Task 17 adds.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "infra" / "template.yaml"

_CFN_TAGS = [
    "Ref",
    "Sub",
    "GetAtt",
    "GetAZs",
    "Select",
    "Join",
    "Split",
    "Not",
    "Equals",
    "If",
    "And",
    "Or",
    "Condition",
    "FindInMap",
    "ImportValue",
]


class _CfnLoader(yaml.SafeLoader):
    pass


def _make_cfn_constructor(tag_suffix: str) -> Any:
    key = "Ref" if tag_suffix == "Ref" else f"Fn::{tag_suffix}"

    def _construct(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        if isinstance(node, yaml.ScalarNode):
            value: Any = loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node)
        else:
            value = loader.construct_mapping(node)
        return {key: value}

    return _construct


for _tag in _CFN_TAGS:
    _CfnLoader.add_constructor(f"!{_tag}", _make_cfn_constructor(_tag))


class Template:
    """Thin read-only wrapper around a parsed CloudFormation document."""

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def resource(self, logical_id: str) -> dict[str, Any]:
        resources = self._body.get("Resources", {})
        assert logical_id in resources, f"{logical_id} is not defined in infra/template.yaml"
        result: dict[str, Any] = resources[logical_id]
        return result

    def all_resources(self) -> list[dict[str, Any]]:
        return list(self._body.get("Resources", {}).values())

    def resource_ids(self) -> list[str]:
        return list(self._body.get("Resources", {}).keys())

    def parameter(self, name: str) -> dict[str, Any]:
        parameters = self._body.get("Parameters", {})
        assert name in parameters, f"{name} is not defined in infra/template.yaml Parameters"
        result: dict[str, Any] = parameters[name]
        return result

    def parameter_ids(self) -> list[str]:
        return list(self._body.get("Parameters", {}).keys())

    def output(self, name: str) -> dict[str, Any]:
        outputs = self._body.get("Outputs", {})
        assert name in outputs, f"{name} is not defined in infra/template.yaml Outputs"
        result: dict[str, Any] = outputs[name]
        return result


@pytest.fixture(scope="module")
def template() -> Template:
    body = yaml.load(TEMPLATE_PATH.read_text(), Loader=_CfnLoader)  # noqa: S506
    return Template(body)


# --- Step 1 examples from the task brief -----------------------------------


def test_worker_has_no_public_ip_and_queue_is_standard(template: Template) -> None:
    worker = template.resource("WorkerService")
    assert (
        worker["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]["AssignPublicIp"]
        == "DISABLED"
    )
    assert not template.resource("ResearchQueue")["Properties"].get("FifoQueue", False)


def test_a_research_message_outlives_a_provenance_check(template: Template) -> None:
    """check_provenance runs inline on the research worker. At SQS's default 30 s
    a long check was redelivered mid-run -- run twice, concurrently, by a second
    worker -- and after maxReceiveCount a message that succeeded could still be
    dead-lettered. _CHECK_BATCH is sized to fit inside this."""
    queue = template.resource("ResearchQueue")["Properties"]
    assert queue["VisibilityTimeout"] == 900
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 3


def test_web_and_worker_have_separate_task_roles(template: Template) -> None:
    web_role = template.resource("WebTaskRole")
    worker_role = template.resource("WorkerTaskRole")
    assert web_role != worker_role


def test_alb_is_https_only(template: Template) -> None:
    listener = template.resource("HttpsListener")
    assert listener["Properties"]["Protocol"] == "HTTPS"


def test_rds_is_private_and_encrypted(template: Template) -> None:
    db = template.resource("Database")
    assert db["Properties"]["PubliclyAccessible"] is False
    assert db["Properties"]["StorageEncrypted"] is True


def test_no_redis_kubernetes_or_graph_resources(template: Template) -> None:
    banned_types = {
        "AWS::ElastiCache::CacheCluster",
        "AWS::EKS::Cluster",
        "AWS::Neptune::DBCluster",
    }
    types = {resource["Type"] for resource in template.all_resources()}
    assert not (types & banned_types)


# --- Region, single-region posture ------------------------------------------


def test_deploy_and_restore_scripts_enforce_eu_central_1() -> None:
    for script in ("scripts/deploy.sh", "scripts/restore_backup.sh"):
        text = Path(script).read_text()
        assert 'AWS_REGION:-}" == "eu-central-1"' in text


def test_deploy_rolls_the_worker_before_the_web_tier() -> None:
    """The consumer must be new before the producer can be, and the wait between
    them is what makes the order real rather than nominal.

    Every queue message in this repo forbids extra fields (pydantic
    extra="forbid"), so an OLD worker cannot parse a NEW message -- it raises,
    consume_once leaves the message on the queue, and after maxReceiveCount it
    dead-letters. ECS rolling deployments run old and new tasks side by side, so
    updating web first opens a window in which every message carrying a new
    field is lost. At VisibilityTimeout 900 x maxReceiveCount 3 the DLQ alarm
    fires up to 45 minutes later, long after deploy.sh and smoke.sh report green.

    This is a property of the message contract, not of any one field, which is
    why it is pinned here rather than noted in the changelog of whoever adds the
    next one.
    """
    text = (TEMPLATE_PATH.parents[1] / "scripts" / "deploy.sh").read_text()
    worker_update = text.index('--service worker --force-new-deployment')
    worker_wait = text.index('services-stable --cluster "$CLUSTER" --services worker')
    web_update = text.index('--service web --force-new-deployment')
    assert worker_update < worker_wait < web_update


@pytest.mark.parametrize("environment", ["test", "production"])
def test_deploy_script_renders_parameter_overrides(environment: str) -> None:
    """Run deploy.sh's own parameter_overrides against the real parameter file.

    A broken renderer here is silent: inside $(...) its failure does not trip
    set -e, so the stack would deploy with CloudFormation's defaults.
    """
    root = TEMPLATE_PATH.parents[1]
    script = (root / "scripts" / "deploy.sh").read_text()
    body = script[script.index("parameter_overrides()") :]
    body = body[: body.index("\n}\n") + 3]
    proc = subprocess.run(  # noqa: S603
        [
            "bash",
            "-c",
            f'set -Eeuo pipefail\n{body}\n'
            f'PARAMETERS_FILE="infra/parameters/{environment}.json"\n'
            "parameter_overrides",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    expected = json.loads(
        (root / "infra" / "parameters" / f"{environment}.json").read_text()
    )
    rendered = proc.stdout.split()
    assert len(rendered) == len(expected)
    for pair, param in zip(rendered, expected, strict=True):
        assert pair.startswith(f"{param['ParameterKey']}=")


# --- RDS: PITR, deletion safety ---------------------------------------------


def test_rds_has_bounded_pitr_retention(template: Template) -> None:
    db = template.resource("Database")
    retention = db["Properties"]["BackupRetentionPeriod"]
    assert 0 < retention <= 35


def test_rds_uses_secrets_manager_managed_master_credential(template: Template) -> None:
    db = template.resource("Database")
    assert db["Properties"]["ManageMasterUserPassword"] is True
    # No plaintext MasterUserPassword property anywhere near the managed secret.
    assert "MasterUserPassword" not in db["Properties"]


def test_app_database_role_secrets_are_secrets_manager_generated(template: Template) -> None:
    for logical_id in ("EngineDatabaseSecret", "WebDatabaseSecret", "MigrationDatabaseSecret"):
        secret = template.resource(logical_id)
        assert secret["Type"] == "AWS::SecretsManager::Secret"
        assert "GenerateSecretString" in secret["Properties"]


# --- Evidence bucket (Task 16 -> Task 17 rename/reuse) ----------------------


def test_evidence_bucket_is_versioned(template: Template) -> None:
    bucket = template.resource("EvidenceBucket")
    assert bucket["Properties"]["VersioningConfiguration"]["Status"] == "Enabled"


def test_evidence_bucket_answers_the_browser_upload_cors_check(template: Template) -> None:
    """documents.js POSTs the presigned form to S3 from the dashboard's origin.
    Without a CORS rule S3 stores the object but fetch rejects, so the student
    reads "Upload failed" and every retry mints another DocumentVersion.
    POST only and no credentials: the presigned policy pins key and size, so
    "*" (white-label hosts) admits nothing the policy does not. A multipart
    FormData POST is a simple request, so no headers are allowed."""
    bucket = template.resource("EvidenceBucket")["Properties"]
    assert bucket["CorsConfiguration"] == {
        "CorsRules": [{"AllowedMethods": ["POST"], "AllowedOrigins": ["*"]}]
    }


def test_evidence_bucket_denies_plaintext_http(template: Template) -> None:
    """Student documents and consultation reports must never move over HTTP."""
    policy = template.resource("EvidenceBucketPolicy")
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    deny = [s for s in statements if s["Effect"] == "Deny"]
    assert len(deny) == 1
    assert deny[0]["Condition"] == {"Bool": {"aws:SecureTransport": False}}
    assert deny[0]["Action"] == "s3:*"
    assert deny[0]["Principal"] == "*"


def test_guardduty_scan_scope_matches_document_scan_role_grant(template: Template) -> None:
    """DocumentMalwareProtectionPlan's ObjectPrefixes must actually match the
    key prefix DocumentScanRole is granted s3:GetObject on -- GuardDuty's
    ObjectPrefixes is a literal string-prefix filter, not a glob, so this
    catches the two silently drifting apart again."""
    plan = template.resource("DocumentMalwareProtectionPlan")
    prefixes = plan["Properties"]["ProtectedResource"]["S3Bucket"]["ObjectPrefixes"]
    assert prefixes == ["quarantine/"]

    role = template.resource("DocumentScanRole")
    statements = role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    object_resources: list[str] = []
    for statement in statements:
        for resource in statement["Resource"]:
            if isinstance(resource, dict) and "Fn::Sub" in resource:
                object_resources.append(resource["Fn::Sub"])
    assert object_resources == ["${EvidenceBucket.Arn}/quarantine/*"]

    # No object-level S3 action may be granted against the bare bucket ARN
    # (no key suffix) -- that grant is inert in IAM and was previously
    # redundant with the object-ARN grant above.
    for statement in statements:
        resources = statement["Resource"]
        bucket_arn_only = any(
            resource == {"Fn::GetAtt": "EvidenceBucket.Arn"} for resource in resources
        )
        if bucket_arn_only:
            assert statement["Action"] == ["s3:GetBucketLocation"]


def test_no_second_evidence_or_documents_bucket_was_added(template: Template) -> None:
    bucket_ids = [
        logical_id
        for logical_id, resource in template._body["Resources"].items()
        if resource["Type"] == "AWS::S3::Bucket"
    ]
    assert bucket_ids == ["EvidenceBucket"]


# --- Least-privilege task roles ---------------------------------------------


def _policy_actions(role: dict[str, Any]) -> set[str]:
    actions: set[str] = set()
    for policy in role["Properties"].get("Policies", []):
        for statement in policy["PolicyDocument"]["Statement"]:
            action = statement["Action"]
            actions.update(action if isinstance(action, list) else [action])
    return actions


def test_only_worker_task_role_consumes_the_research_queue(template: Template) -> None:
    worker_actions = _policy_actions(template.resource("WorkerTaskRole"))
    web_actions = _policy_actions(template.resource("WebTaskRole"))
    assert {"sqs:ReceiveMessage", "sqs:DeleteMessage"} <= worker_actions
    assert "sqs:ReceiveMessage" not in web_actions
    assert "sqs:DeleteMessage" not in web_actions


def test_web_task_role_can_enqueue_but_not_write_evidence(template: Template) -> None:
    """Narrowed, not weakened: the web tier signs uploads into quarantine/,
    which is why it holds PutObject there (see
    test_the_web_tier_may_write_an_upload_but_never_read_one). What it must
    never write anywhere else -- tenants/ (the released, approved artefacts)
    above all -- is pinned resource-agnostically via _put_resources, so a
    future statement that widens the resource (e.g. to the whole bucket)
    instead of naming tenants/* explicitly is still caught."""
    web_actions = _policy_actions(template.resource("WebTaskRole"))
    assert "sqs:SendMessage" in web_actions
    assert _put_resources(template.resource("WebTaskRole")) == [
        {"Fn::Sub": "${EvidenceBucket.Arn}/quarantine/*"}
    ]


def test_the_web_tier_can_send_to_every_queue_it_produces_for(template: Template) -> None:
    """Every web-request producer needs its queue here, or the send fails with
    AccessDenied in production only (every test fakes the queue):
    enqueue_research -> ResearchQueue; push.enqueue_work -> MailboxQueue;
    add_application's capture_requirements and /api/documents/generate
    (enqueue_document_work) -> DocumentQueue. Exact set, so a new producer
    or a widened grant both show up here."""
    resources = [
        statement["Resource"]
        for policy in template.resource("WebTaskRole")["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if statement["Action"] == "sqs:SendMessage"
    ]
    assert sorted(r["Fn::GetAtt"] for r in resources) == [
        "DocumentQueue.Arn",
        "MailboxQueue.Arn",
        "ResearchQueue.Arn",
    ]


def test_worker_task_role_can_read_and_write_evidence_bucket(template: Template) -> None:
    worker_actions = _policy_actions(template.resource("WorkerTaskRole"))
    assert {"s3:GetObject", "s3:PutObject"} <= worker_actions


def _mailbox_statements(role: dict[str, Any]) -> list[dict[str, Any]]:
    statements = [
        statement
        for policy in role["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
    ]
    return [
        statement
        for statement in statements
        if "tehsil/mailbox/*" in str(statement.get("Resource", ""))
    ]


def test_the_worker_may_read_rotate_and_delete_mailbox_grants_but_not_create_or_list_them(
    template: Template,
) -> None:
    """The worker's mailbox code paths are the hourly sync (reads a stored
    grant, and overwrites it when the provider rotates it) and the erasure
    sweep (deletes one). Never CreateSecret -- only connect creates a grant,
    and a worker able to recreate one could undo a revoke. ListSecrets cannot
    be resource-scoped, so granting it would grant every tenant's secrets to
    answer a question about one student."""
    mailbox = _mailbox_statements(template.resource("WorkerTaskRole"))
    assert mailbox, "WorkerTaskRole has no statement for tehsil/mailbox/*"
    actions = {action for statement in mailbox for action in statement["Action"]}
    assert actions == {
        "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue",
        "secretsmanager:DeleteSecret",
    }


def test_the_web_tier_may_create_and_delete_mailbox_grants_but_never_read_them(
    template: Template,
) -> None:
    """apps/mailbox/views.py runs under WebTaskRole. callback() creates/writes
    a token (store_refresh_token) and revoke() deletes one
    (delete_student_mailbox_tokens); no view ever reads a stored token, so
    GetSecretValue stays off this statement -- only the worker's sync job
    needs it."""
    mailbox = _mailbox_statements(template.resource("WebTaskRole"))
    assert mailbox, "WebTaskRole has no statement for tehsil/mailbox/*"
    actions = {action for statement in mailbox for action in statement["Action"]}
    assert actions == {
        "secretsmanager:CreateSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:DeleteSecret",
    }
    assert "secretsmanager:GetSecretValue" not in actions
    assert "secretsmanager:ListSecrets" not in actions


# --- ALB / Fargate services --------------------------------------------------


def test_web_service_has_no_public_ip(template: Template) -> None:
    web = template.resource("WebService")
    assert (
        web["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]["AssignPublicIp"]
        == "DISABLED"
    )


def test_web_and_worker_share_the_same_image_parameter(template: Template) -> None:
    web_image = template.resource("WebTaskDefinition")["Properties"]["ContainerDefinitions"][0][
        "Image"
    ]
    worker_image = template.resource("WorkerTaskDefinition")["Properties"][
        "ContainerDefinitions"
    ][0]["Image"]
    assert web_image == worker_image == {"Ref": "AppImage"}


def test_web_and_worker_have_distinct_command_overrides(template: Template) -> None:
    web_command = template.resource("WebTaskDefinition")["Properties"]["ContainerDefinitions"][0][
        "Command"
    ]
    worker_command = template.resource("WorkerTaskDefinition")["Properties"][
        "ContainerDefinitions"
    ][0]["Command"]
    assert web_command != worker_command
    assert "run_research_worker" in worker_command


def test_alb_listener_uses_the_wildcard_certificate(template: Template) -> None:
    listener = template.resource("HttpsListener")
    certificates = listener["Properties"]["Certificates"]
    assert certificates == [{"CertificateArn": {"Ref": "WildcardCertificate"}}]


def test_additional_certificate_arns_attachment_point_exists(template: Template) -> None:
    template.parameter("AdditionalCertificateArns")
    attachment = template.resource("AdditionalCertificateAttachment")
    assert attachment["Type"] == "AWS::ElasticLoadBalancingV2::ListenerCertificate"


# --- Log retention on new log groups ----------------------------------------


@pytest.mark.parametrize("log_group_id", ["WebLogGroup", "WorkerLogGroup", "MigrationLogGroup"])
def test_app_log_groups_have_bounded_retention(template: Template, log_group_id: str) -> None:
    log_group = template.resource(log_group_id)
    assert isinstance(log_group["Properties"]["RetentionInDays"], int)


# --- CloudWatch alarms this task adds ---------------------------------------


@pytest.mark.parametrize(
    "alarm_id",
    [
        "Http5xxAlarm",
        "HttpLatencyAlarm",
        "FailedResearchRateAlarm",
        "StaleEvidenceAlarm",
        "ReviewBacklogAlarm",
        "ModelErrorAlarm",
        "ModelCostAlarm",
        "AuthFailuresAlarm",
        "CrossTenantDenialAlarm",
        "SupportGrantAlarm",
        "ApprovalBypassAlarm",
    ],
)
def test_new_alarms_exist(template: Template, alarm_id: str) -> None:
    alarm = template.resource(alarm_id)
    assert alarm["Type"] == "AWS::CloudWatch::Alarm"


def test_cross_tenant_denial_alarm_watches_the_documented_signals(template: Template) -> None:
    metric_filter = template.resource("CrossTenantDenialMetricFilter")
    pattern = metric_filter["Properties"]["FilterPattern"]
    assert "PublicationBlocked" in pattern
    assert "TenantContextMissing" in pattern


# --- No out-of-scope service families ---------------------------------------


def test_no_payment_or_browser_submission_resources(template: Template) -> None:
    banned_substrings = ("payment", "browsersubmission", "browser-submission")
    for logical_id in template.resource_ids():
        lowered = logical_id.lower()
        assert not any(needle in lowered for needle in banned_substrings), logical_id


def _bootstrap_sql() -> str:
    return (Path(__file__).resolve().parents[2] / "scripts" / "create_runtime_role.sql").read_text()


def _guard_sql() -> str:
    path = Path(__file__).resolve().parents[2] / "scripts" / "create_erasure_guard.sql"
    return path.read_text()


def _bypassrls_grants(sql_text: str) -> list[str]:
    """Lines that grant BYPASSRLS, ignoring comments, RAISE message text and NOBYPASSRLS.

    A RAISE EXCEPTION/NOTICE/WARNING/INFO/LOG message is free text inside a
    single-quoted string, and can *mention* BYPASSRLS -- e.g. bootstrap's own
    refusal message -- without granting it. Only that message literal is
    stripped (handling '' as an escaped quote), never every literal in the
    line: dynamic SQL built with format()/EXECUTE, e.g.
    EXECUTE format('ALTER ROLE %I BYPASSRLS', member), is a real grant hiding
    inside a string literal and must still be caught.
    """
    grants = []
    for line in sql_text.splitlines():
        if line.lstrip().startswith("--"):
            continue
        without_raise_message = re.sub(
            r"(RAISE\s+(?:EXCEPTION|NOTICE|WARNING|INFO|LOG)\s+)'(?:[^']|'')*'",
            r"\1",
            line,
            flags=re.IGNORECASE,
        )
        if re.search(r"(?<!NO)BYPASSRLS", without_raise_message):
            grants.append(line.strip())
    return grants


def test_runtime_role_bootstrap_never_grants_bypassrls() -> None:
    """No role this script touches may bypass RLS, including in passing.

    The substring check this test used to be would not have noticed a real
    grant. The one BYPASSRLS role in the system is created by
    scripts/create_erasure_guard.sql instead, which keeps it out of reach of
    everything bootstrapped here -- in particular the migration role, whose
    membership of it would be one SET ROLE from full cross-tenant read.
    """
    assert _bypassrls_grants(_bootstrap_sql()) == []
    # PG 17 lets only a role that already holds an attribute change it, even to
    # NO, so the bootstrap cannot SET NOBYPASSRLS on runtime_engine/runtime_web
    # -- it can only refuse a role that already has it. Pin that it still
    # checks rolbypassrls (and the sibling attributes) for both runtime roles.
    assert (
        "rolsuper OR rolcreatedb OR rolreplication OR rolbypassrls" in _bootstrap_sql()
    )
    assert "rolname IN ('runtime_engine', 'runtime_web')" in _bootstrap_sql()
    assert "tehsil_erasure_guard" not in _bootstrap_sql()


def test_bypassrls_grants_reads_grants_not_error_messages() -> None:
    """The scanner must still catch a real grant, only ignore mentions of the

    word inside a RAISE message literal (e.g. bootstrap's own refusal text).
    A dynamic grant issued as EXECUTE format(...) is a real grant hiding
    inside a string literal that is not a RAISE message, and must still be
    caught -- stripping every literal, as an earlier version did, made it
    invisible.
    """
    assert _bypassrls_grants("ALTER ROLE x BYPASSRLS;") == ["ALTER ROLE x BYPASSRLS;"]
    assert _bypassrls_grants(
        "EXECUTE format('ALTER ROLE %I BYPASSRLS', member);"
    ) == ["EXECUTE format('ALTER ROLE %I BYPASSRLS', member);"]
    assert (
        _bypassrls_grants(
            "DO $$ BEGIN RAISE EXCEPTION 'a role is BYPASSRLS; remove it'; END $$;"
        )
        == []
    )


def test_only_the_erasure_guard_role_gets_bypassrls() -> None:
    """And it gets it in the one place a human admin runs by hand.

    Under FORCE ROW LEVEL SECURITY nothing else can answer a cross-tenant
    question and GDPR erasure has to ask one, so this role exists. Nothing is a
    member of it, so only a superuser can SET ROLE to it.
    """
    assert _bypassrls_grants(_guard_sql()) == [
        "CREATE ROLE tehsil_erasure_guard NOLOGIN NOINHERIT BYPASSRLS;",
        "NOINHERIT NOREPLICATION BYPASSRLS;",
    ]
    statements = [
        line for line in _guard_sql().splitlines() if not line.lstrip().startswith("--")
    ]
    assert not [line for line in statements if "GRANT tehsil_erasure_guard TO" in line]
    # And says so as an action: an older bootstrap granted that membership, and
    # deleting the GRANT from a file revokes nothing on a database that has it.
    assert any("REVOKE tehsil_erasure_guard FROM" in line for line in statements)


def test_only_the_engine_role_may_call_the_erasure_guard() -> None:
    """Only the worker's execute_due_erasures reaches the EXECUTED transition,
    the one caller of user_has_active_membership. The web role gets nothing."""
    statements = [
        line for line in _guard_sql().splitlines() if not line.lstrip().startswith("--")
    ]
    grants = [line for line in statements if line.startswith("GRANT EXECUTE")]
    assert grants == [
        "GRANT EXECUTE ON FUNCTION public.user_has_active_membership(bigint) TO runtime_engine;"
    ]
    assert not [line for line in statements if "runtime_web" in line or ':"' in line]


def test_no_migration_creates_a_bypassrls_role() -> None:
    """Such a migration passes every local check and fails at deploy.

    Only a role that already has BYPASSRLS may create one (measured: a
    CREATEROLE NOSUPERUSER role gets "permission denied to create role"), and
    the migration role has neither. CI and every developer database migrate as
    a superuser, which can, so nothing here would catch it. BYPASSRLS roles are
    created by an admin script -- scripts/create_erasure_guard.sql.
    """
    root = Path(__file__).resolve().parents[2]
    offenders = [
        str(path.relative_to(root))
        for path in root.glob("apps/*/migrations/*.py")
        if re.search(r"CREATE\s+ROLE[^;]*(?<!NO)BYPASSRLS", path.read_text(), re.IGNORECASE)
    ]
    assert offenders == [], offenders


def test_catalog_grants_migration_creates_runtime_roles_only_as_superuser() -> None:
    """A non-superuser creating the runtime roles would own their ADMIN OPTION.

    On PG16+ only a role holding ADMIN may ALTER another, so if production's
    `tehsil_migration` created them the admin bootstrap could never make them
    logins. `scripts/deploy.sh` runs the migration right after the stack deploy,
    so the first deploy reaches funding/0049 before anyone thinks to bootstrap:
    it must refuse there, before any CREATE ROLE, not create and strand them.
    Measured on PG17 against a NOSUPERUSER CREATEROLE stand-in: refusal, no role
    created, only that migration's transaction rolled back.
    """
    root = Path(__file__).resolve().parents[2]
    sql = (root / "apps/funding/migrations/0049_catalog_grants.py").read_text()
    guard = sql.index("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    assert "WHERE rolname IN ('runtime_engine', 'runtime_web')) < 2" in sql
    assert "run '\n            'scripts/create_runtime_role.sql as the admin role" in sql
    assert guard < sql.index("CREATE ROLE {role} NOLOGIN")


def test_bootstrap_refuses_an_unconstrained_migration_role() -> None:
    """The migration role owns every table, so its attributes decide RLS outcomes.

    A superuser or BYPASSRLS migration role makes tenant isolation a property of
    how the database was bootstrapped rather than of the policies, and it is the
    reason the erasure guard is owned by a dedicated role instead of by the
    table owner. The bootstrap refuses rather than warns.
    """
    assert (
        "WHERE rolname = :'migration_role' AND NOT rolsuper AND NOT rolbypassrls"
        in _bootstrap_sql()
    )


def _object_actions(role: dict[str, Any], resource_sub: str) -> set[str]:
    """Actions the role grants on one !Sub'd object-ARN resource."""
    actions: set[str] = set()
    for policy in role["Properties"].get("Policies", []):
        for statement in policy["PolicyDocument"]["Statement"]:
            resource = statement["Resource"]
            if resource == {"Fn::Sub": resource_sub}:
                action = statement["Action"]
                actions.update(action if isinstance(action, list) else [action])
    return actions


def _put_resources(role: dict[str, Any]) -> list[Any]:
    """Resources (in their original !Sub/!GetAtt/literal shape, deduped) on
    which the role grants any s3:Put* action. Deliberately resource- AND
    action-agnostic: a statement matches on the action prefix alone, so a
    future PutObject grant widened to a bucket-wide resource, or a new
    PutObjectAcl/PutObjectTagging grant on any resource, is still caught --
    not just the one exact (action, resource) pair this template grants
    today."""
    resources: list[Any] = []
    for policy in role["Properties"].get("Policies", []):
        for statement in policy["PolicyDocument"]["Statement"]:
            action = statement["Action"]
            actions = action if isinstance(action, list) else [action]
            if not any(a.startswith("s3:Put") for a in actions):
                continue
            resource = statement["Resource"]
            candidates = resource if isinstance(resource, list) else [resource]
            for candidate in candidates:
                if candidate not in resources:
                    resources.append(candidate)
    return resources


def test_only_worker_task_role_may_erase_tenant_objects(template: Template) -> None:
    """Erasure under a versioned bucket needs DeleteObjectVersion; the web tier
    reads documents and must never be able to delete one."""
    tenant_objects = "${EvidenceBucket.Arn}/tenants/*"
    worker = _object_actions(template.resource("WorkerTaskRole"), tenant_objects)
    assert {"s3:DeleteObject", "s3:DeleteObjectVersion"} <= worker
    assert "s3:ListBucketVersions" in _policy_actions(template.resource("WorkerTaskRole"))

    web_actions = _policy_actions(template.resource("WebTaskRole"))
    assert "s3:DeleteObject" not in web_actions
    assert "s3:DeleteObjectVersion" not in web_actions


def test_only_worker_task_role_may_read_quarantined_uploads(template: Template) -> None:
    """Ingestion (apps/documents/ingestion.py) opens the scanned-clean original
    worker-side; the web tier never READS a quarantined object. It signs
    uploads into that prefix, which is a write."""
    quarantine_objects = "${EvidenceBucket.Arn}/quarantine/*"
    worker = _object_actions(template.resource("WorkerTaskRole"), quarantine_objects)
    # Exact set: erasure's delete belongs here (see the test below), and
    # nothing else may be added to this prefix without failing here first.
    assert worker == {
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:DeleteObject",
        "s3:DeleteObjectVersion",
    }
    assert "s3:GetObject" not in _object_actions(
        template.resource("WebTaskRole"), quarantine_objects
    )
    assert "s3:GetObjectVersion" not in _object_actions(
        template.resource("WebTaskRole"), quarantine_objects
    )


def test_erasure_can_reach_the_students_uploaded_original(template: Template) -> None:
    """GDPR erasure runs advance_deletion -> delete_student_documents, and the
    student's uploaded CV is at quarantine/{tenant}/{document}, not under their
    own tenants/ prefix. WorkerTaskRole is the role that runs it: it is the only
    role in this template holding s3:DeleteObject at all, and the only one with
    the ListBucketVersions that a versioned erasure enumerates with. Without a
    delete on quarantine/* the request completes and is recorded EXECUTED with
    the file still in the bucket.

    The other half is what must NOT have it: the web tier holds no delete
    anywhere, on any resource, so a request-handling process cannot erase.
    """
    worker = _object_actions(
        template.resource("WorkerTaskRole"), "${EvidenceBucket.Arn}/quarantine/*"
    )
    assert {"s3:DeleteObject", "s3:DeleteObjectVersion"} <= worker

    for role_id in ("WebTaskRole", "DocumentWorkerTaskRole", "EuropassWorkerTaskRole"):
        actions = _policy_actions(template.resource(role_id))
        assert not any(action.startswith("s3:Delete") for action in actions), role_id


# --- Europass render pipeline: queue, pinned worker, canary schedule --------


def test_europass_queue_has_a_dead_letter_queue(template: Template) -> None:
    queue = template.resource("EuropassQueue")["Properties"]
    assert queue["KmsMasterKeyId"] == "alias/aws/sqs"
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 3


def test_the_europass_worker_is_pinned_to_one_task(template: Template) -> None:
    """The task count is a RATE knob, not a throughput knob: outbound rate is
    tasks x (1/delay). Scaling this silently multiplies traffic to a public
    EU service, so the count is a literal 1 and not a parameter."""
    service = template.resource("EuropassWorkerService")["Properties"]
    assert service["DesiredCount"] == 1


def test_the_europass_worker_is_never_autoscaled(template: Template) -> None:
    scalable = [
        name
        for name, resource in zip(template.resource_ids(), template.all_resources())
        if resource["Type"] == "AWS::ApplicationAutoScaling::ScalableTarget" and "Europass" in name
    ]
    assert scalable == []


def test_the_europass_worker_is_its_own_service(template: Template) -> None:
    """Not folded into the research worker: scaling that service for research
    throughput would multiply this worker's request rate as a side effect."""
    assert template.resource("EuropassWorkerService")["Type"] == "AWS::ECS::Service"


def test_the_europass_canary_is_scheduled(template: Template) -> None:
    """The spec calls the canary 'the entire early-warning system' for an
    undocumented API. Unscheduled, the first sign europa.eu changed shape
    would be a dead-letter queue full of students' CVs."""
    rules = [
        resource
        for name, resource in zip(template.resource_ids(), template.all_resources())
        if resource["Type"] == "AWS::Events::Rule" and "Canary" in name
    ]
    assert rules, "no EventBridge rule schedules the Europass canary"
    assert any("ScheduleExpression" in rule["Properties"] for rule in rules)


def test_the_calls_metric_filter_matches_what_the_worker_logs(template: Template) -> None:
    """EuropassCallsTotal is the number that makes our volume answerable to
    europa.eu. A filter whose pattern drifts from the worker's log line is a
    metric that silently reads zero, which is worse than no metric."""
    filters = [
        resource["Properties"]
        for name, resource in zip(template.resource_ids(), template.all_resources())
        if resource["Type"] == "AWS::Logs::MetricFilter" and "EuropassCalls" in name
    ]
    assert len(filters) == 1
    assert "EuropassCallMade" in filters[0]["FilterPattern"]
    assert filters[0]["MetricTransformations"][0]["MetricName"] == "EuropassCallsTotal"


def test_alarms_exist_for_the_europass_backlog_and_dlq(template: Template) -> None:
    alarms = {
        name: resource["Properties"]
        for name, resource in zip(template.resource_ids(), template.all_resources())
        if resource["Type"] == "AWS::CloudWatch::Alarm"
    }
    metrics = {name: props["MetricName"] for name, props in alarms.items() if "Europass" in name}
    assert "ApproximateAgeOfOldestMessage" in metrics.values()
    assert "ApproximateNumberOfMessagesVisible" in metrics.values()


# --- Fix report Finding 1 / Ruling F-J ---------------------------------------

#: config/settings/production.py reads each of these via os.environ[...]
#: (or, for DJANGO_SECRET_KEY, the ECS "Secrets" field populating the same
#: container-env namespace) unconditionally at import time -- regardless of
#: which command a task actually runs. A task definition missing one of
#: these KeyErrors before any command logic runs. Named explicitly rather
#: than parsed from production.py: when someone adds a new required setting
#: there, this list must be updated too, and forgetting is exactly the
#: silent-drift failure this test exists to catch.
_PRODUCTION_REQUIRED_ENV_VARS = frozenset(
    {
        "DJANGO_ALLOWED_HOSTS",
        "RESEARCH_QUEUE_URL",
        "EUROPASS_QUEUE_URL",
        "PORTAL_QUEUE_URL",
        "DOCUMENT_QUEUE_URL",
        "DOCUMENT_SCAN_QUEUE_URL",
        "MAILBOX_QUEUE_URL",
        "DJANGO_SECRET_KEY",
        "CACHE_URL",
    }
)


def _container_env_names(task_definition: dict[str, Any]) -> set[str]:
    container = task_definition["Properties"]["ContainerDefinitions"][0]
    names = {entry["Name"] for entry in container.get("Environment", [])}
    names |= {entry["Name"] for entry in container.get("Secrets", [])}
    return names


def _database_role(template: Template, task_definition_id: str) -> str | None:
    """The literal DATABASE_ROLE value a task definition's container carries,
    or None if it sets none (ProbeTaskDefinition, deliberately)."""
    task_definition = template.resource(task_definition_id)
    container = task_definition["Properties"]["ContainerDefinitions"][0]
    for entry in container.get("Environment", []):
        if entry["Name"] == "DATABASE_ROLE":
            value: str = entry["Value"]
            return value
    return None


ROLE_BY_TASK = {
    "WorkerTaskDefinition": "runtime_engine",
    "DocumentWorkerTaskDefinition": "runtime_engine",
    "EuropassWorkerTaskDefinition": "runtime_engine",
    # The same role the sweep syncs as on WorkerTaskDefinition.
    "MailboxWorkerTaskDefinition": "runtime_engine",
    # runtime_web: the portal tier reads no catalogue (2026-09-25 final review
    # I3), and as the engine a renderer-sandbox escape could write the
    # catalogue every tenant reads.
    "PortalTaskDefinition": "runtime_web",
    "WebTaskDefinition": "runtime_web",
    "MigrationTaskDefinition": "migration",
}


@pytest.mark.parametrize("task,role", sorted(ROLE_BY_TASK.items()))
def test_each_task_definition_carries_the_role_its_work_needs(template, task, role) -> None:
    """Getting one wrong is a silent outage (engine work as web) or a silent
    leak (web work as engine), and neither shows on any screen."""
    assert _database_role(template, task) == role


def test_the_retry_rule_stays_disabled(template) -> None:
    """It shipped DISABLED because catalog_ingestion had no login; runtime_engine
    replaces it, so that reason is gone. It stays DISABLED for a different one:
    apps/research/management/commands/retry_due_fetches.py's own docstring says
    a successful retry persists no snapshot, re-runs no reader and closes no
    task -- the caller that originally needed the page still fetches and pays
    for it again. Enabled on a six-hour schedule, that spends vendor credits
    every run for a result nothing downstream receives. Enable when a retry
    hands its delivered page to the caller that needed it."""
    assert template.resource("RetryDueFetchesRule")["Properties"]["State"] == "DISABLED"


def test_probe_task_definition_carries_no_database_role(template: Template) -> None:
    """ProbeTaskDefinition has no DB role at all (task 6 ruling) -- pinned so
    a future edit does not "helpfully" add one."""
    assert _database_role(template, "ProbeTaskDefinition") is None


def test_the_web_execution_role_cannot_read_the_engine_secret(template: Template) -> None:
    """AppExecutionRole (engine tasks) and WebExecutionRole (the web tier) must
    not overlap on the database secret each resolves into a container's
    Secrets entry -- ECS resolves that Secrets ValueFrom through the
    execution role, so sharing one role would let the web task's execution
    role read the runtime_engine password even though runtime_web never
    connects as that role."""

    def _granted_secret_refs(role_id: str) -> set[str]:
        role = template.resource(role_id)
        return {
            resource["Ref"]
            for policy in role["Properties"]["Policies"]
            for statement in policy["PolicyDocument"]["Statement"]
            if statement["Action"] == "secretsmanager:GetSecretValue"
            for resource in statement["Resource"]
            if isinstance(resource, dict) and "Ref" in resource
        }

    web_secrets = _granted_secret_refs("WebExecutionRole")
    engine_secrets = _granted_secret_refs("AppExecutionRole")
    assert "EngineDatabaseSecret" not in web_secrets
    assert "WebDatabaseSecret" in web_secrets
    assert "WebDatabaseSecret" not in engine_secrets
    assert "EngineDatabaseSecret" in engine_secrets
    # The web task's one extra Secrets entry must resolve through the web's
    # execution role; granted only to AppExecutionRole, the web task never
    # starts (master added it there before the split reached it).
    assert "FirecrawlWebhookSecret" in web_secrets
    assert "FirecrawlWebhookSecret" not in engine_secrets
    portal_secrets = _granted_secret_refs("PortalExecutionRole")
    assert "EngineDatabaseSecret" not in portal_secrets
    assert "WebDatabaseSecret" in portal_secrets
    assert "LlmApiKeySecretArn" in portal_secrets
    assert "LlmApiKeySecretArn" not in engine_secrets | web_secrets
    assert template.resource("PortalTaskDefinition")["Properties"]["ExecutionRoleArn"] == {
        "Fn::GetAtt": "PortalExecutionRole.Arn"
    }


@pytest.mark.parametrize(
    "task_definition_id",
    [
        "WebTaskDefinition",
        "WorkerTaskDefinition",
        "MigrationTaskDefinition",
        "EuropassWorkerTaskDefinition",
        "PortalTaskDefinition",
        "DocumentWorkerTaskDefinition",
        "MailboxWorkerTaskDefinition",
    ],
)
def test_app_task_definitions_supply_every_production_required_env_var(
    template: Template, task_definition_id: str
) -> None:
    """Every task definition here sets DJANGO_SETTINGS_MODULE to
    config.settings.production, so all of them must supply every variable
    production.py requires -- this bug survived four task reviews because
    each one only had the diff in front of it; only a structural test that
    checks all task definitions together closes it."""
    task_definition = template.resource(task_definition_id)
    assert _PRODUCTION_REQUIRED_ENV_VARS <= _container_env_names(task_definition)


# --- Fix report Finding 2 / Ruling F-K ---------------------------------------


def test_europass_worker_task_role_can_read_and_write_evidence_bucket(template: Template) -> None:
    """render_and_store's cache-hit read and its final store both go through
    S3ObjectStore against the tenants/ prefix (apps/documents/europass_render.py,
    apps/documents/storage.py) -- without this grant the europa.eu call
    succeeds and the store 403s, and the message gets redelivered at
    europa.eu's expense."""
    actions = _policy_actions(template.resource("EuropassWorkerTaskRole"))
    assert {"s3:GetObject", "s3:PutObject"} <= actions
    assert "s3:DeleteObject" not in actions
    tenant_objects = "${EvidenceBucket.Arn}/tenants/*"
    assert _object_actions(template.resource("EuropassWorkerTaskRole"), tenant_objects) == {
        "s3:GetObject",
        "s3:PutObject",
    }


@pytest.mark.parametrize(
    ("rule_id", "task_definition_id"),
    [
        ("EuropassCanaryRule", "EuropassWorkerTaskDefinition"),
        ("RetryDueFetchesRule", "WorkerTaskDefinition"),
        ("ProvenanceRecheckRule", "WorkerTaskDefinition"),
        ("ExecuteDueErasuresRule", "WorkerTaskDefinition"),
        ("VerifyDueCyclesRule", "WorkerTaskDefinition"),
        ("SyncMailboxesRule", "WorkerTaskDefinition"),
    ],
)
def test_the_canary_input_overrides_the_task_definitions_actual_container_name(
    template: Template, rule_id: str, task_definition_id: str
) -> None:
    """Each scheduled rule's Input hard-codes the container it overrides. If
    that task definition's container is ever renamed, RunTask fails as a
    dropped EventBridge invocation -- with TreatMissingData: notBreaching on
    the alarms reading these log groups, the scheduled job would simply stop
    running with no signal at all, which is exactly the silent failure this
    invariant exists to prevent. Parametrised rather than canary-only: the
    rename is one edit and it drops every rule naming the old name."""
    container_name = template.resource(task_definition_id)["Properties"][
        "ContainerDefinitions"
    ][0]["Name"]
    raw_input = template.resource(rule_id)["Properties"]["Targets"][0]["Input"]
    # Parsed by the loader as an Fn::Sub tag (no ${} substitution present),
    # so unwrap that before parsing the JSON it carries.
    body = raw_input["Fn::Sub"] if isinstance(raw_input, dict) else raw_input
    payload = json.loads(body)
    assert payload["containerOverrides"][0]["name"] == container_name


def test_the_retry_queue_rule_is_scheduled_and_disabled(template: Template) -> None:
    """The login blocker is gone: WorkerTaskDefinition ran as
    DATABASE_ROLE=runtime, and the runtime role held no role membership
    (scripts/create_runtime_role.sql asserted it) while both fetch-engine
    tables were write-restricted to catalog_ingestion (research/0005_fetch_
    engine_rls) -- that made the reschedule UPDATE match zero rows in silence
    and the first fetch die on an RLS violation, and no test in this repo
    could see either because the test role bypasses RLS (CLAUDE.md).
    WorkerTaskDefinition now runs as DATABASE_ROLE=runtime_engine, which is
    catalog_ingestion made real (a LOGIN role holding the DML grant), so that
    failure mode is gone. It stays DISABLED anyway: a successful retry
    delivers its page to nobody (retry_due_fetches.py's own docstring), so
    enabling it on a schedule spends vendor credits for no delivered result.
    See test_the_retry_rule_stays_disabled for the state assertion itself."""
    rule = template.resource("RetryDueFetchesRule")["Properties"]
    assert rule["ScheduleExpression"]
    assert rule["State"] == "DISABLED"


def test_the_events_role_may_run_only_the_scheduled_task_definitions(
    template: Template,
) -> None:
    """One role now invokes two rules, so its scope is the thing that quietly
    widens. A `Resource: "*"` on either statement hands EventBridge RunTask on
    every task definition in the account -- including the portal tier, whose
    task role reaches per-tenant portal credentials -- and PassRole on every
    role, which is RunTask on anything with a role attached."""
    statements = template.resource("EventsInvokeEcsRole")["Properties"]["Policies"][0][
        "PolicyDocument"
    ]["Statement"]
    scope = {statement["Action"]: statement["Resource"] for statement in statements}
    assert scope["ecs:RunTask"] == [
        {"Ref": "EuropassWorkerTaskDefinition"},
        {"Ref": "WorkerTaskDefinition"},
        {"Ref": "DocumentWorkerTaskDefinition"},
    ]
    assert scope["iam:PassRole"] == [
        {"Fn::GetAtt": "AppExecutionRole.Arn"},
        {"Fn::GetAtt": "EuropassWorkerTaskRole.Arn"},
        {"Fn::GetAtt": "WorkerTaskRole.Arn"},
        {"Fn::GetAtt": "DocumentWorkerTaskRole.Arn"},
    ]


def test_the_europass_age_alarm_outlasts_the_whole_retry_envelope(template: Template) -> None:
    """A message that fails twice ages VisibilityTimeout x (maxReceiveCount-1)
    before the DLQ catches it. An alarm tighter than that pages on ordinary
    redelivery, not on a real failure -- which is exactly the mistake this
    threshold invites, since drain time (~3.5 min at ~100 renders/day) looks
    like the governing number and is not."""
    queue = template.resource("EuropassQueue")["Properties"]
    alarm = template.resource("EuropassQueueAgeAlarm")["Properties"]
    legitimate_age = queue["VisibilityTimeout"] * (queue["RedrivePolicy"]["maxReceiveCount"] - 1)
    assert alarm["Threshold"] >= legitimate_age


# --- Browser tier, now deleted (spec 4, owner decision 2026-09-19) ----------
#
# The isolation design this section used to pin (2026-08-26-browser-isolation)
# no longer applies: the research fetch path is vendor-only, so there is no
# Chromium task left to secure. test_the_database_admits_web_worker_and_portal_only
# still guards the group DatabaseSecurityGroup admits; test_no_browser_tier_remains
# below asserts the browser tier's absence instead of its shape.


def _admitted_groups(group: dict[str, Any]) -> list[Any]:
    """Every ingress source, refusing any rule that is not a group reference.

    The refusal is the point. A rule keyed by CidrIp has no
    SourceSecurityGroupId, so collecting sources with .get() yields None for it
    and an assertion about *which groups* are admitted stays green while the
    group sits open to an address range. For the groups this file guards,
    "admitted by CIDR" is never the right answer -- a bastion range, a VPN
    block or an analytics host added to DatabaseSecurityGroup would hand the
    browser task Postgres on 5432, which is the precise thing the browser
    isolation exists to prevent.

    Description is allowed because AWS permits it on a rule and it changes
    nothing about who is admitted.
    """
    allowed_keys = {"IpProtocol", "FromPort", "ToPort", "SourceSecurityGroupId", "Description"}
    sources = []
    for rule in group["SecurityGroupIngress"]:
        assert set(rule) <= allowed_keys, f"ingress rule is not a group reference: {rule}"
        sources.append(rule["SourceSecurityGroupId"])
    return sources


def test_the_database_admits_web_worker_and_portal_only(template: Template) -> None:
    """An exact allowlist, not "the browser is absent".

    The most likely way the isolation gets silently undone is reusing
    WorkerSecurityGroup for the browser task -- it already exists and already
    has the right egress -- and DatabaseSecurityGroup admits that group on
    5432. But asserting only that BrowserSecurityGroup is absent guards one
    spelling of the mistake. Pinning the whole list catches every widening,
    including the CIDR rule that an absence check cannot see at all.

    Task 14 deliberately widens this allowlist to three: PortalSecurityGroup
    is admitted because the portal task reads field maps and writes the
    §5.5 audit trail while it types, so unlike the browser task it cannot be
    credential-free. What makes that acceptable is the renderer sandbox
    (apps/portals/engine.py refuses to run without it) and the EC2 launch
    type that makes the sandbox possible (Fargate cannot give Chrome the
    user namespaces the sandbox needs). BrowserSecurityGroup stays absent --
    that reasoning is unchanged, and this test still fails the instant
    someone adds it.
    """
    assert _admitted_groups(template.resource("DatabaseSecurityGroup")["Properties"]) == [
        {"Ref": "WebSecurityGroup"},
        {"Ref": "WorkerSecurityGroup"},
        {"Ref": "PortalSecurityGroup"},
    ]


def test_the_cache_admits_web_worker_and_portal_only(template: Template) -> None:
    """Same three-group shape as DatabaseSecurityGroup, and the same reasoning:
    WorkerSecurityGroup is shared by worker, europass-worker, document-worker and
    the migration RunTask, so this list already covers all six app task
    definitions. OcrSecurityGroup is never in it -- the OCR function parses
    untrusted uploads and has no route to anything but S3 (audit fix-1 review,
    2026-09-27: a node-based Valkey replication group, cluster mode disabled,
    replaced DatabaseCache as apps/ratelimit.py's shared counter backend)."""
    assert _admitted_groups(template.resource("CacheSecurityGroup")["Properties"]) == [
        {"Ref": "WebSecurityGroup"},
        {"Ref": "WorkerSecurityGroup"},
        {"Ref": "PortalSecurityGroup"},
    ]


def test_the_cache_is_a_node_based_replication_group_not_serverless(template: Template) -> None:
    """N1 (2026-09-27 re-review): AWS documents ElastiCache Serverless as speaking
    only the cluster protocol ("ElastiCache Serverless only supports clients that
    support the Valkey or Redis OSS cluster protocol", AWS ElastiCache
    troubleshooting guide), while Django's built-in RedisCache uses the plain
    non-cluster client. A node-based ReplicationGroup, cluster mode disabled (no
    ClusterMode/NumNodeGroups property -- their presence would mean cluster mode
    enabled), is what that client actually speaks."""
    cache = template.resource("Cache")
    assert cache["Type"] == "AWS::ElastiCache::ReplicationGroup"
    props = cache["Properties"]
    assert props["Engine"] == "valkey"
    assert props["NumCacheClusters"] == 1
    assert "ClusterMode" not in props
    assert "NumNodeGroups" not in props
    assert props["TransitEncryptionEnabled"] is True
    assert props["AtRestEncryptionEnabled"] is True
    assert props["SecurityGroupIds"] == [{"Ref": "CacheSecurityGroup"}]
    assert props["CacheSubnetGroupName"] == {"Ref": "CacheSubnetGroup"}
    assert "CacheUsageLimits" not in props  # that property belongs to ServerlessCache


def test_the_ocr_function_has_no_security_group_path_to_the_cache(template: Template) -> None:
    """OcrSecurityGroup is checked directly, not just absent from the cache's
    ingress list above: this pins that the OCR function's own security group
    carries no rule reaching anywhere but S3 over HTTPS, so it could not reach
    Valkey even if a future edit added it to CacheSecurityGroup's admitted list."""
    ocr_group = template.resource("OcrSecurityGroup")["Properties"]
    assert ocr_group["SecurityGroupEgress"] == [
        {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"}
    ]
    assert "SecurityGroupIngress" not in ocr_group


def test_no_browser_tier_remains(template: Template) -> None:
    """The research path is vendor-only (spec 4, owner decision 2026-09-19), so there
    is no Chromium in this account to secure. The four properties the deleted tests
    pinned — no task role, its own security group, absent from the database group,
    shipped stopped — are all satisfied by the resource not existing.

    Deliberately NOT deleted: the DatabaseSecurityGroup ingress test above. Its
    list is still load-bearing for web, worker and portal.
    """
    assert [name for name in template.resource_ids() if name.startswith("Browser")] == []
    assert [name for name in template.parameter_ids() if name.startswith("Browser")] == []
    worker = template.resource("WorkerTaskDefinition")
    env = worker["Properties"]["ContainerDefinitions"][0].get("Environment", [])
    assert [e for e in env if e["Name"] == "BROWSER_SERVICE_URL"] == []


def test_every_long_running_service_log_group_is_watched(template: Template) -> None:
    """No service ships unmonitored. This is the general form on purpose.

    BrowserLogGroup was added with no metric filter at all -- the browser
    service would have failed every render in silence. A test asserting only
    that one group is watched fixes the instance; this one fixes the class, so
    the next service added has to make the same decision deliberately.

    The exemptions are the three groups that are not long-running services:
    FlowLog is VPC flow records (already a CloudWatch destination, not
    application output), and Probe/Migration are one-off tasks whose failure
    surfaces as a non-zero task exit rather than a log line nobody reads.
    """
    not_a_service = {"FlowLogGroup", "ProbeLogGroup", "MigrationLogGroup"}

    groups = {
        logical_id
        for logical_id in template.resource_ids()
        if template.resource(logical_id)["Type"] == "AWS::Logs::LogGroup"
    }
    watched = {
        template.resource(logical_id)["Properties"]["LogGroupName"]["Ref"]
        for logical_id in template.resource_ids()
        if template.resource(logical_id)["Type"] == "AWS::Logs::MetricFilter"
    }

    assert (groups - not_a_service) <= watched, (
        f"unmonitored service log group(s): {sorted(groups - not_a_service - watched)}"
    )


def test_the_database_major_matches_the_postgres_the_tests_run_on(template: Template) -> None:
    """Every RLS guarantee this repo makes is verified against the container in
    compose.yaml and the service in ci.yml. A template naming a different major
    would run those guarantees on an engine nothing here has ever tested, and
    nothing would report the divergence -- the suite stays green either way.
    """
    root = Path(__file__).resolve().parents[2]
    template_major = str(template.resource("Database")["Properties"]["EngineVersion"]).split(".")[0]

    tested = set(
        re.findall(
            r"postgres:(\d+)",
            (root / "compose.yaml").read_text() + (root / ".github/workflows/ci.yml").read_text(),
        )
    )

    assert tested, "no postgres:<major> image in compose.yaml or ci.yml -- has one been renamed?"
    assert tested == {template_major}, (
        f"template runs postgres {template_major}, tests run {sorted(tested)}"
    )


# --- Portal execution (Task 14: EC2 launch type, shipped stopped) -----------


def test_the_portal_service_runs_on_ec2_not_fargate(template: Template) -> None:
    """Fargate refuses unprivileged user namespaces (measured, us-east-1,
    2026-08-26), so Chrome's renderer sandbox cannot engage there. The sandbox
    is the only boundary between a hostile portal page and a process holding
    the database password, the LLM key and live student cookies, so the launch
    type follows the sandbox rather than the other way around."""
    task = template.resource("PortalTaskDefinition")["Properties"]
    service = template.resource("PortalService")["Properties"]

    assert task["RequiresCompatibilities"] == ["EC2"]
    assert "FARGATE" not in task["RequiresCompatibilities"]
    assert service["LaunchType"] == "EC2"


def test_the_portal_volume_is_encrypted(template: Template) -> None:
    """The browser profile holding live portal session cookies lives on this
    volume, and volume-level encryption is what "encrypted at rest" means for a
    directory Chrome holds open (apps/portals/profiles.py)."""
    mappings = template.resource("PortalLaunchTemplate")["Properties"]["LaunchTemplateData"][
        "BlockDeviceMappings"
    ]

    assert all(mapping["Ebs"]["Encrypted"] is True for mapping in mappings)


def test_the_portal_service_ships_stopped(template: Template) -> None:
    """Portal terms (§10) gate running this against a real portal at all, and
    an idle EC2 instance is not free.

    MaxValue is pinned too, and is load-bearing in two places nothing else
    guards: a second task cannot resume an application the first one paused
    (browser profiles are local to their instance), and
    handle_portal_message's "no row lock, there is only one consumer" comment
    rests on it.
    """
    assert template.parameter("PortalDesiredCount")["Default"] == 0
    assert template.parameter("PortalDesiredCount")["MaxValue"] == 1
    assert template.resource("PortalService")["Properties"]["DesiredCount"] == {
        "Ref": "PortalDesiredCount"
    }
    assert template.resource("PortalAutoScalingGroup")["Properties"]["MinSize"] == "0"


def test_the_portal_capacity_provider_never_manages_scaling(template: Template) -> None:
    """PortalService uses LaunchType: EC2, so its tasks are never attributed
    to PortalCapacityProvider's own reservation count. With ManagedScaling
    ENABLED, ECS would see zero tasks reserved against the provider and drive
    the ASG back to MinSize "0" -- pulling the instance out from under a
    running task, since ManagedTerminationProtection is DISABLED. Browser
    profiles that let a paused application resume are local to that
    instance (PortalDesiredCount's own description), so this is not a
    "capacity fix" waiting to happen -- re-enabling it breaks the resume
    story it looks like it is protecting."""
    scaling = template.resource("PortalCapacityProvider")["Properties"]["AutoScalingGroupProvider"][
        "ManagedScaling"
    ]
    assert scaling["Status"] == "DISABLED"


def test_the_portal_task_role_consumes_only_the_portal_queue(template: Template) -> None:
    """An exact allowlist, not an absence check on the other two queues --
    the same failure test_the_database_admits_web_worker_and_portal_only's
    own docstring argues against. An absence check passes unchanged if a
    future statement grants Resource: "*" for sqs:*, or names some other
    queue added later; pinning the whole resource list closes both."""
    actions = _policy_actions(template.resource("PortalTaskRole"))
    assert any("sqs:ReceiveMessage" in action for action in actions)

    statements = [
        statement
        for policy in template.resource("PortalTaskRole")["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
    ]
    resources = [statement["Resource"] for statement in statements]
    # This module's Fn::GetAtt constructor parses the scalar form (!GetAtt
    # X.Y) into a plain "X.Y" string, not a two-element list -- see line ~214
    # above (EvidenceBucket.Arn) for the established precedent.
    assert resources == [
        {"Fn::GetAtt": "PortalQueue.Arn"},
        {
            "Fn::Sub": (
                "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:tehsil/portal/*"
            )
        },
    ]


def test_the_portal_escalation_filter_matches_what_escalate_actually_logs(
    template: Template,
) -> None:
    """Same failure this codebase has already had once: a metric filter whose
    pattern never matches is an alarm that never fires."""
    pattern = template.resource("PortalEscalationFilter")["Properties"]["FilterPattern"]

    assert "PortalEscalation" in pattern
    source = (
        Path(__file__).resolve().parents[2] / "apps" / "portals" / "escalation.py"
    ).read_text(encoding="utf-8")
    assert "PortalEscalation" in source
# --- The document engine's door ---------------------------------------------


@pytest.mark.parametrize("queue_id", ["DocumentQueue", "DocumentScanQueue"])
def test_the_document_queues_have_dead_letter_queues(template: Template, queue_id: str) -> None:
    queue = template.resource(queue_id)["Properties"]
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 3


def test_the_worker_knows_which_scan_delivery_is_the_last(template: Template) -> None:
    """consume_once marks a transcript READ_FAILED on the delivery SQS dead-letters next. A
    constant larger than the queue's count never fires; a smaller one fails a reading SQS
    would still have retried."""
    from apps.documents.document_queue import MAX_RECEIVES

    queue = template.resource("DocumentScanQueue")["Properties"]
    assert queue["RedrivePolicy"]["maxReceiveCount"] == MAX_RECEIVES


def test_document_queue_uses_the_kms_key_only_our_own_principals_need(
    template: Template,
) -> None:
    """Only our own IAM principals send here, so the AWS-managed key is fine."""
    assert template.resource("DocumentQueue")["Properties"]["KmsMasterKeyId"] == "alias/aws/sqs"


def test_document_scan_queue_uses_sse_sqs_not_a_kms_key(template: Template) -> None:
    """EventBridge is the sender on this one queue, and delivery to a
    KMS-encrypted queue needs kms:Decrypt/kms:GenerateDataKey for
    events.amazonaws.com granted through the key POLICY -- which an
    AWS-managed key's policy cannot be edited to grant. SSE-SQS needs no key
    policy at all. Getting this wrong fails silently: sqs:SendMessage
    succeeds at the IAM layer and the send still drops at the KMS layer, so
    every upload stays QUARANTINED forever with no alarm anywhere."""
    queue = template.resource("DocumentScanQueue")["Properties"]
    assert queue["SqsManagedSseEnabled"] is True
    assert "KmsMasterKeyId" not in queue


@pytest.mark.parametrize(
    "alarm_id",
    [
        "DocumentQueueAgeAlarm",
        "DocumentDeadLetterDepthAlarm",
        "DocumentScanQueueAgeAlarm",
        "DocumentScanDeadLetterDepthAlarm",
    ],
)
def test_the_document_queues_are_alarmed(template: Template, alarm_id: str) -> None:
    """A wedged document queue is a student's CV that never generates, with no
    other signal: there is no job-state row for a frontend to report on."""
    assert template.resource(alarm_id)["Type"] == "AWS::CloudWatch::Alarm"


@pytest.mark.parametrize(
    ("alarm_id", "queue_id"),
    [
        ("DocumentQueueAgeAlarm", "DocumentQueue"),
        ("DocumentScanQueueAgeAlarm", "DocumentScanQueue"),
    ],
)
def test_a_document_age_alarm_outlasts_its_whole_retry_envelope(
    template: Template, alarm_id: str, queue_id: str
) -> None:
    """Same relationship the Europass alarm keeps: with maxReceiveCount 3, a
    message that fails twice legitimately ages VisibilityTimeout x 2 before it
    reaches the DLQ. An alarm tighter than that pages on ordinary redelivery.
    If you raise VisibilityTimeout, this has to move with it."""
    queue = template.resource(queue_id)["Properties"]
    alarm = template.resource(alarm_id)["Properties"]
    assert alarm["Threshold"] >= queue["VisibilityTimeout"] * 2


def test_the_scan_rule_matches_guardduty_object_scan_results(template: Template) -> None:
    """Pattern verified against AWS's published samples. detail-type and source
    are the whole match: the handler re-checks the bucket itself, because this
    rule is account-wide."""
    rule = template.resource("DocumentScanRule")["Properties"]
    assert rule["EventPattern"] == {
        "detail-type": ["GuardDuty Malware Protection Object Scan Result"],
        "source": ["aws.guardduty"],
    }
    (target,) = rule["Targets"]
    assert target["Arn"] == {"Fn::GetAtt": "DocumentScanQueue.Arn"}


def test_eventbridge_may_send_to_the_scan_queue(template: Template) -> None:
    """A rule with no queue policy is a rule whose deliveries are silently
    dropped -- the scan verdict simply never arrives, and the only symptom is
    documents stuck at QUARANTINED forever."""
    policy = template.resource("DocumentScanQueuePolicy")["Properties"]
    statement = policy["PolicyDocument"]["Statement"][0]
    assert statement["Principal"] == {"Service": "events.amazonaws.com"}
    assert statement["Action"] == "sqs:SendMessage"
    assert statement["Condition"]["ArnEquals"]["aws:SourceArn"] == {
        "Fn::GetAtt": "DocumentScanRule.Arn"
    }


def test_a_scan_rule_that_stops_delivering_sets_off_an_alarm(template: Template) -> None:
    """Every other alarm on this path reads a queue, so none of them can see
    this: if the rule stops delivering, nothing is enqueued, nothing ages, and
    all four stay green while every upload sits at QUARANTINED forever."""
    alarm = template.resource("DocumentScanRuleFailedInvocationsAlarm")["Properties"]
    assert alarm["Namespace"] == "AWS/Events"
    assert alarm["MetricName"] == "FailedInvocations"
    assert alarm["Dimensions"] == [{"Name": "RuleName", "Value": {"Ref": "DocumentScanRule"}}]
    assert alarm["Threshold"] == 0
    assert alarm["ComparisonOperator"] == "GreaterThanThreshold"
    # A quiet hour publishes no datapoint at all; no uploads is not a fault.
    assert alarm["TreatMissingData"] == "notBreaching"


def test_the_document_worker_reads_quarantine_and_writes_tenant_objects(
    template: Template,
) -> None:
    """One task holds both grants: quarantine/* read for the scan-and-ingest
    path, tenants/* write for the render path -- the shape WorkerTaskRole
    already has. Splitting into two task definitions is the named upgrade
    path, not a requirement today."""
    role = template.resource("DocumentWorkerTaskRole")
    assert _object_actions(role, "${EvidenceBucket.Arn}/quarantine/*") == {
        "s3:GetObject",
        "s3:GetObjectVersion",
    }
    assert _object_actions(role, "${EvidenceBucket.Arn}/tenants/*") == {
        "s3:GetObject",
        "s3:PutObject",
    }
    assert "s3:DeleteObject" not in _policy_actions(role)


def test_the_document_worker_may_hand_off_to_the_europass_queue(template: Template) -> None:
    """A EUROPASS_API draft is enqueued, never rendered here: that queue is
    single-worker and pinned for the circuit breaker and the courtesy rate."""
    actions = _policy_actions(template.resource("DocumentWorkerTaskRole"))
    assert "sqs:SendMessage" in actions


def test_the_web_tier_may_write_an_upload_but_never_read_one(template: Template) -> None:
    """The presigned POST is signed with WebTaskRole's own credentials, so the
    upload cannot work without PutObject on quarantine/*. Read stays worker-only
    (ingestion opens the scanned-clean original), and tenants/* -- the released
    artefacts -- stays unwritable from the web tier entirely."""
    web = template.resource("WebTaskRole")
    assert _object_actions(web, "${EvidenceBucket.Arn}/quarantine/*") == {"s3:PutObject"}
    assert "s3:PutObject" not in _object_actions(web, "${EvidenceBucket.Arn}/tenants/*")
    assert "s3:GetObject" not in _object_actions(web, "${EvidenceBucket.Arn}/quarantine/*")


def test_the_document_worker_is_its_own_service(template: Template) -> None:
    assert template.resource("DocumentWorkerService")["Type"] == "AWS::ECS::Service"


# --- Transcript OCR runs on demand, in its own function -----------------------


def test_transcript_ocr_is_a_function_from_its_own_image(template: Template) -> None:
    """Not the shared AppImage, and not an always-on worker (owner, 2026-09-26). It is a small
    page inventory now (Azure does the reading), and its timeout stays under the scan queue's
    900 s visibility timeout so a slow read is never redelivered to a second reader."""
    function = template.resource("OcrFunction")["Properties"]
    assert function["PackageType"] == "Image"
    assert function["Code"] == {"ImageUri": {"Ref": "OcrImage"}}
    visibility = template.resource("DocumentScanQueue")["Properties"]["VisibilityTimeout"]
    assert function["Timeout"] < visibility
    worker = template.resource("DocumentWorkerTaskDefinition")["Properties"]
    assert (worker["Cpu"], worker["Memory"]) == ("512", "1024")


def test_the_document_worker_gets_the_azure_key_as_a_secret_and_never_the_launch_gate(
    template: Template,
) -> None:
    task = template.resource("DocumentWorkerTaskDefinition")["Properties"]
    container = task["ContainerDefinitions"][0]
    secrets = {s["Name"]: s["ValueFrom"] for s in container["Secrets"]}
    env = {e["Name"]: e["Value"] for e in container["Environment"]}
    assert secrets["AZURE_DI_KEY"] == {"Ref": "AzureDocumentIntelligenceKeySecret"}
    assert env["AZURE_DI_ENDPOINT"] == {"Ref": "AzureDocumentIntelligenceEndpoint"}
    assert "TRANSCRIPT_AZURE_ENABLED" not in env  # the owner turns it on after the DPA review


def test_the_page_inventory_function_is_small(template: Template) -> None:
    function = template.resource("OcrFunction")["Properties"]
    assert function["MemorySize"] <= 2048 and function["Timeout"] <= 120


def test_the_ocr_function_holds_no_secret_and_reads_only_cleared_uploads(
    template: Template,
) -> None:
    function = template.resource("OcrFunction")["Properties"]
    assert function["Environment"]["Variables"] == {"DOCUMENT_BUCKET": {"Ref": "EvidenceBucket"}}
    [policy] = template.resource("OcrFunctionRole")["Properties"]["Policies"]
    reads = [
        statement
        for statement in policy["PolicyDocument"]["Statement"]
        if "s3:GetObject" in statement["Action"]
    ]
    # GetObjectVersion: the function reads the version GuardDuty scanned, never the latest,
    # and the tag condition holds per version.
    assert reads == [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:GetObjectVersion"],
            "Resource": {"Fn::Sub": "${EvidenceBucket.Arn}/quarantine/*"},
            "Condition": {
                "StringEquals": {
                    "s3:ExistingObjectTag/GuardDutyMalwareScanStatus": "NO_THREATS_FOUND"
                }
            },
        }
    ]
    actions = {
        action
        for statement in policy["PolicyDocument"]["Statement"]
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
    }
    assert not {a for a in actions if a.startswith(("secretsmanager:", "kms:", "sqs:"))}
    assert {a for a in actions if a.startswith("s3:")} == {"s3:GetObject", "s3:GetObjectVersion"}


def test_the_ocr_subnets_have_no_route_out_but_s3(template: Template) -> None:
    """The parser of untrusted uploads cannot reach the internet or write to any bucket."""
    routes = [
        resource["Properties"]
        for resource in template.all_resources()
        if resource["Type"] == "AWS::EC2::Route"
    ]
    assert not [route for route in routes if route["RouteTableId"] == {"Ref": "OcrRouteTable"}]
    endpoint = template.resource("OcrS3Endpoint")["Properties"]
    assert endpoint["RouteTableIds"] == [{"Ref": "OcrRouteTable"}]
    [allowed] = endpoint["PolicyDocument"]["Statement"]
    assert allowed["Action"] == ["s3:GetObject", "s3:GetObjectVersion"]
    vpc = template.resource("OcrFunction")["Properties"]["VpcConfig"]
    assert vpc["SubnetIds"] == [{"Ref": "OcrPrivateSubnetA"}, {"Ref": "OcrPrivateSubnetB"}]


def test_the_document_worker_invokes_the_ocr_function_and_reaches_jev(template: Template) -> None:
    container = template.resource("DocumentWorkerTaskDefinition")["Properties"][
        "ContainerDefinitions"
    ][0]
    env = {entry["Name"]: entry["Value"] for entry in container["Environment"]}
    assert env["OCR_FUNCTION_NAME"] == {"Ref": "OcrFunction"}
    assert env["DECISIONS_BASE_URL"] == "https://openrouter.ai/api"
    assert env["TYPESAFE_MODEL"] == "typesafe/jev-1.13"
    secrets = {entry["Name"]: entry["ValueFrom"] for entry in container["Secrets"]}
    assert secrets["OPENROUTER_API_KEY"] == {"Ref": "TypesafeApiKeySecret"}
    assert "TYPESAFE_API_KEY" not in secrets
    statements = template.resource("DocumentWorkerTaskRole")["Properties"]["Policies"][0][
        "PolicyDocument"
    ]["Statement"]
    assert {
        "Effect": "Allow",
        "Action": "lambda:InvokeFunction",
        "Resource": {"Fn::GetAtt": "OcrFunction.Arn"},
    } in statements


# --- OPENAI_API_KEY reaches the tiers that call the OpenAI SDK ----------------


def _container_secrets(task_definition: dict[str, Any]) -> dict[str, Any]:
    container = task_definition["Properties"]["ContainerDefinitions"][0]
    return {entry["Name"]: entry["ValueFrom"] for entry in container.get("Secrets", [])}


@pytest.mark.parametrize(
    "task_definition_id",
    ["WorkerTaskDefinition", "DocumentWorkerTaskDefinition", "MailboxWorkerTaskDefinition"],
)
def test_the_llm_calling_tiers_are_handed_an_openai_key(
    template: Template, task_definition_id: str
) -> None:
    """Nothing in config/settings reads OPENAI_API_KEY -- the OpenAI SDK picks
    it straight off the environment when a client is constructed -- so no
    settings check and no _PRODUCTION_REQUIRED_ENV_VARS entry can catch its
    absence. It fails at the first LLM call instead: apps/research/extraction.py
    on the research worker, and generation/ingestion/tailoring/derive
    on the document worker. This test is the only thing standing between that
    and a deploy.

    It must arrive as a Secrets entry, never Environment: an Environment value
    is template text, which puts a live third-party credential in the repo and
    in every DescribeTaskDefinition response.
    """
    task_definition = template.resource(task_definition_id)
    assert _container_secrets(task_definition).get("OPENAI_API_KEY") == {
        "Ref": "OpenAiApiKeySecret"
    }
    execution_role = template.resource("AppExecutionRole")
    granted = [
        resource
        for policy in execution_role["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if statement["Action"] == "secretsmanager:GetSecretValue"
        for resource in statement["Resource"]
    ]
    assert {"Ref": "OpenAiApiKeySecret"} in granted, (
        "the execution role resolves Secrets entries; without the grant the task "
        "never starts, which is a louder failure but still a deploy-time one"
    )


def test_the_openai_key_stays_off_the_web_tier(template: Template) -> None:
    """No view calls an LLM (see CLAUDE.md: none of the LLM-calling modules is
    wired to one). Handing the web task an API key would undo that."""
    secrets = _container_secrets(template.resource("WebTaskDefinition"))
    assert "OPENAI_API_KEY" not in secrets


def test_the_openai_secret_carries_no_value_of_its_own(template: Template) -> None:
    """A third party issues this key, so the template owns an empty container
    and a human fills it once per environment. GenerateSecretString would mint
    a random string that looks like a configured key and fails every call with
    a 401; a literal SecretString would commit the key to the repo."""
    properties = template.resource("OpenAiApiKeySecret")["Properties"]
    assert "GenerateSecretString" not in properties
    assert "SecretString" not in properties


# --- The reminder ladder's hourly schedule ------------------------------------


def test_the_reminder_ladder_runs_hourly(template: Template) -> None:
    """Hourly, not daily: a daily job cannot hit the 6-hour rung at all."""
    rule = template.resource("ReminderLadderRule")

    assert rule["Properties"]["ScheduleExpression"] == "rate(1 hour)"
    assert rule["Properties"]["State"] == "ENABLED"


def test_the_reminder_ladder_runs_the_worker_task(template: Template) -> None:
    target = template.resource("ReminderLadderRule")["Properties"]["Targets"][0]
    parameters = target["EcsParameters"]

    assert parameters["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}
    assert parameters["LaunchType"] == "FARGATE"
    assert parameters["NetworkConfiguration"]["AwsVpcConfiguration"]["SecurityGroups"] == [
        {"Ref": "WorkerSecurityGroup"}
    ]


def test_the_reminder_ladder_invokes_the_command_that_exists(template: Template) -> None:
    """The container name and the command are a pair: a rename on either side
    leaves a rule that runs hourly and does nothing."""
    raw_input = template.resource("ReminderLadderRule")["Properties"]["Targets"][0]["Input"]
    overrides = json.loads(raw_input["Fn::Sub"])["containerOverrides"][0]

    assert overrides["name"] == "worker"
    assert overrides["command"] == ["python", "manage.py", "send_due_reminders"]


def test_the_ladder_ships_with_its_schedule(template: Template) -> None:
    """The erasure command shipped without its rule and that is now a
    documented deployment blocker: the command exists, nothing invokes it, and
    every screen says the right thing. An hourly sweep nobody invokes fails the
    same silent way."""
    assert "ReminderLadderRule" in template.resource_ids()


def test_erasure_ships_with_its_schedule_enabled(template: Template) -> None:
    """The deployment blocker CLAUDE.md records, closed: a deletion request is
    executed only if something runs execute_due_erasures, daily, as the worker."""
    rule = template.resource("ExecuteDueErasuresRule")["Properties"]
    assert rule["State"] == "ENABLED"
    assert rule["ScheduleExpression"] == "rate(1 day)"
    overrides = json.loads(rule["Targets"][0]["Input"]["Fn::Sub"])["containerOverrides"][0]
    assert overrides["command"] == ["python", "manage.py", "execute_due_erasures"]

# --- the fetch vendors' keys reach the research worker ------------------------


@pytest.mark.parametrize(
    ("variable", "secret"),
    [
        ("FIRECRAWL_API_KEY", "FirecrawlApiKeySecret"),
        ("SCRAPEDO_API_KEY", "ScrapeDoApiKeySecret"),
    ],
)
def test_the_research_worker_is_handed_the_fetch_vendor_keys(
    template: Template, variable: str, secret: str
) -> None:
    """Every research page fetch goes through apps/research/fetch, and both
    providers raise "... is not set" on an empty key. VendorUnavailable
    subclasses SourceBlocked, so the pipeline degrades rather than aborting:
    deployed without these, a sweep blocks every lead and exits 0. Nothing in
    config/settings refuses to start without them either -- settings default
    both to "" -- so this test is the only thing standing between that and a
    deploy, exactly as for OPENAI_API_KEY above.

    Secrets entry, never Environment: an Environment value is template text,
    which puts a live third-party credential in the repo and in every
    DescribeTaskDefinition response.
    """
    worker = template.resource("WorkerTaskDefinition")
    assert _container_secrets(worker).get(variable) == {"Ref": secret}
    execution_role = template.resource("AppExecutionRole")
    granted = [
        resource
        for policy in execution_role["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if statement["Action"] == "secretsmanager:GetSecretValue"
        for resource in statement["Resource"]
    ]
    assert {"Ref": secret} in granted


@pytest.mark.parametrize("secret", ["FirecrawlApiKeySecret", "ScrapeDoApiKeySecret"])
def test_the_fetch_vendor_secrets_carry_no_value_of_their_own(
    template: Template, secret: str
) -> None:
    """Same reason as OpenAiApiKeySecret: a third party issues the key, so the
    template owns an empty container and a human fills it once per environment."""
    properties = template.resource(secret)["Properties"]
    assert "GenerateSecretString" not in properties
    assert "SecretString" not in properties


# --- the search providers reach the deployed worker --------------------------


def test_the_worker_can_read_every_search_provider_key(template: Template) -> None:
    """Without these the discovery sweep runs deployed as seed-catalogues-only
    and says so once, in a log line nobody reads. A key that is absent from
    the template is a feature that is silently off in production."""
    secrets = _container_secrets(template.resource("WorkerTaskDefinition"))
    for name in ("EXA_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY"):
        assert name in secrets, name
    execution_role = template.resource("AppExecutionRole")
    granted = [
        resource
        for policy in execution_role["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if statement["Action"] == "secretsmanager:GetSecretValue"
        for resource in statement["Resource"]
    ]
    for ref in ("ExaApiKeySecret", "BraveApiKeySecret", "TavilyApiKeySecret"):
        assert {"Ref": ref} in granted, ref


def test_the_search_keys_stay_off_the_web_tier(template: Template) -> None:
    """The plan asked this of BrowserTaskDefinition, whose guarantee was that
    there is nothing to steal. That tier was deleted with the Scrapling ladder
    (CLAUDE.md, "Web fetching"), so the assertion moves to the tier that still
    exists and still must not hold a provider credential: no view searches."""
    secrets = _container_secrets(template.resource("WebTaskDefinition"))
    for name in ("EXA_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY"):
        assert name not in secrets, name


def test_the_search_secrets_carry_no_value_of_their_own(template: Template) -> None:
    """Third parties issue these, so the template owns empty containers and a
    human fills them once per environment -- the same reason and the same
    shape as OpenAiApiKeySecret."""
    for name in ("ExaApiKeySecret", "BraveApiKeySecret", "TavilyApiKeySecret"):
        properties = template.resource(name)["Properties"]
        assert "SecretString" not in properties, name
        assert "GenerateSecretString" not in properties, name


# --- The application watch's schedule and its alarms ---------------------------


def test_the_watch_runs_hourly_and_ships_enabled(template: Template) -> None:
    rule = template.resource("WatchApplicationsRule")["Properties"]
    assert rule["ScheduleExpression"] == "rate(1 hour)"
    assert rule["State"] == "ENABLED"
    parameters = rule["Targets"][0]["EcsParameters"]
    assert parameters["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}


def test_the_watch_invokes_the_command_that_exists(template: Template) -> None:
    raw_input = template.resource("WatchApplicationsRule")["Properties"]["Targets"][0]["Input"]
    overrides = json.loads(raw_input["Fn::Sub"])["containerOverrides"][0]
    assert overrides["name"] == "worker"
    assert overrides["command"] == ["python", "manage.py", "watch_applications"]


@pytest.mark.parametrize(
    "rule", ["ReminderLadderRule", "WatchApplicationsRule", "SyncMailboxesRule"]
)
def test_a_schedule_that_stops_invoking_sets_off_an_alarm(template: Template, rule: str) -> None:
    alarm = template.resource(f"{rule}FailedInvocationsAlarm")["Properties"]
    assert alarm["Namespace"] == "AWS/Events"
    assert alarm["MetricName"] == "FailedInvocations"
    assert alarm["Dimensions"] == [{"Name": "RuleName", "Value": {"Ref": rule}}]
    assert alarm["Threshold"] == 0
    assert alarm["ComparisonOperator"] == "GreaterThanThreshold"


def test_a_silent_job_sets_off_an_alarm(template: Template) -> None:
    """A task that starts and dies is a successful invocation; only the jobs'
    own heartbeat check can see it (apps/watch/heartbeat.py)."""
    metric_filter = template.resource("JobSilentMetricFilter")["Properties"]
    assert metric_filter["LogGroupName"] == {"Ref": "WorkerLogGroup"}
    assert "JobSilent" in metric_filter["FilterPattern"]
    transformation = metric_filter["MetricTransformations"][0]
    alarm = template.resource("JobSilentAlarm")["Properties"]
    assert alarm["Namespace"] == transformation["MetricNamespace"]
    assert alarm["MetricName"] == transformation["MetricName"]
    assert alarm["Threshold"] == 0
    assert alarm["ComparisonOperator"] == "GreaterThanThreshold"
    assert alarm["TreatMissingData"] == "notBreaching"


def test_every_job_dying_at_once_sets_off_an_alarm(template: Template) -> None:
    """Both hourly jobs share one image and task definition, so one bad deploy
    kills both and nobody is left to log JobSilent. Missing JobFinished lines
    are the signal, so missing data must breach."""
    metric_filter = template.resource("JobFinishedMetricFilter")["Properties"]
    assert metric_filter["LogGroupName"] == {"Ref": "WorkerLogGroup"}
    assert "JobFinished" in metric_filter["FilterPattern"]
    transformation = metric_filter["MetricTransformations"][0]
    alarm = template.resource("JobFinishedMissingAlarm")["Properties"]
    assert alarm["Namespace"] == transformation["MetricNamespace"]
    assert alarm["MetricName"] == transformation["MetricName"]
    assert alarm["Statistic"] == "Sum"
    assert alarm["Period"] == 3600
    assert alarm["EvaluationPeriods"] == 2
    assert alarm["Threshold"] == 1
    assert alarm["ComparisonOperator"] == "LessThanThreshold"
    assert alarm["TreatMissingData"] == "breaching"


# --- the Firecrawl webhook secret reaches the web tier, not the worker -------


def test_the_webhook_secret_reaches_the_web_task_as_a_secret(template: Template) -> None:
    """The receiver runs in Web, not Worker -- the fetch vendors' API keys are
    the worker's. An Environment entry would put the HMAC key in template
    text, where it is readable by anyone with describe-task-definition."""
    web = template.resource("WebTaskDefinition")
    assert _container_secrets(web).get("FIRECRAWL_WEBHOOK_SECRET") == {
        "Ref": "FirecrawlWebhookSecret"
    }


def test_the_webhook_secret_carries_no_value_of_its_own(template: Template) -> None:
    """Firecrawl issues it, so the template can neither generate nor hold it:
    GenerateSecretString would mint a random value that verifies nothing, and
    a literal SecretString would commit the key to the repository."""
    properties = template.resource("FirecrawlWebhookSecret")["Properties"]
    assert "GenerateSecretString" not in properties
    assert "SecretString" not in properties


def _secret_ref(value_from: Any) -> Any:
    """The secret a Secrets ValueFrom resolves: itself, or for an ECS JSON-key
    reference ``!Sub "${Param}:<key>::"``, ``{"Ref": "Param"}``."""
    if isinstance(value_from, dict) and "Fn::Sub" in value_from:
        match = re.fullmatch(r"\$\{(\w+)\}:\w+::", value_from["Fn::Sub"])
        assert match, value_from
        return {"Ref": match.group(1)}
    return value_from


def test_every_task_secret_resolves_through_its_own_execution_role(template: Template) -> None:
    """ECS resolves a container's Secrets entries through the task's EXECUTION
    role; one it cannot read stops the task from starting, and nothing short of
    a deploy shows it. Written after a merge added FIRECRAWL_WEBHOOK_SECRET to
    the web task and granted it to AppExecutionRole, which the web task no
    longer uses. Covers every task definition, so the next split cannot repeat
    it. The Aurora master secret is a GetAtt, compared the same way. A JSON-key
    reference (``!Sub "${Arn}:key::"``) is checked against a grant on the
    secret it names: IAM is granted the secret, never a key inside it."""
    for task_id in template.resource_ids():
        resource = template.resource(task_id)
        if resource["Type"] != "AWS::ECS::TaskDefinition":
            continue
        properties = resource["Properties"]
        role_id = properties["ExecutionRoleArn"]["Fn::GetAtt"].split(".")[0]
        granted = [
            entry
            for policy in template.resource(role_id)["Properties"]["Policies"]
            for statement in policy["PolicyDocument"]["Statement"]
            if statement["Action"] == "secretsmanager:GetSecretValue"
            for entry in statement["Resource"]
        ]
        for container in properties["ContainerDefinitions"]:
            for secret in container.get("Secrets", []):
                assert _secret_ref(secret["ValueFrom"]) in granted, (
                    task_id,
                    role_id,
                    secret["Name"],
                )


# --- The provenance recheck's daily schedule ----------------------------------


def test_the_provenance_recheck_runs_daily_and_ships_enabled(template: Template) -> None:
    """Spec §7.6: without it UNCONFIRMED is never retried and a good school is
    lost silently -- the erasure schedule's failure mode, so it ships enabled."""
    rule = template.resource("ProvenanceRecheckRule")["Properties"]
    assert rule["ScheduleExpression"] == "rate(1 day)"
    assert rule["State"] == "ENABLED"
    target = rule["Targets"][0]
    assert target["EcsParameters"]["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}
    raw_input = target["Input"]
    body = raw_input["Fn::Sub"] if isinstance(raw_input, dict) else raw_input
    assert json.loads(body)["containerOverrides"][0]["command"] == [
        "python", "manage.py", "provenance_recheck",
    ]


def test_no_rule_schedules_the_mill_list_diff(template: Template) -> None:
    """mill_list_diff is an operator-run comparison, never a scheduled job --
    confirms the plan's decision not to add a rule for it stayed true."""
    for resource_id in template.resource_ids():
        resource = template.resource(resource_id)
        if resource["Type"] != "AWS::Events::Rule":
            continue
        for target in resource["Properties"].get("Targets", []):
            raw_input = target.get("Input")
            if raw_input is None:
                continue
            body = raw_input["Fn::Sub"] if isinstance(raw_input, dict) else raw_input
            assert "mill_list_diff" not in body


# --- Task 17: the worker's provenance-check S3 grants, narrowly scoped ------


def test_the_worker_may_archive_register_snapshots_write_only(template: Template) -> None:
    """load_register (apps/research/recognition.py, reached from
    provenance_job.py's check_body) archives a register's bytes with one
    S3ObjectStore().put() call and never reads one back."""
    registers_objects = "${EvidenceBucket.Arn}/registers/*"
    assert _object_actions(template.resource("WorkerTaskRole"), registers_objects) == {
        "s3:PutObject"
    }


def test_the_worker_reads_and_writes_official_source_snapshots_never_deletes(
    template: Template,
) -> None:
    """body_page_texts (apps/research/blocking.py) reads an archived
    official-source snapshot back for the content veto; persist_snapshot
    (apps/research/snapshot.py) writes one from discover and read_program_page,
    which run on the worker."""
    official_source_objects = "${EvidenceBucket.Arn}/official-sources/*"
    assert _object_actions(template.resource("WorkerTaskRole"), official_source_objects) == {
        "s3:GetObject",
        "s3:PutObject",
    }


# --- Task 17: PROVENANCE_GATE_ENFORCED, one Ref, both tiers -----------------


def test_provenance_gate_enforced_defaults_on_and_only_takes_0_or_1(template: Template) -> None:
    parameter = template.parameter("ProvenanceGateEnforced")
    assert parameter["Default"] == "1"
    assert set(parameter["AllowedValues"]) == {"0", "1"}


@pytest.mark.parametrize("task_definition_id", ["WebTaskDefinition", "WorkerTaskDefinition"])
def test_the_provenance_gate_flag_reaches_web_and_worker_from_one_ref(
    template: Template, task_definition_id: str
) -> None:
    """The pack-writing tier and the sweep tier read the same setting
    (apps/funding/services.py, pool.py vs apps/research/provenance_sweep.py)
    -- one Parameter feeding both task definitions is what keeps them from
    ever disagreeing on it."""
    container = template.resource(task_definition_id)["Properties"]["ContainerDefinitions"][0]
    entries = [e for e in container["Environment"] if e["Name"] == "PROVENANCE_GATE_ENFORCED"]
    assert len(entries) == 1
    assert entries[0]["Value"] == {"Ref": "ProvenanceGateEnforced"}


def test_the_cycle_verification_schedule_exists_and_ships_disabled(template: Template) -> None:
    """Daily, the finest cadence spec 9.3 asks for; `next_check_at` makes a
    monthly row wait. DISABLED because WorkerTaskDefinition carries no
    ANTHROPIC_API_KEY (the command refuses to start without it) and the 9.3
    gate has not been run -- see the comment above the rule."""
    rule = template.resource("VerifyDueCyclesRule")["Properties"]
    assert rule["State"] == "DISABLED"
    assert rule["ScheduleExpression"] == "rate(1 day)"
    target = rule["Targets"][0]
    body = target["Input"]["Fn::Sub"] if isinstance(target["Input"], dict) else target["Input"]
    assert json.loads(body)["containerOverrides"][0]["command"] == [
        "python", "manage.py", "verify_due_cycles",
    ]
    assert target["EcsParameters"]["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}


def test_the_transcript_resume_sweep_runs_every_fifteen_minutes_with_the_azure_key(
    template: Template,
) -> None:
    rule = template.resource("TranscriptResumeRule")["Properties"]
    assert rule["ScheduleExpression"] == "rate(15 minutes)" and rule["State"] == "ENABLED"
    [target] = rule["Targets"]
    assert target["EcsParameters"]["TaskDefinitionArn"] == {"Ref": "DocumentWorkerTaskDefinition"}
    overrides = json.loads(target["Input"]["Fn::Sub"])["containerOverrides"][0]
    assert overrides["name"] == "document-worker"
    assert overrides["command"] == ["python", "manage.py", "resume_transcript_readings"]


# --- Graph push for Microsoft mailboxes (watch spec §3a) ---------------------

_MAILBOX_SECRETS = {
    "Fn::Sub": "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:tehsil/mailbox/*"
}


def test_the_mailbox_queue_dead_letters_like_the_europass_queue(template: Template) -> None:
    """Identifiers only on a durable queue, three receives, then a DLQ that
    pages: a crash in the mailbox worker must surface, not loop forever."""
    queue = template.resource("MailboxQueue")["Properties"]
    europass = template.resource("EuropassQueue")["Properties"]
    assert not queue.get("FifoQueue", False)
    assert queue["KmsMasterKeyId"] == "alias/aws/sqs"
    assert queue["RedrivePolicy"] == {
        "deadLetterTargetArn": {"Fn::GetAtt": "MailboxDeadLetterQueue.Arn"},
        "maxReceiveCount": europass["RedrivePolicy"]["maxReceiveCount"],
    }
    dlq_alarm = template.resource("MailboxDeadLetterDepthAlarm")["Properties"]
    assert dlq_alarm["Dimensions"] == [
        {"Name": "QueueName", "Value": {"Fn::GetAtt": "MailboxDeadLetterQueue.QueueName"}}
    ]
    assert dlq_alarm["Threshold"] == 0


def test_the_mailbox_age_alarm_outlasts_the_whole_retry_envelope(template: Template) -> None:
    """Same arithmetic as the Europass alarm: tighter than VisibilityTimeout x
    (maxReceiveCount - 1) pages on ordinary redelivery."""
    queue = template.resource("MailboxQueue")["Properties"]
    alarm = template.resource("MailboxQueueAgeAlarm")["Properties"]
    assert alarm["Dimensions"] == [
        {"Name": "QueueName", "Value": {"Fn::GetAtt": "MailboxQueue.QueueName"}}
    ]
    legitimate_age = queue["VisibilityTimeout"] * (queue["RedrivePolicy"]["maxReceiveCount"] - 1)
    assert alarm["Threshold"] >= legitimate_age


def test_the_mailbox_worker_is_one_fargate_task_running_the_consumer(
    template: Template,
) -> None:
    service = template.resource("MailboxWorkerService")["Properties"]
    assert service["DesiredCount"] == 1
    assert service["LaunchType"] == "FARGATE"
    assert service["TaskDefinition"] == {"Ref": "MailboxWorkerTaskDefinition"}
    network = service["NetworkConfiguration"]["AwsvpcConfiguration"]
    assert network["AssignPublicIp"] == "DISABLED"
    assert network["SecurityGroups"] == [{"Ref": "WorkerSecurityGroup"}]
    task = template.resource("MailboxWorkerTaskDefinition")["Properties"]
    assert task["RequiresCompatibilities"] == ["FARGATE"]
    assert task["TaskRoleArn"] == {"Fn::GetAtt": "MailboxWorkerTaskRole.Arn"}
    assert task["ContainerDefinitions"][0]["Command"] == [
        "python", "manage.py", "run_mailbox_worker",
    ]


def test_the_mailbox_worker_role_holds_exactly_the_queue_and_the_grant_rotation(
    template: Template,
) -> None:
    """The exact list, so anything added is a deliberate edit to this test.
    Get+Put because Microsoft rotates the refresh token on every use
    (oauth.py::access_token_for -> replace_refresh_token). Never CreateSecret
    (a worker that could recreate a grant could undo a revoke), never
    DeleteSecret (erasure is WorkerTaskRole's), never ListSecrets, never S3."""
    statements = [
        statement
        for policy in template.resource("MailboxWorkerTaskRole")["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
    ]
    assert statements == [
        {
            "Effect": "Allow",
            "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
            "Resource": {"Fn::GetAtt": "MailboxQueue.Arn"},
        },
        {
            "Effect": "Allow",
            "Action": ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"],
            "Resource": _MAILBOX_SECRETS,
        },
    ]


def test_the_web_tier_may_enqueue_mailbox_work_but_never_consume_it(template: Template) -> None:
    """The webhook, the OAuth callback (views.py -> push.enqueue_work) and the
    extension's mailbox check (ext_api.mailbox_check) enqueue; only the mailbox
    worker receives, and only it may read a stored grant."""
    statements = [
        statement
        for policy in template.resource("WebTaskRole")["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
    ]
    on_mailbox_queue = [
        statement
        for statement in statements
        if statement["Resource"] == {"Fn::GetAtt": "MailboxQueue.Arn"}
    ]
    assert on_mailbox_queue == [
        {
            "Effect": "Allow",
            "Action": "sqs:SendMessage",
            "Resource": {"Fn::GetAtt": "MailboxQueue.Arn"},
        }
    ]


def test_the_mailbox_sweep_runs_every_six_hours_and_ships_enabled(template: Template) -> None:
    """The backstop for every notification Graph drops, and the subscription
    upkeep: unscheduled, subscriptions lapse in seven days and push silently
    stops, while the heartbeat (13 h) says the sweep went missing."""
    rule = template.resource("SyncMailboxesRule")["Properties"]
    assert rule["ScheduleExpression"] == "rate(6 hours)"
    assert rule["State"] == "ENABLED"
    target = rule["Targets"][0]
    assert target["EcsParameters"]["TaskDefinitionArn"] == {"Ref": "WorkerTaskDefinition"}
    assert target["RoleArn"] == {"Fn::GetAtt": "EventsInvokeEcsRole.Arn"}
    body = target["Input"]["Fn::Sub"] if isinstance(target["Input"], dict) else target["Input"]
    overrides = json.loads(body)["containerOverrides"][0]
    assert overrides["name"] == "worker"
    assert overrides["command"] == ["python", "manage.py", "sync_mailboxes"]


def test_mailbox_push_defaults_off_and_only_takes_0_or_1(template: Template) -> None:
    parameter = template.parameter("MailboxPushEnabled")
    assert parameter["Default"] == "0"
    assert set(parameter["AllowedValues"]) == {"0", "1"}


@pytest.mark.parametrize(
    "task_definition_id",
    ["WebTaskDefinition", "WorkerTaskDefinition", "MailboxWorkerTaskDefinition"],
)
def test_the_mailbox_push_flag_reaches_every_push_tier_from_one_ref(
    template: Template, task_definition_id: str
) -> None:
    """Webhook (web), upkeep in the sweep (worker) and upkeep on "subscribe"
    (mailbox worker) all read it; one Parameter keeps them from disagreeing."""
    container = template.resource(task_definition_id)["Properties"]["ContainerDefinitions"][0]
    entries = [e for e in container["Environment"] if e["Name"] == "MAILBOX_PUSH_ENABLED"]
    assert entries == [{"Name": "MAILBOX_PUSH_ENABLED", "Value": {"Ref": "MailboxPushEnabled"}}]


def test_every_production_task_definition_is_handed_the_mailbox_queue(
    template: Template,
) -> None:
    """Structural rather than a list: production.py requires MAILBOX_QUEUE_URL
    at import, so any task definition running production settings without it
    dies before its command runs."""
    for task_id in template.resource_ids():
        resource = template.resource(task_id)
        if resource["Type"] != "AWS::ECS::TaskDefinition":
            continue
        container = resource["Properties"]["ContainerDefinitions"][0]
        env = {e["Name"]: e["Value"] for e in container.get("Environment", [])}
        if env.get("DJANGO_SETTINGS_MODULE") != "config.settings.production":
            continue
        assert env.get("MAILBOX_QUEUE_URL") == {"Ref": "MailboxQueue"}, task_id


# --- Student-mailbox OAuth credentials ------------------------------------------

_MAILBOX_OAUTH_SECRETS = {
    "MICROSOFT_OAUTH_CLIENT_SECRET": {"Fn::Sub": "${MailboxOAuthClientSecretArn}:microsoft::"},
    "GOOGLE_OAUTH_CLIENT_SECRET": {"Fn::Sub": "${MailboxOAuthClientSecretArn}:google::"},
}
_MAILBOX_OAUTH_IDS = {
    "MICROSOFT_OAUTH_CLIENT_ID": {"Ref": "MicrosoftOAuthClientId"},
    "GOOGLE_OAUTH_CLIENT_ID": {"Ref": "GoogleOAuthClientId"},
}
_MAILBOX_OAUTH_TASKS = {"WebTaskDefinition", "WorkerTaskDefinition", "MailboxWorkerTaskDefinition"}
_MAILBOX_OAUTH_NAMES = {*_MAILBOX_OAUTH_SECRETS, *_MAILBOX_OAUTH_IDS, "MAILBOX_OAUTH_REDIRECT_BASE"}


def _container_env(task_definition: dict[str, Any]) -> dict[str, Any]:
    container = task_definition["Properties"]["ContainerDefinitions"][0]
    return {entry["Name"]: entry["Value"] for entry in container.get("Environment", [])}


@pytest.mark.parametrize(
    "parameter", ["MicrosoftOAuthClientId", "GoogleOAuthClientId", "MailboxOAuthRedirectBase"]
)
def test_the_mailbox_oauth_plain_parameters_default_empty(
    template: Template, parameter: str
) -> None:
    """Empty means "provider not configured" in config/settings/base.py, which
    is the right state for a stack nobody has registered an app for yet."""
    assert template.parameter(parameter)["Default"] == ""


def test_the_mailbox_oauth_secret_arn_is_required_and_cannot_be_a_wildcard(
    template: Template,
) -> None:
    """It lands in two execution roles' Resource lists; a wildcard there would
    hand both roles every secret in the account."""
    parameter = template.parameter("MailboxOAuthClientSecretArn")
    assert "Default" not in parameter
    pattern = parameter["AllowedPattern"]
    prefix = "arn:aws:secretsmanager:eu-central-1:123456789012:secret:"
    full = f"{prefix}tehsil/mailbox/oauth-client-AbC123"
    assert re.fullmatch(pattern, full)
    assert not re.fullmatch(pattern, f"{prefix}*")
    assert not re.fullmatch(pattern, f"{prefix}tehsil/*")
    # Already carries a JSON key: the task definitions' ":microsoft::" would break it.
    assert not re.fullmatch(pattern, f"{full}:microsoft::")
    assert not re.fullmatch(pattern, "REPLACE_WITH_SECRET_ARN")


@pytest.mark.parametrize("task_definition_id", sorted(_MAILBOX_OAUTH_TASKS))
def test_the_mailbox_tiers_get_the_oauth_client_credentials(
    template: Template, task_definition_id: str
) -> None:
    """Web for connect and the callback's code exchange; worker (sync_mailboxes)
    and mailbox worker for apps/mailbox/oauth.py::access_token_for's refresh.
    Missing on any one, every student's connection fails there in silence --
    settings default to "". Secrets by JSON key, never Environment."""
    task_definition = template.resource(task_definition_id)
    secrets = _container_secrets(task_definition)
    for name, value_from in _MAILBOX_OAUTH_SECRETS.items():
        assert secrets.get(name) == value_from, name
    env = _container_env(task_definition)
    for name, value in _MAILBOX_OAUTH_IDS.items():
        assert env.get(name) == value, name
    assert not _MAILBOX_OAUTH_SECRETS.keys() & env.keys()


def test_only_the_web_tier_builds_the_oauth_redirect(template: Template) -> None:
    """Only connect and the callback build a redirect URI; a refresh never does."""
    holders = {
        task_id
        for task_id in template.resource_ids()
        if template.resource(task_id)["Type"] == "AWS::ECS::TaskDefinition"
        and "MAILBOX_OAUTH_REDIRECT_BASE" in _container_env(template.resource(task_id))
    }
    assert holders == {"WebTaskDefinition"}
    env = _container_env(template.resource("WebTaskDefinition"))
    assert env["MAILBOX_OAUTH_REDIRECT_BASE"] == {"Ref": "MailboxOAuthRedirectBase"}


def test_no_other_task_definition_carries_mailbox_oauth_credentials(
    template: Template,
) -> None:
    """Europass, document worker, migration, portal and probe have no mailbox
    code path; an OAuth client secret there is reach for nothing."""
    for task_id in template.resource_ids():
        resource = template.resource(task_id)
        if resource["Type"] != "AWS::ECS::TaskDefinition" or task_id in _MAILBOX_OAUTH_TASKS:
            continue
        assert not _MAILBOX_OAUTH_NAMES & _container_env_names(resource), task_id


@pytest.mark.parametrize("role_id", ["WebExecutionRole", "AppExecutionRole"])
def test_the_mailbox_execution_roles_may_read_exactly_the_oauth_secret(
    template: Template, role_id: str
) -> None:
    """ECS resolves Secrets with the EXECUTION role: Web uses WebExecutionRole,
    Worker and MailboxWorker AppExecutionRole. Granted by the parameter's own
    Ref -- never a wildcard, never a Sub that could widen it."""
    statements = [
        statement
        for policy in template.resource(role_id)["Properties"]["Policies"]
        for statement in policy["PolicyDocument"]["Statement"]
        if statement["Action"] == "secretsmanager:GetSecretValue"
    ]
    resources = [resource for statement in statements for resource in statement["Resource"]]
    assert {"Ref": "MailboxOAuthClientSecretArn"} in resources
    assert all(isinstance(resource, dict) for resource in resources), resources
    assert not any("*" in json.dumps(resource) for resource in resources), resources
    users = {
        "WebExecutionRole": ["WebTaskDefinition"],
        "AppExecutionRole": ["WorkerTaskDefinition", "MailboxWorkerTaskDefinition"],
    }[role_id]
    for task_id in users:
        execution_role = template.resource(task_id)["Properties"]["ExecutionRoleArn"]
        assert execution_role == {"Fn::GetAtt": f"{role_id}.Arn"}, task_id


def test_the_portal_execution_role_cannot_read_the_mailbox_oauth_secret(
    template: Template,
) -> None:
    role = template.resource("PortalExecutionRole")
    assert "MailboxOAuthClientSecretArn" not in json.dumps(role)


def test_promotion_needs_no_grant_on_guarddutys_role(template: Template) -> None:
    """Uploads are promoted to tenants/ by handle_scan_result, which runs under
    DocumentWorkerTaskRole (get quarantine/*, get+put tenants/*). DocumentScanRole
    is GuardDuty's service role: it runs none of our code and keeps no write
    beyond the scan tag. The upload check runs in OcrFunction, which can write
    nothing at all (test_the_ocr_function_holds_no_secret_and_reads_only_cleared_uploads,
    unchanged)."""
    assert "s3:PutObject" not in _policy_actions(template.resource("DocumentScanRole"))
    worker = template.resource("DocumentWorkerTaskRole")
    # Exactly these: the scanned version is read from quarantine/, the copy written to tenants/.
    assert _object_actions(worker, "${EvidenceBucket.Arn}/quarantine/*") == {
        "s3:GetObject",
        "s3:GetObjectVersion",
    }
    assert _object_actions(worker, "${EvidenceBucket.Arn}/tenants/*") == {
        "s3:GetObject",
        "s3:PutObject",
    }
    [ocr] = template.resource("OcrFunctionRole")["Properties"]["Policies"]
    quarantine = [
        statement
        for statement in ocr["PolicyDocument"]["Statement"]
        if statement["Resource"] == {"Fn::Sub": "${EvidenceBucket.Arn}/quarantine/*"}
    ]
    assert [statement["Action"] for statement in quarantine] == [
        ["s3:GetObject", "s3:GetObjectVersion"]
    ]
    web = template.resource("WebTaskRole")
    assert "s3:GetObject" in _object_actions(web, "${EvidenceBucket.Arn}/tenants/*")
