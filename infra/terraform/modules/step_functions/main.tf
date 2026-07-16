# ===========================================================================
# A-W2 -- SFN platform: ONE parameterized thin-contract silver state machine.
#
# Binding rule (plan line 6): ONE machine + per-family input JSON; delete
# schedules, never add bespoke machines. Weather's 4-wide silver + dependent
# gold + single family gate over 5 tables is expressed PURELY as phase contents.
#
# Execution INPUT schema (plan A-W2 "State machine shape"), object-keyed phases
# so each stage Maps over its own task list via a fixed ItemsPath:
#   {
#     "family": "fx_macro_daily",
#     "phases": {
#       "fetch":  { "tasks": [ <task>, ... ] },   # ALL three keys REQUIRED
#       "bronze": { "tasks": [ <task>, ... ] },   # (empty array [] is allowed;
#       "silver": { "tasks": [ <task>, ... ] }    #  a MISSING path errors the Map)
#     },
#     "gate":    { "jobdef": "leviathan-dev-evidence-build",
#                  "queue":  "<queue-ondemand arn|name>",
#                  "command": ["jobs/audit/silver_rebuild_gate.py","--tables","...",
#                              "--asof","...","--baseline-uri","..."] },
#     "promote": { "tasks": [ <task>, ... ] },    # same-family silver jobdef,
#                                                 # --publish-mode canonical, jobRoleArn=silver-publisher
#     "auth_mode": "kms"                           # conveyed to promote jobs via task.env
#   }
#
#   <task> = {
#     "integration": "batch" | "glue",
#     "jobdef":  "<batch jobdef name|arn>",       # batch tasks
#     "queue":   "<queue arn|name>",              # batch tasks
#     "command": ["jobs/batch/x.py", "..."],      # batch tasks (REQUIRED, array)
#     "env":     [ {"Name":"K","Value":"V"} ],    # batch tasks (REQUIRED array,
#                                                 #  Batch ContainerOverrides.Environment shape; [] if none)
#     "glue_job":  "<glue job name>",             # glue tasks
#     "arguments": { "--k": "v" }                 # glue tasks (Glue Arguments map)
#   }
#
# The A-W6 generator renders this input from configs/silver/dags/{family}.json.
# The [Gate] verdict is the job EXIT CODE (batch:submitJob.sync throws
# States.TaskFailed on a FAILED job) -- NOT in-machine JSON parsing (plan line 93).
# A red gate is CAUGHT -> [FailNotify] and [Promote] is never entered (INV-6).
# ===========================================================================

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  # Reusable per-task iterator: Choice on integration -> batch|glue .sync.
  # Item scope: ItemSelector merges the top-level family with the current task
  # ({ family, task }). A batch item never has glue_job (and the Glue branch never
  # runs for it) so the missing-field-on-the-wrong-branch trap is avoided.
  # INLINE Map iterator states share ONE global namespace across the whole
  # definition (AWS DUPLICATE_STATE_NAME), so the processor is stamped per phase
  # with suffixed state names instead of shared verbatim.
  task_item_processors = {
    for phase in ["Fetch", "Bronze", "Silver", "Promote"] : phase => {
      ProcessorConfig = { Mode = "INLINE" }
      StartAt         = "RouteIntegration${phase}"
      States = {
        "RouteIntegration${phase}" = {
          Type = "Choice"
          Choices = [{
            Variable     = "$.task.integration"
            StringEquals = "glue"
            Next         = "GlueSync${phase}"
          }]
          Default = "BatchSync${phase}"
        }

        "BatchSync${phase}" = {
          Type     = "Task"
          Resource = "arn:aws:states:::batch:submitJob.sync"
          Parameters = {
            "JobName.$"       = "States.Format('{}-{}', $.family, States.UUID())"
            "JobDefinition.$" = "$.task.jobdef"
            "JobQueue.$"      = "$.task.queue"
            ContainerOverrides = {
              "Command.$"     = "$.task.command"
              "Environment.$" = "$.task.env"
            }
          }
          Retry = [{
            ErrorEquals     = ["States.TaskFailed", "States.Timeout"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }]
          End = true
        }

        "GlueSync${phase}" = {
          Type     = "Task"
          Resource = "arn:aws:states:::glue:startJobRun.sync"
          Parameters = {
            "JobName.$"   = "$.task.glue_job"
            "Arguments.$" = "$.task.arguments"
          }
          Retry = [{
            ErrorEquals     = ["States.TaskFailed", "States.Timeout", "Glue.ConcurrentRunsExceededException"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }]
          End = true
        }
      }
    }
  }

  # ItemSelector shared by every phase Map -- carries family into item scope.
  map_item_selector = {
    "family.$" = "$.family"
    "task.$"   = "$$.Map.Item.Value"
  }

  definition = {
    Comment = "Leviathan silver thin contract: fetch->bronze->silver-shadow->gate->{promote|fail-notify}->reconcile. ONE machine, per-family input."
    StartAt = "Fetch"
    States = {
      # --- fetch -> bronze -> silver (all shadow via task.command --publish-mode shadow) ---
      Fetch = {
        Type           = "Map"
        ItemsPath      = "$.phases.fetch.tasks"
        ItemSelector   = local.map_item_selector
        ItemProcessor  = local.task_item_processors["Fetch"]
        MaxConcurrency = var.map_max_concurrency
        ResultPath     = "$.fetchResults" # scratch path: preserve the input object for later states
        Next           = "Bronze"
      }
      Bronze = {
        Type           = "Map"
        ItemsPath      = "$.phases.bronze.tasks"
        ItemSelector   = local.map_item_selector
        ItemProcessor  = local.task_item_processors["Bronze"]
        MaxConcurrency = var.map_max_concurrency
        ResultPath     = "$.bronzeResults"
        Next           = "Silver"
      }
      Silver = {
        Type           = "Map"
        ItemsPath      = "$.phases.silver.tasks"
        ItemSelector   = local.map_item_selector
        ItemProcessor  = local.task_item_processors["Silver"]
        MaxConcurrency = var.map_max_concurrency
        ResultPath     = "$.silverResults"
        Next           = "Gate"
      }

      # --- gate: exit 0/1 = PASS/FAIL. FAIL raises States.TaskFailed -> Catch -> FailNotify. ---
      Gate = {
        Type     = "Task"
        Resource = "arn:aws:states:::batch:submitJob.sync"
        Parameters = {
          "JobName.$"       = "States.Format('{}-gate-{}', $.family, States.UUID())"
          "JobDefinition.$" = "$.gate.jobdef"
          "JobQueue.$"      = "$.gate.queue"
          ContainerOverrides = {
            "Command.$" = "$.gate.command"
            # Gate invariant (plan line 87): pg numbers backend.
            Environment = [{ Name = "GRAPHRAG_NUMBERS_BACKEND", Value = "pg" }]
          }
        }
        # Retry ONLY transient Batch service faults -- NEVER States.TaskFailed
        # (a red gate must not be retried into a green one).
        Retry = [{
          ErrorEquals     = ["Batch.ServerException", "Batch.TooManyRequestsException", "States.Timeout"]
          IntervalSeconds = 30
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "FailNotify"
        }]
        ResultPath = "$.gateResult"
        Next       = "Promote" # [Choice] fork realized as the .sync exit-code exception (green -> here)
      }

      # --- promote: same-family silver jobdef --publish-mode canonical under silver-publisher (auth_mode=kms via task.env) ---
      Promote = {
        Type           = "Map"
        ItemsPath      = "$.promote.tasks"
        ItemSelector   = local.map_item_selector
        ItemProcessor  = local.task_item_processors["Promote"]
        MaxConcurrency = var.map_max_concurrency
        ResultPath     = "$.promoteResults"
        Next           = "Reconcile"
      }

      # --- reconcile: A-W3 replaces this Pass with a batch task writing the post-census
      #     to s3://<bucket>/cascade_census/rolling/{family}/census.json (out of A-W2 scope). ---
      Reconcile = {
        Type       = "Pass"
        Comment    = "A-W3 fills this: write the run's post-census to the rolling S3 baseline key."
        ResultPath = "$.reconcile"
        Next       = "Succeeded"
      }

      Succeeded = { Type = "Succeed" }

      # --- fail-notify: publish to leviathan-dev-alerts, then end FAILED (drives the ExecutionsFailed alarm). ---
      FailNotify = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = var.alerts_topic_arn
          "Subject.$" = "States.Format('[${local.name_prefix}] silver pipeline FAILED: {}', $.family)"
          "Message.$" = "States.Format('Family {} failed the silver_rebuild_gate (or an upstream task). Execution {}. Canonical left untouched (INV-6).', $.family, $$.Execution.Name)"
        }
        ResultPath = "$.notifyResult"
        Next       = "PipelineFailed"
      }
      PipelineFailed = {
        Type  = "Fail"
        Error = "SilverPipelineGateFailed"
        Cause = "The silver_rebuild_gate returned FAIL (or an upstream fetch/bronze/silver task failed); canonical promote was skipped."
      }
    }
  }
}

