# ---------------------------------------------------------------------------
# Durable terminal store (Phase 4 Stage 4): store.py DynamoStore backend.
#
# Single-table design (pk/sk), on-demand billing, NO TTL (durable — unlike the graphrag-sessions table
# which TTLs conversation memory at 24h). Holds share links, the per-user thread INDEX, and — with the
# "durable turns" decision — each thread's full turn history keyed under the user.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "store" {
  name         = "${var.project_name}-${var.environment}-terminal-store"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true # durable user data — cheap insurance at this scale
  }

  tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}
