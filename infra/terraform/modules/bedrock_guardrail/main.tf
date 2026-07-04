# ---------------------------------------------------------------------------
# GraphRAG serving INPUT guardrail (plan P4) — a managed prompt-injection +
# high-risk-PII pre-filter applied to the raw USER QUERY before the dispatch
# planner runs (orchestrator._guardrail_check). INPUT-ONLY by design: output
# filtering would fight the deterministic citation verifier, which owns answer
# quality. Defense-in-depth alongside the enum-locked planner, spotlighting,
# and the PIT kill-switch — not a replacement for them.
# Serving reads GRAPHRAG_GUARDRAIL=<guardrail id> (default off) — fail-open.
# ---------------------------------------------------------------------------

resource "aws_bedrock_guardrail" "graphrag_input" {
  name                      = "${var.project_name}-${var.environment}-graphrag-input"
  description               = "GraphRAG serving input pre-filter: prompt-attack (HIGH) + high-risk PII block."
  blocked_input_messaging   = "This query was flagged by the input safety filter and was not processed."
  blocked_outputs_messaging = "Blocked." # required field; output side is unused (NONE strengths)

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE" # PROMPT_ATTACK is input-only by API contract
    }
  }

  sensitive_information_policy_config {
    # Only identifiers that can never be legitimate in a commodity-research query.
    # Emails/names are NOT filtered — anonymizing would mutate legitimate queries.
    pii_entities_config {
      type   = "US_SOCIAL_SECURITY_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = "BLOCK"
    }
  }
}

data "aws_iam_policy_document" "apply_guardrail" {
  statement {
    sid       = "ApplyGraphragInputGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.graphrag_input.guardrail_arn]
  }
}

resource "aws_iam_policy" "apply_guardrail" {
  name        = "${var.project_name}-${var.environment}-apply-graphrag-guardrail"
  description = "Allows serving containers to call ApplyGuardrail on the GraphRAG input guardrail only."
  policy      = data.aws_iam_policy_document.apply_guardrail.json
}

resource "aws_iam_role_policy_attachment" "batch_job_apply_guardrail" {
  role       = var.batch_job_role_name
  policy_arn = aws_iam_policy.apply_guardrail.arn
}