# ---------------------------------------------------------------------------
# CloudWatch vended-log group for the state machine.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/${local.name_prefix}-silver-thin-contract"
  retention_in_days = var.log_retention_days
  tags              = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# States execution role + policy (plan A-W2 step 1 exact list).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "sfn_exec" {
  name = "${local.name_prefix}-sfn-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_iam_role_policy" "sfn_exec" {
  name = "${local.name_prefix}-sfn-exec"
  role = aws_iam_role.sfn_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Sid      = "BatchSubmitDescribeTerminate"
          Effect   = "Allow"
          Action   = ["batch:SubmitJob", "batch:DescribeJobs", "batch:TerminateJob"]
          Resource = "*" # DescribeJobs/TerminateJob are not resource-scopable; mirrors module.iam batch_orchestrator
        },
        {
          Sid      = "GlueStartGetStop"
          Effect   = "Allow"
          Action   = ["glue:StartJobRun", "glue:GetJobRun", "glue:BatchStopJobRun"]
          Resource = "*"
        },
        {
          # .sync managed EventBridge rule for batch:submitJob.sync callbacks
          # (StepFunctionsGetEventsForBatchJobsRule). Glue .sync is POLL-based
          # (glue:GetJobRun above) and has NO managed rule -- so the wildcard covers
          # only the Batch (and any future ECS) managed .sync rule, not all rules.
          Sid      = "BatchSyncManagedRule"
          Effect   = "Allow"
          Action   = ["events:PutRule", "events:PutTargets", "events:DescribeRule"]
          Resource = "arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsFor*Rule"
        },
        {
          Sid      = "SnsPublishAlertTopics"
          Effect   = "Allow"
          Action   = "sns:Publish"
          Resource = [var.alerts_topic_arn, var.silver_pipeline_topic_arn]
        },
        {
          # SFN vended CloudWatch Logs delivery (required on "*" by the service).
          Sid    = "StatesVendedLogs"
          Effect = "Allow"
          Action = [
            "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
            "logs:DeleteLogDelivery", "logs:ListLogDeliveries",
            "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
          ]
          Resource = "*"
        },
      ],
      length(var.pass_role_arns) > 0 ? [{
        Sid      = "PassThinContractRoles"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = var.pass_role_arns
      }] : []
    )
  })
}

# ---------------------------------------------------------------------------
# The single parameterized Standard state machine.
# ---------------------------------------------------------------------------
resource "aws_sfn_state_machine" "silver_thin_contract" {
  name     = "${local.name_prefix}-silver-thin-contract"
  role_arn = aws_iam_role.sfn_exec.arn
  type     = "STANDARD"

  definition = jsonencode(local.definition)

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}
