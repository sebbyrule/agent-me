from agent_kernel.permissions import Decision, PermissionPolicy, RiskLevel


def test_reads_always_allowed():
    for mode in ("ask", "allow", "deny"):
        assert PermissionPolicy(mode).decide(RiskLevel.READ) == Decision.ALLOW


def test_ask_mode_prompts_for_write_and_exec():
    policy = PermissionPolicy("ask")
    assert policy.decide(RiskLevel.WRITE) == Decision.ASK
    assert policy.decide(RiskLevel.EXEC) == Decision.ASK


def test_allow_mode_auto_approves():
    policy = PermissionPolicy("allow")
    assert policy.decide(RiskLevel.WRITE) == Decision.ALLOW
    assert policy.decide(RiskLevel.EXEC) == Decision.ALLOW


def test_deny_mode_refuses_non_read():
    policy = PermissionPolicy("deny")
    assert policy.decide(RiskLevel.WRITE) == Decision.DENY
    assert policy.decide(RiskLevel.EXEC) == Decision.DENY
