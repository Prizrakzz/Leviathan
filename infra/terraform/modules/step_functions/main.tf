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

  # =========================================================================
  # LANE B -- FETCH LEGS ARE BEST-EFFORT: BOUNDED, DISCRIMINATED, FETCH-ONLY.
  #
  # Measured 2026-09-01 / 09-03 / 09-04: jobs/ingest/fetch_cepea_daily.py took
  # HTTP 403 (Cloudflare) on both indicators with the pinned CEPEA_USER_AGENT,
  # returned nothing_fetched and exited 1. The Fetch Map was fail-fast, so
  # czce/jse/miax/euronext never reached silver, gate or promote -- ONE blocked
  # venue staled FIVE futures boards on 3 of 4 fires. Source-side blocks are
  # PARKED by house law (no UA rotation, no bot evasion), so the DAG has to
  # survive them.
  #
  # THREE BOUNDS, each measured, none optional:
  #
  #  1. BOUNDED. A degraded fetch continues to Bronze ONLY when at least one leg
  #     SUCCEEDED. If EVERY leg failed, the run takes the failure path and
  #     canonical is never touched. Measured on
  #     infra/terraform/envs/dev/dag_schedules.auto.tfvars.json, the fetch-leg
  #     histogram over the 25 enabled schedules is
  #     { 0 legs: 1, 1 leg: 18, 2 legs: 4, 3 legs: 1, 5 legs: 1 } -- so for 18 of
  #     25 schedules "one leg failed" IS "the whole acquisition phase failed",
  #     the terminal status stays FAILED and bronze/silver/gate/promote are never
  #     entered, exactly as today. Only the 6 multi-leg families (enso_monthly,
  #     futures_eod_free, production_conab, sagis_weekly, unica, weather_daily)
  #     can ever run degraded. That is the honest scope of this lane and it is
  #     smaller than "the Fetch Map now tolerates a failure" would suggest.
  #
  #  2. DISCRIMINATED, not swallowed. A leg that never RAN is not a blocked
  #     source. The per-leg Catch splits the Batch service faults out by ERROR
  #     NAME; the remaining States.TaskFailed carries the DescribeJobs JobDetail
  #     as its Cause, which is PARSED ONCE (States.StringToJson) and then
  #     classified on NAMED FIELDS of the parsed object -- never on a substring of
  #     the document, which is the defect probe P1 measured on 2026-09-06 and
  #     which the ONE PARSER, TWO READERS banner below records in full. A
  #     container that never became the job (no ExitCode at all, or a StatusReason
  #     / container Reason on the closed infra roster) is INFRA and is NOT
  #     tolerated -- that run goes to FetchInfraFailNotify and FAILS. Only a
  #     container that RAN and chose a non-zero exit -- a source block or a
  #     producer refusal -- is tolerated. Anything unrecognised DEFAULTS to infra,
  #     so the unknown case keeps today's behaviour.
  #
  #  3. FETCH ONLY. Bronze, Silver and Promote render byte-identically to HEAD.
  #
  # THE TOLERANCE BOUNDARY IS A DESCRIPTOR LABEL, AND IT IS ALREADY IMPERFECT.
  # `phase == "Fetch"` keys on the name whoever wrote configs/silver/dags/*.json
  # gave the phase, never on what the task does. Measured across all 34 fetch
  # legs of the 25 enabled schedules: exactly ONE is a derivation step --
  # weather_daily's `chirps_to_bronze` task
  # (configs/silver/dags/weather_daily.json phases[0], command
  # jobs/batch/chirps_to_bronze_task.py, whose own docstring is
  # "CHIRPS COG -> bronze" and which imports
  # leviathan.storage.paths.bronze_weather_key and WRITES the bronze layer).
  # That leg therefore runs BEST-EFFORT the day this lands, so the shipped alert
  # text below must NOT claim "derivation is not best-effort" without naming it.
  # ACCEPTED WIDENING, dated 2026-09-04, real fix DOCKETED: move that task from
  # phases[0] "fetch" to phases[1] "bronze" in the descriptor and regenerate
  # dag_schedules.auto.tfvars.json -- sequenced AFTER the pre-existing
  # psd_monthly descriptor drift, which the same regeneration would sweep up.
  # tests/unit/test_thin_contract_fetch_degraded.py freezes that census at
  # exactly this one leg, so a SECOND fused fetch+derive task fails offline.
  # =========================================================================
  # EVERY fetch-only fragment is a ONE-ELEMENT LIST, and every use is
  # `phase == "Fetch" ? <list> : []` fed through merge(concat(...)...). That is
  # not a stylistic choice: terraform's conditional operator requires BOTH result
  # expressions to have consistent types, so the obvious `phase == "Fetch" ? {
  # Catch = ... } : {}` is REJECTED at validate time ("The true and false result
  # expressions must have consistent types ... includes object attribute Catch,
  # which is absent in the false value"). The list form is the idiom this file
  # already uses for the optional PassRole statement below.

  # The GREEN fetch leg, normalized to a CONSTANT. Three measured reasons:
  #   1. the degraded Choice below string-matches a stringified $.fetchResults,
  #      and an un-normalized array of five Batch job objects is ~8 KB of scan
  #      string carried through every later state and written to the vended log
  #      at level=ALL, on every fire of all 25 families;
  #   2. a uniform `status` key across ok and failed legs is what makes the
  #      marker match unambiguous;
  #   3. NO CONTEXT OBJECT. An earlier draft carried "index.$" =
  #      "$$.Map.Item.Index" here. Nothing reads it (grep: $.fetchResults is
  #      referenced nowhere in the repo outside this module and its test, and the
  #      Choice matches on `status`), and whether the Map context object resolves
  #      inside an INLINE ItemProcessor payload template is NOT settleable
  #      offline -- so it was pure first-fire risk on EVERY GREEN LEG OF ALL 25
  #      FAMILIES. It is gone; a failed leg is named by its `task` (jobdef +
  #      command), which the ItemSelector put in scope. This selector now
  #      dereferences no path at all.
  # The job id / log stream are NOT lost: they stay in the execution history
  # TaskSucceeded event and in /aws/batch, which is exactly where the D-PR-10
  # message already sends the operator.
  fetch_ok_result_selector = {
    "status" = "ok"
  }

  # =========================================================================
  # ONE PARSER, TWO READERS -- A BATCH FAILURE IS CLASSIFIED FROM PARSED FIELDS,
  # NEVER FROM A SUBSTRING OF THE WHOLE CAUSE.
  #
  # THE DEFECT THIS REPLACES, MEASURED ON THE LIVE MACHINE 2026-09-06 23:42Z.
  # Probe execution `laneb-p1-20260906T234214Z` ran two fetch legs on jobdef
  # leviathan-dev-b3-flat-silver rev 37: one `-c "raise SystemExit(1)"`, one
  # `-c "raise SystemExit(0)"`. The exit-1 leg raised States.TaskFailed whose
  # Cause is the DescribeJobs JobDetail (2,631 chars), and that document carries
  # THE JOB'S OWN RETRY POLICY:
  #
  #   "RetryStrategy":{"Attempts":2,"EvaluateOnExit":[
  #     {"Action":"retry","OnStatusReason":"CannotPullContainer*"},
  #     {"Action":"retry","OnStatusReason":"ResourceInitializationError*"},
  #     {"Action":"exit","OnReason":"*"}]}
  #
  # The classifier's first arm was Or[StringMatches "*CannotPullContainer*",
  # "*ResourceInitializationError*", "*OutOfMemory*"] over the WHOLE Cause
  # string. Every jobdef in this estate carries the D-SG retry matrix
  # (infra/terraform/modules/batch/main.tf, `producer_retry_rules`), so EVERY
  # Batch Cause in this estate contains those substrings, the infra arm ALWAYS
  # won, and the source arm (`*"ExitCode":*`) was UNREACHABLE CODE. Measured
  # outcome: history events 13-15 ClassifyFailureFetch -> RecordInfraFailureFetch,
  # then FetchInfraFailNotify and terminal FAILED / SilverPipelineInfraFailed --
  # on a plain exit-1 SOURCE failure, while the green leg's TaskSucceeded
  # (event 25) showed the rest of the lane sound. The tolerance this lane exists
  # to grant was granted to NOTHING. The same substring roster sat one arm later
  # in the gate's classifier; see ClassifyGateFailure for what it cost there.
  #
  # WHY NO SUBSTRING ROSTER CAN BE PATCHED INTO CORRECTNESS. The Cause is the
  # whole JobDetail: RetryStrategy, the RESOLVED ContainerOverrides Command, the
  # resolved Environment, image URIs, role ARNs, tags. None of that text is
  # written by this module and none of it is bounded by it -- a roster tuned
  # against today's document is one jobdef edit away from the same failure. The
  # discriminator has to be a FIELD, so the Cause is parsed ONCE with
  # States.StringToJson and every arm below compares a NAMED path of the result.
  # =========================================================================

  # The scratch key both readers parse into. The gate parses at TOP level and a
  # fetch leg parses inside the Map ITEM -- separate scopes -- so ONE name serves
  # both and the guard objects below render byte-identically for the two readers,
  # which is what "one parser, two readers" has to mean to be a drift fence.
  # `.job` is a wrapper key, not decoration: a Pass `Parameters` must be a JSON
  # OBJECT, so an intrinsic's result cannot sit at the payload root.
  batch_cause_root = "$.batchCause.job"

  # THE PARSE. `ResultPath` MERGES it in, preserving $.task and $.error for the
  # record states and $.family for the notifiers; each reader adds its own `Next`.
  #
  # HONEST RESIDUAL, AND THE REASON FOR THE PRECONDITION BELOW. A Pass state
  # CANNOT carry a Catch -- ASL allows Retry/Catch on Task, Parallel and Map only,
  # which this file already states three times -- so States.StringToJson on a
  # non-JSON Cause would fail the execution with NO notification, the exact trade
  # D-PR-10 refused when it declined to parse at all. The Catch is therefore
  # replaced by a PRECONDITION: this state is reachable only through a Choice arm
  # that has already established the error NAME (States.TaskFailed is the only
  # name whose Cause is a DescribeJobs document; a Batch.* service fault carries
  # a plain sentence) and that the Cause is a JSON object literal. For the
  # non-JSON class a precondition is strictly stronger than a Catch: that class
  # never reaches the parse at all, instead of reaching it and being recovered.
  # What remains uncovered is a Cause that is brace-wrapped and still malformed,
  # which AWS does not produce for a batch:submitJob.sync States.TaskFailed.
  batch_cause_parse_pass = {
    Type       = "Pass"
    Parameters = { "job.$" = "States.StringToJson($.error.Cause)" }
    ResultPath = "$.batchCause"
  }

  # The precondition. `{*}` is a SHAPE test, not a content test: it says the Cause
  # is a JSON object literal, and it is the last thing standing between a
  # malformed Cause and an uncatchable intrinsic failure.
  batch_cause_is_parseable = [
    { Variable = "$.error.Cause", IsPresent = true },
    { Variable = "$.error.Cause", StringMatches = "{*}" },
  ]

  # THE INFRA ROSTER -- CLOSED AND CITED -- matched as PREFIXES of two NAMED
  # fields of the parsed JobDetail, never as substrings of the document.
  #
  #   CannotPullContainer*         infra/terraform/modules/batch/main.tf
  #                                `producer_retry_rules` (D-SG G1-3):
  #                                on_status_reason = "CannotPullContainer*".
  #                                Estate history: five in-window events
  #                                2026-08-02..08-13, plus the 2026-07-17 and
  #                                2026-07-23 digest-eviction incidents that
  #                                scripts/ops/check_ecr_pinned_digests.py exists
  #                                for.
  #   ResourceInitializationError* same file, Class B. The estate's one sample is
  #                                modis-fetch 2026-07-17, "unable to retrieve
  #                                secret from asm: invalid character E ...".
  #   OutOfMemory*                 same file, Class J -- and note that rule keys
  #                                on on_REASON, not on_status_reason, because the
  #                                live sample (evidence-build rev 32, 2026-08-02,
  #                                "OutOfMemoryError: container killed due to
  #                                memory usage") arrives in the CONTAINER REASON.
  #                                An OOM-killed container DID run and DID exit
  #                                (137), so its StatusReason is the ordinary
  #                                "Essential container in task exited". That is
  #                                why the Reason arm must be tested BEFORE the
  #                                ran-to-an-exit arm, and why a classifier that
  #                                read StatusReason alone would silently
  #                                reclassify every OOM as a blocked source.
  #   Task failed to start*        the ECS stopped-reason Batch copies into
  #   DockerTimeoutError*          statusReason when a task never reached RUNNING.
  #                                NOT OBSERVED IN THIS ESTATE, and named as such.
  #                                Both sit on the INFRA side only -- the
  #                                NOT-tolerated side for the fetch reader, the
  #                                no-verdict side for the gate -- so a wrong
  #                                entry here can only make a classifier MORE
  #                                conservative, never tolerate more.
  #
  # The roster is CLOSED: anything not on it falls to the reader's Default, and
  # both Defaults are today's behaviour.
  batch_cause_infra_reason_prefixes = [
    "CannotPullContainer*",
    "ResourceInitializationError*",
    "OutOfMemory*",
    "Task failed to start*",
    "DockerTimeoutError*",
  ]

  # THE CONTAINER-REASON FIELD IS AN INFERENCE, AND THIS LANE NO LONGER RESTS ON IT.
  # (Review finding 2026-09-07, MAJOR. Closed with code, not with a comment.)
  #
  # WHAT IS MEASURED: the P1 Cause's top-level `Container` has SIXTEEN keys --
  # Command, Environment, ExecutionRoleArn, ExitCode, FargatePlatformConfiguration,
  # Image, JobRoleArn, LogStreamName, MountPoints, NetworkConfiguration,
  # NetworkInterfaces, ResourceRequirements, Secrets, TaskArn, Ulimits, Volumes --
  # and `Reason` is NOT one of them, in either casing. `Attempts[0].Container` has
  # four: ExitCode, LogStreamName, NetworkInterfaces, TaskArn. Neither carries a
  # container reason, because that run had none (the container chose exit 1).
  #
  # WHAT IS INFERRED, TWICE OVER. That an OOM's reason text arrives (a) spelled
  # `Reason` -- from the PascalCase convention the whole measured Cause obeys, while
  # the DescribeJobs API itself returns lowerCamelCase `reason`, which is the
  # spelling the DSG-TAIL F1 probe read when it recorded "container reason None" --
  # and (b) at the TOP level rather than only inside `Attempts[-1]`, which a Choice
  # `Variable` cannot address at all (not a single-node reference path). Two
  # independent guesses, neither observable offline, and the OOM fixture was written
  # to match the rule, so classifier and fixture would have moved together.
  #
  # THE COST OF GUESSING WRONG WAS A REGRESSION, not merely an unproven improvement.
  # Measured against the rendered rules: re-key that fixture to `reason` and the
  # fetch reader returns RecordSourceFailureFetch -- an OOM-killed leg TOLERATED,
  # Bronze entered on an incomplete fetch, which is the one invariant this lane
  # rests on. HEAD substring-matched "*OutOfMemory*" over the WHOLE Cause, so HEAD
  # was robust to the key name and returned RecordInfraFailureFetch.
  #
  # THE FIX: the OOM class is now carried by a field that IS measured -- the exit
  # code -- and the reason arms are kept only as a widening that cannot subtract.
  #
  #   1. NO EXIT CODE AT ALL. The top-level `Container` of a DescribeJobs
  #      JobDetail is the LATEST attempt -- measured on the P1 Cause, where the
  #      top-level Container.ExitCode (1) and StatusReason are byte-identical to
  #      the single Attempts[0] entry's. No ExitCode there means no container ever
  #      ran to an exit, i.e. the job never became a job. This arm is also why
  #      "no attempt carries an ExitCode" needs no array indexing: a Choice
  #      `Variable` must be a single-node reference path, and `Attempts[-1]` is
  #      not one. IsPresent resolves the WHOLE path, so a job detail carrying no
  #      `Container` node at all takes this arm too -- the same reading, not a
  #      different one.
  #   2. THE CONTAINER DID NOT CHOOSE ITS EXIT. 128+N is the signal convention and
  #      137 = 128 + SIGKILL(9) is what an OOM-killed Fargate container reports:
  #      the ECS agent stops the task and the process never returns a value of its
  #      own. This arm reads `Container.ExitCode`, the ONE field this shape is
  #      MEASURED to carry, so it holds whatever AWS calls -- or omits -- the
  #      reason text. It cannot steal a producer's verdict: the estate's chosen
  #      exit codes, measured over jobs/, src/leviathan/ and scripts/, are
  #      {0,1,2,3,5,6,7} plus the gate's D-PR-8 vocabulary {64,70,71,72}. The
  #      maximum is 72 and NOTHING reaches 128.
  #   3/4/5. The roster, as a PREFIX of StatusReason and of the container reason
  #      under BOTH spellings. StatusReason is measured present. The two reason
  #      paths are the inference above, kept because a widening on the INFRA side
  #      can only make a reader MORE conservative -- fetch's infra side is the
  #      NOT-tolerated side, the gate's is the no-verdict side -- and now that arm
  #      2 carries the OOM class, being wrong about both spellings costs nothing.
  #      Every field here is optional (the DSG-TAIL F1 probe recorded a real
  #      failure with container reason None), so each is IsPresent-guarded before
  #      it is compared -- the house idiom; an unguarded compare against a missing
  #      path is a States.Runtime failure that no Catch can reach.
  #
  # WHAT IS STILL NOT PROVEN, stated because this file does not launder guesses:
  # arms 3-5 remain unexercised by any measured artifact, and the OOM fixtures are
  # SYNTHETIC in all three spellings. The claim is only that the lane is now
  # NO WORSE THAN HEAD on the infra needle whatever the spelling turns out to be,
  # and tests/unit/test_thin_contract_fetch_degraded.py pins exactly that -- as a
  # property of the raw Cause TEXT, so it cannot move with the rule the way the
  # fixture did.
  #
  # 128 = the POSIX signal-exit floor (128 + N for signal N). Named so the pin that
  # measures the estate's exit codes against it can read the same number this does.
  batch_cause_signal_exit_floor = 128

  # WHY EVERY NUMERIC COMPARISON BELOW IS `IsNumeric`-GUARDED AS WELL AS `IsPresent`-GUARDED.
  # (Review finding 2026-09-07, MINOR. Closed with code.)
  #
  # Until 2026-09-06 this document contained ZERO numeric comparators -- measured on the
  # rendered artifact, HEAD is { IsPresent 7, StringMatches 21, StringEquals 4 }. The parsed
  # readers introduced eight, and all eight read ONE field, `Container.ExitCode`, which is not
  # written by this module: it is whatever `States.StringToJson` put there, i.e. whatever AWS
  # printed into the Cause string. The house idiom guards a compare with `IsPresent` because an
  # unguarded compare against a MISSING path is a States.Runtime failure that no Catch can
  # reach -- and a Choice state cannot carry a Catch at all, so such a failure kills the
  # execution with no notification, which is the exact silent class this lane exists to narrow.
  # `IsPresent` does not cover a present-but-WRONG-TYPE value, and ASL's behaviour when a
  # Numeric* comparator meets a string is asserted nowhere in this repo.
  #
  # THE RISK IS SMALL AND THIS FILE SAYS SO: `exitCode` is modelled as an Integer by the Batch
  # API, and it is an int in the one measured artifact (the P1 Cause) and in all eight fixtures.
  # The guard is here because it is FREE and it is the same shape as the presence guard already
  # in use -- `IsNumeric` is an ASL data-test expression like `IsPresent` -- not because a
  # string ExitCode has ever been seen. With it, a non-numeric ExitCode simply fails to match
  # the arm and falls through to the reader Default, which on both readers is today behaviour.
  batch_cause_exit_code_is_numeric = {
    Variable  = "${local.batch_cause_root}.Container.ExitCode"
    IsNumeric = true
  }

  batch_cause_container_reason_paths = [
    "${local.batch_cause_root}.Container.Reason",
    "${local.batch_cause_root}.Container.reason",
  ]

  batch_cause_infra_guards = concat(
    [
      { Variable = "${local.batch_cause_root}.Container.ExitCode", IsPresent = false },
      {
        And = [
          { Variable = "${local.batch_cause_root}.Container.ExitCode", IsPresent = true },
          local.batch_cause_exit_code_is_numeric,
          { Variable = "${local.batch_cause_root}.Container.ExitCode", NumericGreaterThanEquals = local.batch_cause_signal_exit_floor },
        ]
      },
      {
        And = [
          { Variable = "${local.batch_cause_root}.StatusReason", IsPresent = true },
          { Or = [for p in local.batch_cause_infra_reason_prefixes :
          { Variable = "${local.batch_cause_root}.StatusReason", StringMatches = p }] },
        ]
      },
    ],
    [for path in local.batch_cause_container_reason_paths : {
      And = [
        { Variable = path, IsPresent = true },
        { Or = [for p in local.batch_cause_infra_reason_prefixes :
        { Variable = path, StringMatches = p }] },
      ]
    }],
  )

  # POSITIVE EVIDENCE THAT THE CONTAINER RAN AND CHOSE ITS OWN EXIT. Two measured
  # samples, two different exit codes, ONE StatusReason:
  #   exit 1 -- probe laneb-p1-20260906T234214Z, 2026-09-06, "Essential container
  #             in task exited";
  #   exit 2 -- job cb151695 on b3-flat-silver, the DSG-TAIL F1 probe recorded in
  #             infra/terraform/modules/batch/main.tf: container reason None, the
  #             SAME StatusReason, terminal after one attempt.
  # Each reader adds its own exit-code test: the fetch lane tolerates ANY non-zero
  # exit (a blocked source or a producer refusal), the gate lane reads the exact
  # code out of the D-PR-8 vocabulary. Both of those are NUMERIC comparators, so the
  # `IsNumeric` guard is carried HERE, in the shared prefix every one of them concats
  # onto -- one place, three rendered arms (fetch source, gate refusal, gate
  # no-verdict), and the And short-circuits in order so the guard always precedes the
  # compare. See `batch_cause_exit_code_is_numeric` above for why.
  batch_cause_ran_to_an_exit_guards = [
    { Variable = "${local.batch_cause_root}.Container.ExitCode", IsPresent = true },
    local.batch_cause_exit_code_is_numeric,
    { Variable = "${local.batch_cause_root}.StatusReason", IsPresent = true },
    { Variable = "${local.batch_cause_root}.StatusReason", StringMatches = "Essential container in task exited*" },
  ]

  # The Batch faults that arrive under their OWN error name: SubmitJob never
  # produced a running job, or the .sync wait timed out. "Never ran / no verdict"
  # by construction, no Cause parsing needed. Same four names the Gate's D-PR-10
  # infra arm uses, so the two agree by construction.
  fetch_infra_error_names_batch = ["Batch.ServerException", "Batch.TooManyRequestsException",
  "States.Timeout", "Batch.AWSBatchException"]

  fetch_only_batch_overrides = [{
    ResultSelector = local.fetch_ok_result_selector
    Catch = [
      {
        ErrorEquals = local.fetch_infra_error_names_batch
        # ResultPath (not the default) is load-bearing: it MERGES the caught error
        # under $.error and PRESERVES the item input { family, task }, which is
        # what the records below need in order to NAME the leg that failed. The
        # default would REPLACE the item input with the error object.
        ResultPath = "$.error"
        Next       = "RecordInfraFailureFetch"
      },
      {
        ErrorEquals = ["States.ALL"]
        ResultPath  = "$.error"
        Next        = "ClassifyFailureFetch"
      },
    ]
  }]

  # GLUE FETCH LEGS ARE NOT TOLERATED, and that is the fail-closed choice, not an
  # oversight. Measured: 34 of 34 fetch legs across the 25 enabled schedules are
  # integration=batch (the estate's only two Glue legs are weather_daily's bronze
  # and silver), so no Glue fetch Cause shape has ever been observed here -- and a
  # glue:startJobRun.sync Cause carries no "ExitCode", which is the discriminator
  # the Batch classifier uses. Rather than tolerate a leg on a guessed Cause
  # shape, this arm records it as INFRA, which routes the run to the failure path
  # exactly as today. The arm exists so a future Glue fetch leg fails LOUD and
  # NAMED instead of throwing out of the Map, and it must carry its own probe
  # before anyone promotes it to tolerated.
  fetch_only_glue_overrides = [{
    ResultSelector = local.fetch_ok_result_selector
    Catch = [{
      ErrorEquals = ["States.ALL"]
      ResultPath  = "$.error"
      Next        = "RecordInfraFailureFetch"
    }]
  }]

  fetch_only_extra_states = [{
    ClassifyFailureFetch     = local.fetch_failure_classifier
    ParseBatchCauseFetch     = merge(local.batch_cause_parse_pass, { Next = "ClassifyBatchCauseFetch" })
    ClassifyBatchCauseFetch  = local.fetch_parsed_cause_classifier
    RecordSourceFailureFetch = local.fetch_failure_record["source"]
    RecordInfraFailureFetch  = local.fetch_failure_record["infra"]
  }]

  # THE ERROR-NAME GATE. This is arm ZERO of the classification and it is a NAME
  # test, not a content test: the per-leg Catch splits the four Batch service
  # faults out already, but its second arm is States.ALL, so Batch.ClientException
  # (probe P2's shape: a jobdef that does not exist), States.Permissions and any
  # future name land here too, and NONE of those carries a DescribeJobs document.
  # Only States.TaskFailed does. A leg that arrives under any other name never
  # reaches the parse and takes the Default, which is NOT tolerated -- today's
  # behaviour for exactly that class, unchanged.
  fetch_failure_classifier = {
    Type = "Choice"
    Choices = [
      {
        And = concat([
          { Variable = "$.error.Error", IsPresent = true },
          { Variable = "$.error.Error", StringEquals = "States.TaskFailed" },
        ], local.batch_cause_is_parseable)
        Next = "ParseBatchCauseFetch"
      },
    ]
    Default = "RecordInfraFailureFetch"
  }

  # THE READER. ORDER IS LOAD-BEARING, and the gate's reader now uses the SAME one:
  #   arms 1-5 THE SHARED INFRA ARMS, first, because infra is the NOT-tolerated
  #          side here and because an OOM-killed container exits 137 under the
  #          ordinary "Essential container in task exited" -- so every one of them
  #          MUST precede the ran-to-an-exit arm or an OOM is tolerated as a
  #          blocked source. Arm 2 (the signal floor) is the one that carries that
  #          class on measured evidence; arms 4 and 5 are the reason-text widening.
  #   arm 6  SOURCE: the container ran and chose a NON-ZERO exit BELOW the signal
  #          floor. That is a blocked source or a producer refusal, and it is the
  #          only thing this lane tolerates.
  #   Default INFRA. An unrecognised shape is NOT tolerated, so the unknown case
  #          keeps today's behaviour (the run fails, canonical untouched) instead
  #          of continuing on a leg nobody classified. The pin
  #          test_an_unrecognised_cause_reaches_the_default_behaviourally drives a
  #          Cause through this state that matches no arm, so the Default is proven
  #          by EVALUATION and not only by a string assertion over the HCL.
  # A Choice adds no compute and cannot fail closed-mouthed.
  fetch_parsed_cause_classifier = {
    Type = "Choice"
    Choices = concat(
      [for guard in local.batch_cause_infra_guards :
      merge(guard, { Next = "RecordInfraFailureFetch" })],
      [{
        And = concat(local.batch_cause_ran_to_an_exit_guards, [
          { Variable = "${local.batch_cause_root}.Container.ExitCode", NumericGreaterThan = 0 },
        ])
        Next = "RecordSourceFailureFetch"
      }],
    )
    Default = "RecordInfraFailureFetch"
  }

  # THE FAILED LEG, recorded as the item's NORMAL result -- the item ENDS, it does
  # not throw, so the Map completes and the family object survives into the scan.
  # `class` is what the top-level Choice routes on: "source" may be tolerated,
  # "infra" never is.
  #
  # `cause` carries States.JsonToString($.error), i.e. the WHOLE caught error
  # object (Error + Cause), never $.error.Cause. Deliberate: Cause is OPTIONAL on
  # some error names, and a payload template that dereferences an absent path
  # raises States.Runtime -- which no Catch can reach, so a Cause-less fetch
  # failure would FAIL the execution instead of degrading it. Same trap the
  # D-PR-10 comment names for the gate classifier.
  #
  # HONEST RESIDUAL, stated where it is created: a Pass state cannot carry a
  # Catch, so these two records and ScanFetchResults below are UNPROTECTED
  # payload-template sites -- FIVE of them since the 2026-09-07 parse landed, not
  # three. The count is written out because it went UP and an earlier draft of this
  # comment did not notice:
  #   1. ScanFetchResults        top-level, traversed by all 25 families on EVERY
  #                              fire (States.JsonToString($.fetchResults));
  #   2. RecordSourceFailureFetch \ in the Fetch iterator, traversed only on a
  #   3. RecordInfraFailureFetch  / failed leg;
  #   4. ParseBatchCauseGate      TOP-LEVEL, added 2026-09-06, traversed only on a
  #                              States.TaskFailed gate failure;
  #   5. ParseBatchCauseFetch     in the Fetch iterator, added 2026-09-06,
  #                              traversed only on a failed batch leg.
  # 4 and 5 are the shared `batch_cause_parse_pass`; both dereference $.error.Cause
  # through States.StringToJson, and BOTH are protected by a PRECONDITION instead of
  # a Catch -- the error-NAME arm plus the `{*}` shape guard, which is strictly
  # stronger than a Catch for the non-JSON class because that class never reaches
  # the parse. 1-3 have no such precondition: every path they dereference is present
  # by construction ($.task from the ItemSelector, $.error and $.error.Error from the
  # Catch that just wrote them, $.fetchResults from the Map ResultPath) and none uses
  # a context object. That is a bounded argument, not a guarantee -- which is exactly
  # why this lane does NOT claim "zero silences created" anywhere.
  fetch_failure_record = {
    for cls in ["source", "infra"] : cls => {
      Type = "Pass"
      Parameters = {
        "status"  = "failed"
        "class"   = cls
        "task.$"  = "$.task"
        "error.$" = "$.error.Error"
        "cause.$" = "States.JsonToString($.error)"
      }
      End = true
    }
  }

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
      # LANE B: merge() so the classifier and the two failure-recording Pass
      # states exist ONLY in the Fetch processor. INLINE Map iterator states share
      # ONE global name space (AWS DUPLICATE_STATE_NAME), so they carry the phase
      # suffix like every other stamped state -- and because they are stamped for
      # Fetch alone there is exactly one ClassifyFailureFetch, one
      # RecordSourceFailureFetch and one RecordInfraFailureFetch.
      States = merge(concat([{
        "RouteIntegration${phase}" = {
          Type = "Choice"
          Choices = [{
            Variable     = "$.task.integration"
            StringEquals = "glue"
            Next         = "GlueSync${phase}"
          }]
          Default = "BatchSync${phase}"
        }

        "BatchSync${phase}" = merge(concat([{
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
          # D-PR-9: retry authority moves DOWN to the jobdef, where evaluateOnExit can
          # discriminate a permanent digest eviction from a transient container-start
          # fault. `States.TaskFailed` is what batch:submitJob.sync raises for ANY
          # FAILED job -- a gate refusal, an exit 1, an OOM, a CannotPullContainerError
          # -- so retrying on it is retrying on "something went wrong", which is not a
          # class. It is REMOVED here.
          #
          # MEASURED, not theoretical (2026-08-04, 393 jobs across both queues): this
          # rule is why every deterministic producer failure in the archive appears as
          # a TRIPLET ~60 s and ~120 s apart, each with jobdef `attempts: 1` --
          # b3-flat-silver rev 23 at 09:36:42 / 09:38:59 / 09:42:17Z; databento-fetch
          # rev 1 x3 on 07-30 and again x3 on 07-31; futures-eod-silver rev 2 x3;
          # silver-publisher-runner rev 22 x3 and rev 23 x3; nasa-power-backfill rev 5
          # x3 on 08-02 AND x3 on 08-03 (all CannotPullContainerError on an evicted
          # digest, i.e. three guaranteed-identical failures per fire).
          #
          # ORDERING IS LOAD-BEARING (D-PR-41): this narrowing must be applied BEFORE
          # the jobdef retry matrices, never after. Arming jobdef `attempts: 3` while
          # this still retries on States.TaskFailed gives 3 x 3 = 9 attempts per fire.
          # Narrowing first gives 1 SFN attempt x whatever the jobdef does.
          Retry = [{
            ErrorEquals     = ["States.Timeout", "Batch.ServerException", "Batch.TooManyRequestsException"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }]
          End = true
          }],
          # LANE B, FETCH ONLY. The Retry list above is NOT touched: a Catch is not
          # a retry, and D-PR-9's narrowed ErrorEquals is unchanged on all four
          # phases. What changes is only where a FETCH leg goes AFTER its retries
          # are exhausted -- into the two-arm Catch that separates a leg which
          # never ran from a leg that ran and exited non-zero, and then to a Pass
          # that records the failure as the item result instead of throwing out of
          # the Map. Attempt arithmetic per blocked leg is unchanged: the jobdef
          # evaluateOnExit matrix runs inside Batch first (exit 1 -> EXIT, ONE
          # attempt), the .sync task fails, the narrowed SFN Retry does not match
          # States.TaskFailed, and only then does this Catch fire. Total: 1.
          phase == "Fetch" ? local.fetch_only_batch_overrides : []
        )...)

        "GlueSync${phase}" = merge(concat([{
          Type     = "Task"
          Resource = "arn:aws:states:::glue:startJobRun.sync"
          Parameters = {
            "JobName.$"   = "$.task.glue_job"
            "Arguments.$" = "$.task.arguments"
          }
          # D-PR-9 as amended by D-PR-40. Each phase Map has TWO task states, not one --
          # the RouteIntegration Choice fans to BatchSync AND GlueSync -- so narrowing
          # "the producer Map states' Retry" touches EIGHT Retry blocks, not four, and
          # this half must NOT take the Batch narrowed list verbatim:
          #
          #   * `States.TaskFailed` is dropped for the same reason as the Batch half:
          #     it fires on any failed Glue run, which is not a class.
          #   * `Glue.ConcurrentRunsExceededException` is KEPT. It is the one genuinely
          #     retriable Glue transient, and applying the Batch list here would have
          #     DELETED it -- regressing concurrency handling on weather_daily, the
          #     estate's most-fired family (cron(0 8 * * ? *)) and the only family with
          #     Glue legs at all (leviathan-dev-raw-to-bronze-nasa-power +
          #     leviathan-dev-bronze-to-silver-nasa-power, both MaxRetries=0).
          #   * `Batch.*` errors are meaningless on a glue:startJobRun.sync task, so the
          #     Batch service-fault pair is deliberately absent rather than copied.
          #
          # Retry authority cannot move down to a jobdef here: Glue has no jobdef and no
          # evaluateOnExit, so this narrowed list IS the whole retry posture for Glue.
          Retry = [{
            ErrorEquals     = ["States.Timeout", "Glue.ConcurrentRunsExceededException"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }]
          End = true
          }],
          # D-PR-40 still holds: Glue.ConcurrentRunsExceededException stays in the
          # Retry list above, untouched. No Glue leg is scheduled in ANY family's
          # fetch phase today (measured: 34 of 34 fetch tasks across 25 schedules
          # are integration=batch; the estate's only two Glue legs are
          # weather_daily's bronze and silver). This arm exists so a future Glue
          # fetch leg fails LOUD and NAMED rather than throwing out of the Map --
          # it records INFRA, i.e. NOT tolerated, because no Glue Cause shape has
          # been observed here and a glue:startJobRun.sync Cause carries no
          # ExitCode to classify on. See fetch_only_glue_overrides above.
          phase == "Fetch" ? local.fetch_only_glue_overrides : []
        )...)
        }],
        phase == "Fetch" ? local.fetch_only_extra_states : []
      )...)
    }
  }

  # ItemSelector shared by every phase Map -- carries family into item scope.
  map_item_selector = {
    "family.$" = "$.family"
    "task.$"   = "$$.Map.Item.Value"
  }

  # =========================================================================
  # D-PR-10 -- "THE GATE REFUSED" AND "THE GATE NEVER RAN" ARE NOT THE SAME EMAIL.
  #
  # Until now every Gate failure took ONE Catch (States.ALL -> FailNotify) and produced the sentence
  # "Family {} failed the silver_rebuild_gate", which is FALSE for an infra death: a CannotPull, an
  # ASM/ResourceInitializationError, an OOM or a crashed interpreter never judged any data. That is
  # the census class D-iii shape (a `ModuleNotFoundError: psycopg` in the gate image read to the
  # operator exactly like a data refusal, and the week went into the config).
  #
  # WHY THIS NEEDS MORE THAN A SECOND `Catch` KEYED ON ERROR NAMES. Only the SubmitJob API faults
  # (Batch.*) and a .sync timeout arrive under their own error names. A gate job that STARTS and
  # dies -- and every exit code the gate itself produces -- arrives as **States.TaskFailed**, the
  # same name as a refusal. Measured 2026-08-04 on execution
  # `fred-refire-cotfence-20260804T071403Z` (history event 28, resource batch:submitJob.sync):
  #
  #   error = "States.TaskFailed"
  #   cause = "{\"Attempts\":[{\"Container\":{\"ExitCode\":1,\"LogStreamName\":...}}],
  #             ...,\"Container\":{...,\"ExitCode\":1,\"FargatePlatformConfiguration\":{...}},
  #             \"StatusReason\":\"Essential container in task exited\",...}"
  #
  # So the discriminator IS available -- as compact JSON inside the Cause string. Until 2026-09-06
  # the classifier below STRING-MATCHED that string, on the argument that a Pass state cannot carry
  # a `Catch` and so a Cause that failed to parse would fail the execution with no notification at
  # all. The Pass-cannot-Catch half of that argument is still true. THE STRING-MATCHING HALF WAS
  # WRONG, AND THE SAME DEFECT THAT MADE THE LANE B FETCH CLASSIFIER UNREACHABLE (see the ONE PARSER,
  # TWO READERS banner above) SAT ONE ARM LATER HERE.
  #
  # THE GATE'S CAUSE IS THE SAME SHAPE, SO IT CARRIED THE SAME DEFECT. The Gate is a
  # batch:submitJob.sync task, its States.TaskFailed Cause is the same DescribeJobs JobDetail, and
  # that document embeds the gate jobdef's own `RetryStrategy.EvaluateOnExit` -- which, like every
  # jobdef in this estate, names "CannotPullContainer*" and "ResourceInitializationError*". So the
  # no-verdict arm's `container_never_started_patterns` matched EVERY gate Cause. What saved the
  # common case is only ORDER: the refusal arm (exit 1) is tested first, so a real refusal still
  # routed to FailNotify. What it cost is the DEFAULT: any gate exit code outside the D-PR-8
  # vocabulary -- exit 2 is a measured shape, DSG-TAIL F1 probe job cb151695 on b3-flat-silver,
  # "container reason None, statusReason 'Essential container in task exited'" -- fell through the
  # exit-code patterns into the container-never-started patterns and was mailed as "NO GATE VERDICT"
  # although the container had run and chosen its exit. `Default = "FailNotify"`, the documented
  # unknown case, was unreachable for every Cause the estate can actually produce.
  #
  # FIXED THE SAME WAY, WITH THE SAME PARSER: ClassifyGateFailure is now the error-name/shape gate,
  # ParseBatchCauseGate is the shared `batch_cause_parse_pass`, and ClassifyBatchCauseGate reads the
  # SAME guard objects the fetch reader reads (`batch_cause_infra_guards`,
  # `batch_cause_ran_to_an_exit_guards`) with the gate's own exit-code vocabulary bolted on. One
  # parser, two readers: the two cannot drift because they are the same rendered objects.
  #
  # SAFETY PROPERTY OF THE CLASSIFIER, UNCHANGED: every comparison is guarded by `IsPresent` (the
  # documented idiom for an optional path; an unguarded comparison against a missing path is a
  # States.Runtime failure that no Catch can reach), and the Default is FailNotify -- today's
  # behaviour. An unrecognised cause therefore degrades to exactly what happens now. The classifier
  # can only IMPROVE attribution; it cannot lose a notification.
  #
  # WHICH ATTEMPT IS BEING READ, settled. It used to be that with `attempts: 2` a Cause could carry
  # TWO attempts (attempt 1 exit 72 -> retried -> attempt 2 exit 1) and a substring test could not
  # tell which was last. Parsing settles that: the JobDetail's TOP-LEVEL `Container` IS the latest
  # attempt (measured on the P1 Cause, where it is byte-identical to the single Attempts[0] entry).
  #
  # ORDER IS LOAD-BEARING IN BOTH READERS, AND BOTH NOW USE THE SAME ORDER. An earlier draft of
  # this comment claimed that under parsed fields the arms are mutually exclusive, so the order was
  # "a statement of intent rather than a safety property", and used that to justify testing refusal
  # first here while the fetch reader tested infra first. THE CLAIM WAS FALSE, and the counterexample
  # is one Cause: ExitCode 1 + StatusReason "Essential container in task exited" + a container reason
  # of "DockerTimeoutError: Could not transition to created". Under the old asymmetry the fetch
  # reader called that INFRA and the gate reader called it a REFUSAL -- the two readers disagreeing
  # on one document, which is the exact drift "one parser, two readers" exists to prevent. The shared
  # infra arms are therefore tested FIRST in BOTH readers, so a container whose reason says it never
  # properly started is never credited with a verdict it cannot have produced. The two readers still
  # differ where they are SUPPOSED to -- in what the non-infra side means (a tolerated blocked source
  # vs a real gate refusal) and in their Defaults: the fetch reader's is NOT-TOLERATED, the gate's is
  # FailNotify.
  #
  # The exit codes are the vocabulary in jobs/audit/silver_rebuild_gate.py (D-PR-8):
  #   1 REFUSAL (a decision about data)      | 64 usage | 70 internal crash
  #   71 image/config preflight fence        | 72 baseline fetch (the only retryable code)
  # tests/unit/test_gate_exit_vocabulary.py pins these two constants against that module, so the
  # pair cannot drift.
  # =========================================================================
  gate_refusal_exit_code = 1

  gate_no_verdict_exit_codes = [64, 70, 71, 72]

  # The gate's reader over the shared parse. SHARED INFRA ARMS FIRST -- the SAME
  # order the fetch reader uses -- then the gate's own vocabulary: refusal, then the
  # non-verdict codes. Default keeps today's route.
  #
  # THE ORDER USED TO BE THE OTHER WAY ROUND HERE, and the comment above justified
  # the asymmetry by claiming the parsed arms are mutually exclusive so order cannot
  # matter. THAT CLAIM WAS FALSE and is corrected in the banner above. This reader
  # now agrees with the fetch reader on every Cause, which is what "one parser, two
  # readers" is supposed to buy.
  gate_parsed_cause_classifier = {
    Type = "Choice"
    Choices = concat(
      [for guard in local.batch_cause_infra_guards :
      merge(guard, { Next = "InfraFailNotify" })],
      [
        {
          And = concat(local.batch_cause_ran_to_an_exit_guards, [
            { Variable = "${local.batch_cause_root}.Container.ExitCode", NumericEquals = local.gate_refusal_exit_code },
          ])
          Next = "FailNotify"
        },
        {
          And = concat(local.batch_cause_ran_to_an_exit_guards, [
            { Or = [for c in local.gate_no_verdict_exit_codes :
            { Variable = "${local.batch_cause_root}.Container.ExitCode", NumericEquals = c }] },
          ])
          Next = "InfraFailNotify"
        },
      ],
    )
    Default = "FailNotify" # unknown cause == today's behaviour, never a lost notification
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
        # LANE B / D-PR-44 (Fetch half): the four phase Maps carry Retry but NO
        # Catch, so until now a Map that died for a reason the per-item Catch
        # cannot see failed the EXECUTION with no notification at all -- the owner
        # learned it only from the sfn-executions-failed alarm, which is itself
        # alarm_actions = [] (D-PR-12 / D-ALARM-1).
        #
        # WHAT THIS CATCH COVERS, stated narrowly on purpose. It reaches the
        # Map-level failures AWS raises under a CATCHABLE error name --
        # States.DataLimitExceeded is the measured one. It does NOT reach a
        # runtime path/intrinsic fault: this same file states three separate times
        # that no Catch reaches that class, and an earlier draft of THIS comment
        # claimed the opposite. So this arm NARROWS the silent class; it does not
        # close it. Nothing in Lane B may be cited to demote sfn-executions-failed
        # further, and D-PR-44 still requires the Catch on all four phases plus
        # one OBSERVED producer failure first.
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "FailNotify"
        }]
        Next = "ScanFetchResults"
      }

      # --- LANE B: DEGRADED IS LOUD, AND BOUNDED. -----------------------------
      # Map results are an ARRAY, and a Choice Variable must be a REFERENCE PATH
      # (exactly one node -- no [*], no filter expression), so "did any item fail"
      # and "did any item succeed" cannot be asked of $.fetchResults directly.
      # They are asked of a stringified copy instead: the same idiom D-PR-10
      # already uses to read the gate Cause, for the same reason -- the
      # discriminator is available as text or not at all. States.ArrayContains is
      # not usable here: it tests EXACT element equality, and no two failed legs
      # are equal.
      #
      # THE MARKERS CANNOT BE FORGED FROM CONTENT. Inside States.JsonToString the
      # nested quotes of `task` and `cause` are backslash-escaped, so an
      # UNESCAPED "status":"ok" / "status":"failed" / "class":"infra" can only be
      # a top-level key this module wrote.
      #
      # SIZE: a green five-leg family renders {"status":"ok"} x 5 == ~85 bytes of
      # scan. A failed leg adds its task plus the whole caught error object
      # (~1-2 KB; a Batch Cause is the full DescribeJobs JobDetail). The
      # worst DEGRADED case is now 4 of 5 legs failed -- the all-failed case is
      # bounded away to FailNotify below and never reaches a notifier that carries
      # the scan -- which keeps this well inside the 256 KB transition payload
      # limit and the 262,144-byte SNS message cap.
      ScanFetchResults = {
        Type       = "Pass"
        Parameters = { "all.$" = "States.JsonToString($.fetchResults)" }
        ResultPath = "$.fetchScan"
        Next       = "AnyFetchLegFailed"
      }

      # THE BOUND. Three arms, in order, and the order IS the safety property:
      #
      #  1. ANY leg classed infra -> FetchInfraFailNotify -> FAILED. A leg that
      #     never ran produced no verdict about a source, so it is not a blocked
      #     source and must not buy the run a continue.
      #  2. At least one leg failed AND NO leg succeeded -> FailNotify -> FAILED.
      #     This is the whole acquisition phase dying, and it is what happens for
      #     18 of the 25 enabled schedules, which carry exactly ONE fetch leg
      #     (histogram { 0: 1, 1: 18, 2: 4, 3: 1, 5: 1 }). For those 18 families
      #     the terminal status, the untouched canonical and the never-entered
      #     Bronze/Silver/Gate/Promote are all IDENTICAL to today; the only delta
      #     is that an email now goes out where the execution used to fail
      #     silently. "One blocked venue must not stale four others" has no force
      #     where there is no fourth, and this arm is that admission in code.
      #  3. At least one leg failed AND at least one succeeded -> DegradedNotify
      #     -> Bronze. This is the ONLY path that continues, and only the 6
      #     multi-fetch-leg families can reach it.
      #
      # Default = "Bronze" is today's behaviour exactly, so every all-green family
      # and the one family with zero fetch legs (fx_macro_daily -> family `fred`:
      # fetchResults == [], scan == "[]", which matches no arm) is unchanged.
      # Every comparison is And-guarded with IsPresent for the
      # ClassifyGateFailure reason: an unguarded comparison against a missing path
      # is a States.Runtime failure that no Catch can reach.
      AnyFetchLegFailed = {
        Type = "Choice"
        Choices = [
          {
            And = [
              { Variable = "$.fetchScan.all", IsPresent = true },
              { Variable = "$.fetchScan.all", StringMatches = "*\"class\":\"infra\"*" },
            ]
            Next = "FetchInfraFailNotify"
          },
          {
            And = [
              { Variable = "$.fetchScan.all", IsPresent = true },
              { Variable = "$.fetchScan.all", StringMatches = "*\"status\":\"failed\"*" },
              { Not = { Variable = "$.fetchScan.all", StringMatches = "*\"status\":\"ok\"*" } },
            ]
            Next = "FailNotify"
          },
          {
            And = [
              { Variable = "$.fetchScan.all", IsPresent = true },
              { Variable = "$.fetchScan.all", StringMatches = "*\"status\":\"failed\"*" },
            ]
            Next = "DegradedNotify"
          },
        ]
        Default = "Bronze"
      }

      # SAME TOPIC as FailNotify / InfraFailNotify (var.alerts_topic_arn ==
      # module.alerting.topic_arn == leviathan-dev-alerts). The exec role's
      # SnsPublishAlertTopics statement already grants sns:Publish on exactly that
      # ARN, so LANE B needs NO IAM change.
      #
      # THE RETRY IS HERE AND NOWHERE ELSE. FailNotify / InfraFailNotify /
      # FetchInfraFailNotify are each followed by a Fail state, so losing their
      # publish still shows as a FAILED execution. Losing THIS publish shows as a
      # fully SUCCEEDED run with no signal at all, and this email is the lane's
      # only new detector. D-PR-9's law is that a retry list must name a CLASS,
      # never "something went wrong" -- on a producer .sync task States.TaskFailed
      # conflates a data verdict with an infra death, which is why it is banned
      # there. On sns:publish there is exactly ONE class, "the publish did not go
      # through", and States.ALL names it exactly. No producer Retry is touched.
      #
      # The Catch is deliberate and is not a swallow. A degraded run has real
      # bronze/silver/gate/promote work to do for the sources that DID land; if
      # SNS still fails after the retries, failing the execution here would hand
      # one blocked venue the very outcome this lane exists to prevent. The failed
      # legs still ride in $.fetchResults into the execution output, and both the
      # transition and the error are in the execution history either way.
      #
      # DISCLOSURE: the message embeds the caught error objects, and a
      # batch:submitJob.sync Cause is the whole DescribeJobs JobDetail, which
      # carries the job definition's RESOLVED container environment. The three
      # credentials this estate registers (FAS_API_KEY, EVIDENCE_PG_DSN,
      # DATABENTO_API_KEY -- infra/terraform/modules/batch/main.tf) are ASM
      # `secrets` entries of shape { name, valueFrom }, i.e. Secrets Manager ARNs,
      # never values. This email can disclose a secret ARN; it cannot disclose a
      # secret.
      DegradedNotify = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = var.alerts_topic_arn
          "Subject.$" = "States.Format('[${local.name_prefix}] silver pipeline DEGRADED, fetch leg blocked: {}', $.family)"
          "Message.$" = "States.Format('Family {} ran DEGRADED. At least one FETCH leg was BLOCKED AT THE SOURCE (the job RAN and exited non-zero) AND at least one other fetch leg SUCCEEDED, so the pipeline CONTINUED to bronze/silver/gate/promote with the sources that did land. Execution {}. Per-leg results follow; a failed leg carries status failed, class source, its task (jobdef + command) and the whole caught error object: {}. NOT COVERED BY THIS TOLERANCE: a leg whose container never started is classed infra and does NOT arrive here -- that run FAILS. Neither does a run where every fetch leg failed. Bronze, Silver and Promote stay FAIL-FAST, so a failed derivation or publication leg still stops this run before canonical (INV-6) -- with ONE measured exception, weather_daily task chirps_to_bronze, a bronze WRITER that sits in the fetch phase of its descriptor and is therefore best-effort until that descriptor moves (accepted 2026-09-04, docketed). If the SAME leg degrades on consecutive fires, treat the SOURCE as blocked and open a docket -- do not rotate a user agent.', $.family, $$.Execution.Name, $.fetchScan.all)"
        }
        ResultPath = "$.degradedNotifyResult"
        Retry = [{
          ErrorEquals     = ["States.ALL"]
          IntervalSeconds = 5
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.degradedNotifyError"
          Next        = "Bronze"
        }]
        Next = "Bronze"
      }

      # THE OTHER HALF OF THE DISCRIMINATOR. A separate notifier, not
      # InfraFailNotify, for a measured reason: InfraFailNotify's text says
      # "produced NO GATE VERDICT ... the gate job did not run to a decision",
      # which is FALSE for a fetch-phase infra fault -- the gate was never even
      # reached. It also reads $.error.Error, and on this path $.error was written
      # by an ITEM-scoped Catch inside the Fetch iterator and does NOT exist at
      # top level; dereferencing it here would be a runtime path fault that no
      # Catch reaches. This state therefore reads ONLY paths the top-level object
      # is guaranteed to carry ($.family, $.fetchScan.all) plus the context
      # object's execution name, and it ends on the EXISTING PipelineInfraFailed
      # Fail state so the terminal error NAME (SilverPipelineInfraFailed) and
      # every consumer of it are unchanged. That Fail state's CAUSE, however, IS
      # widened to name this second inbound edge (NF-1): reusing the gate's cause
      # verbatim would reintroduce, in the terminal string an operator actually
      # reads, the very mislabel this notifier exists to avoid.
      FetchInfraFailNotify = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = var.alerts_topic_arn
          "Subject.$" = "States.Format('[${local.name_prefix}] silver pipeline INFRA FAILURE in FETCH: {}', $.family)"
          "Message.$" = "States.Format('Family {} produced NO SOURCE VERDICT in the FETCH phase. At least one fetch leg failed INFRA-side -- that is NOT a blocked source, so it was NOT tolerated. EVERY ROUTE THAT LANDS HERE, one sentence each, so this email can never deny the mechanism that actually fired. (a) NO EXIT CODE AT ALL in the Batch job detail: no container ever ran to an exit, so the job never became a job. (b) THE CONTAINER DID NOT CHOOSE ITS EXIT: an exit code at or above 128, the POSIX signal floor, where 137 = 128 + SIGKILL is what an OOM-killed Fargate container reports -- it DID run and it DID exit, so do not go hunting for a special StatusReason, read the exit code. (c) THE STATUSREASON BEGINS with CannotPullContainer, ResourceInitializationError, OutOfMemory, Task failed to start or DockerTimeoutError. (d) THE CONTAINER REASON BEGINS with one of those same five, in either spelling AWS may use (Reason or reason). (e) A BATCH SERVICE FAULT or a .sync timeout ended the leg under its own error name. (f) A GLUE fetch leg failed at all: a Glue cause carries no exit code, so this lane never tolerates one. (g) THE FAILURE COULD NOT BE CLASSIFIED -- an error name that carries no Batch job detail, a cause that is not a JSON object, or a job detail matching none of the above -- and the unrecognised case is NOT tolerated by design. Bronze, silver, gate and promote were never entered and canonical was never touched (INV-6). Execution {}. Per-leg results follow; an infra leg carries class infra plus its task (jobdef + command) and the whole caught error object: {}. Do not hunt a data problem -- read the failed Batch attempt (exit code + StatusReason + container reason) in the execution history and the /aws/batch log stream, fix the infra fault, then re-run the family.', $.family, $$.Execution.Name, $.fetchScan.all)"
        }
        ResultPath = "$.notifyResult"
        Next       = "PipelineInfraFailed"
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
        # D-PR-10, three arms, evaluated in order:
        #   1. the Batch service faults ALREADY in the Retry list above (i.e. retries exhausted) plus
        #      Batch.AWSBatchException -- SubmitJob itself never produced a running gate, or the .sync
        #      wait timed out. "Never ran / no verdict" by construction, no Cause parsing needed.
        #   2. States.TaskFailed -- the job RAN and failed. Refusal or infra death: only the Cause knows.
        #   3. States.ALL -- anything unclassified keeps today's route, unchanged.
        Catch = [
          {
            ErrorEquals = ["Batch.ServerException", "Batch.TooManyRequestsException", "States.Timeout",
            "Batch.AWSBatchException"]
            ResultPath = "$.error"
            Next       = "InfraFailNotify"
          },
          {
            ErrorEquals = ["States.TaskFailed"]
            ResultPath  = "$.error"
            Next        = "ClassifyGateFailure"
          },
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "FailNotify"
          },
        ]
        ResultPath = "$.gateResult"
        Next       = "Promote" # [Choice] fork realized as the .sync exit-code exception (green -> here)
      }

      # --- D-PR-10 classifier: refusal (exit 1) -> FailNotify; every other cause -> InfraFailNotify. ---
      # THE SHAPE GATE. Reached only from the Gate's States.TaskFailed Catch arm, so the error NAME is
      # already established by construction here (the Batch service faults took the arm above it) --
      # what is left to establish is that the Cause is a JSON object, because the parse that follows
      # is a Pass and a Pass cannot carry a Catch. Unmatched -> Default -> FailNotify, i.e. today's
      # route, which is why this state can only improve attribution and cannot lose a notification.
      ClassifyGateFailure = {
        Type = "Choice"
        Choices = [{
          And  = local.batch_cause_is_parseable
          Next = "ParseBatchCauseGate"
        }]
        Default = "FailNotify" # unparseable cause == today's behaviour, never a lost notification
      }

      # THE SHARED PARSE, second reader. Byte-identical to ParseBatchCauseFetch except for `Next`.
      ParseBatchCauseGate = merge(local.batch_cause_parse_pass, { Next = "ClassifyBatchCauseGate" })

      # THE GATE'S READER over the parsed JobDetail. Exit 1 is a REFUSAL (a decision about data) and
      # takes the same FailNotify the whole pipeline's failures take; 64/70/71/72 are the gate's own
      # non-verdict codes; the shared infra arms catch a container that never became the gate.
      #
      # THE TWO DIRECTIONS THIS CHANGE MOVES, WRITTEN OUT BECAUSE A HANDOFF REPORT GOT THEM BACKWARDS
      # ONCE (review finding 2026-09-07, MINOR) AND THE OWNER READS THE REPORT. Both measured by
      # evaluating the rendered rules of HEAD and of this tree against the same Cause documents:
      #   EXIT 2 (and every other code the gate CHOSE that is outside the D-PR-8 vocabulary) moves
      #   TOWARDS THE ORDINARY FAILURE EMAIL. HEAD = InfraFailNotify, the NO GATE VERDICT mail, because
      #   the code fell past the exit-code substrings into the container-never-started substrings,
      #   which the jobdef RetryStrategy makes match every Cause. THIS TREE = FailNotify, the
      #   documented Default, which HEAD could not reach. Fixture batch_exit2_unknown_code declares
      #   exactly that, and the measured shape behind it is DSG-TAIL F1 probe job cb151695.
      #   AN OOM-KILLED OR NEVER-STARTED GATE moves the OTHER WAY, towards no-verdict: exit >= 128, a
      #   job detail with no ExitCode at all, or a roster prefix in StatusReason or the container
      #   reason now reach InfraFailNotify where the 2026-09-06 draft sent them to FailNotify.
      # The two halves of the sentence point in OPPOSITE directions; either one alone is a misreport.
      ClassifyBatchCauseGate = local.gate_parsed_cause_classifier

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

      # --- reconcile (A-W3 step 2): after the GREEN gate + GREEN promote, re-run the census on the SAME
      #     silver-gate jobdef/image and roll the run's post-census FORWARD to the family's rolling S3
      #     baseline s3://<bucket>/cascade_census/rolling/{family}/census.json (== $.gate_baseline_uri, the
      #     key the next scheduled gate reads via --baseline-uri). advance_rolling_census exits 0 ONLY on a
      #     clean census (rc==0) uploaded successfully; a nonzero exit raises States.TaskFailed on the .sync
      #     integration -> Catch -> [FailNotify] (a failed reconcile FAILS visibly, never leaves a stale
      #     baseline). GRAPHRAG_NUMBERS_BACKEND=pg mirrors the Gate invariant (plan line 87). ---
      Reconcile = {
        Type     = "Task"
        Resource = "arn:aws:states:::batch:submitJob.sync"
        Parameters = {
          "JobName.$"       = "States.Format('{}-reconcile-{}', $.family, States.UUID())"
          "JobDefinition.$" = "$.gate.jobdef" # same silver-gate jobdef/image (advance_rolling_census must be IN it)
          "JobQueue.$"      = "$.gate.queue"
          ContainerOverrides = {
            # -m module form (the census + rolling baseline write): python -m jobs.audit.advance_rolling_census
            #   --asof <$.asof, string-coerced> --dest-uri <$.gate_baseline_uri>.
            "Command.$" = "States.Array('-m', 'jobs.audit.advance_rolling_census', '--asof', States.Format('{}', $.asof), '--dest-uri', $.gate_baseline_uri)"
            Environment = [{ Name = "GRAPHRAG_NUMBERS_BACKEND", Value = "pg" }]
          }
        }
        # Retry ONLY transient Batch service faults -- NEVER States.TaskFailed (a failed reconcile must not
        # be retried into a false green; the census is deterministic given the mirror).
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
        ResultPath = "$.reconcileResult"
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

      # --- D-PR-10: the OTHER email. Same topic, different Subject, and a message that does not ---
      #     claim a verdict that was never reached. `$.error.Error` is the SFN error name (always
      #     present in a caught error object); the exit code and StatusReason live in the execution
      #     history's Cause and in the /aws/batch log stream, both named in the text.
      InfraFailNotify = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = var.alerts_topic_arn
          "Subject.$" = "States.Format('[${local.name_prefix}] silver pipeline INFRA FAILURE, no gate verdict: {}', $.family)"
          "Message.$" = "States.Format('Family {} produced NO GATE VERDICT. The gate job did not run to a decision ({}). Execution {}. This is an INFRASTRUCTURE fault, NOT a refusal: no table was judged, [Promote] was never entered and canonical was never touched (INV-6). Do not hunt a data problem -- read the failed Batch attempt (exit code + StatusReason) in the execution history and the /aws/batch log stream, fix the infra fault, then re-run the family. Gate exit codes: 64 usage, 70 internal crash, 71 image/config fence, 72 baseline fetch (D-PR-8). SINCE 2026-09-07 THIS EMAIL COVERS MORE THAN THAT VOCABULARY, one sentence per inbound class, so it never denies the mechanism that fired. (a) The job detail carries NO EXIT CODE AT ALL, so the gate container never ran to an exit. (b) The gate was KILLED rather than choosing its exit -- an exit code at or above 128, the POSIX signal floor, where 137 = 128 + SIGKILL is what an OOM-killed Fargate container reports. (c) The StatusReason begins with CannotPullContainer, ResourceInitializationError, OutOfMemory, Task failed to start or DockerTimeoutError. (d) The container reason begins with one of those same five, in either spelling AWS may use (Reason or reason). (e) A Batch service fault or a .sync timeout ended the job under its own error name. AN EXIT CODE THE GATE CHOSE THAT IS OUTSIDE THE D-PR-8 VOCABULARY IS NOT THIS EMAIL: exit 2 and every other unrecognised code now reach the ordinary silver pipeline FAILED notice, which is where the documented default always said they should go and which a jobdef RetryStrategy substring used to make unreachable.', $.family, $.error.Error, $$.Execution.Name)"
        }
        ResultPath = "$.notifyResult"
        Next       = "PipelineInfraFailed"
      }
      # NF-1. This Fail state has TWO inbound edges since Lane B: InfraFailNotify (the
      # GATE produced no verdict) and FetchInfraFailNotify (a FETCH leg failed infra-side,
      # so the gate was never reached). The Cause is the string DescribeExecution and the
      # SFN console show, so it must name both edges: the old wording sent an operator
      # holding a fetch-phase infra fault off to read a gate that never ran -- the exact
      # mislabel FetchInfraFailNotify exists to avoid, reintroduced one state later. The
      # error NAME is frozen (SilverPipelineInfraFailed, the D-PR-10 vocabulary) and
      # tests/unit/test_gate_exit_vocabulary.py:328 pins that NAME. The CAUSE is pinned
      # too, on the WIDENED wording, at tests/unit/test_thin_contract_fetch_degraded.py:465
      # -- reword the string here and there together or that pin goes red.
      PipelineInfraFailed = {
        Type  = "Fail"
        Error = "SilverPipelineInfraFailed"
        Cause = "The silver_rebuild_gate produced NO VERDICT, or a FETCH leg failed infra-side before the gate was reached (infrastructure fault: the job never ran, never finished, or exited on a non-verdict code). Canonical promote was skipped and canonical was never touched."
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
#
# LANE B ACCEPTANCE, MIRRORED HERE ON PURPOSE. The operator runbook lives at
# docs/private/LANE_B_FETCH_TOLERANCE_ROLLOUT.md, and docs/private/ is gitignored
# -- it does not survive a clean clone. This file does. Blast radius: ONE machine,
# 25 of 25 enabled schedules, 21 distinct families, NO per-family canary.
#
# WHAT DOES *NOT* FAIL CLOSED AT APPLY. terraform validate proves HCL types only,
# and UpdateStateMachine validates ASL SYNTAX only -- error names, intrinsic
# arity, JSONPath syntax, Next-target existence. It does NOT prove that
# States.JsonToString accepts an ARRAY at that path, that a per-item Catch ENDS
# the item rather than failing the Map, or that an sns:publish reaches the topic.
# NONE of those fail closed at apply. The THROWAWAY PROBE EXECUTION IS THE GATE,
# and it must run BEFORE the next scheduled fire:
#   P1 two fetch legs, one exit 1 and one exit 0, empty bronze/silver/promote:
#      expect SUCCEEDED, fetchResults = [{status failed, class source, task,
#      error, cause}, {status ok}], RecordSourceFailureFetch once,
#      DegradedNotify once then TaskSucceeded, ONE degraded email.
#      P1 WAS RUN AND IT FAILED -- execution laneb-p1-20260906T234214Z,
#      2026-09-06 23:42Z, jobdef leviathan-dev-b3-flat-silver rev 37. Terminal
#      FAILED / SilverPipelineInfraFailed; history events 13-15 show
#      ClassifyFailureFetch -> RecordInfraFailureFetch on the exit-1 leg, then
#      FetchInfraFailNotify. The green leg was sound (TaskSucceeded, event 25).
#      ROOT CAUSE: the classifier string-matched the WHOLE Cause and the Cause
#      embeds the jobdef's own RetryStrategy, which names CannotPullContainer*
#      and ResourceInitializationError* -- so the infra arm matched every Batch
#      failure in the estate and the source arm was unreachable. THE PROBE DID
#      ITS JOB. The classifier now parses the Cause and reads named fields (see
#      the ONE PARSER, TWO READERS banner), and ALL THREE PROBES MUST BE RE-RUN
#      ON THE FIXED MACHINE -- P1 is no longer a first-fire test but a
#      REGRESSION test, and it is the one that must go SUCCEEDED this time.
#      Fixtures tests/fixtures/sfn_causes/ carry the real P1 Cause; the offline
#      pins in tests/unit/test_thin_contract_fetch_degraded.py evaluate the
#      rendered Choice rules against it, so an offline red now precedes a probe
#      red.
#   P2 TWO fetch legs, one infra-shaped (a jobdef that does not exist) and one
#      GREEN: expect FetchInfraFailNotify once and DegradedNotify NEVER, even
#      though the other leg SUCCEEDED -- infra WINS over "at least one leg
#      landed", which is the one property this lane added most code for. Terminal
#      FAILED with error SilverPipelineInfraFailed, Bronze NEVER entered. The
#      second leg is load-bearing: run with ONE leg and the probe proves nothing,
#      because a single failed leg takes arm 2 whatever its class.
#   P3 ONE fetch leg that exits 1 -- a SEPARATE probe, NOT implied by P2, and the
#      only one that exercises the M1 bound: expect RecordSourceFailureFetch once,
#      FailNotify once, DegradedNotify NEVER, terminal FAILED with error
#      SilverPipelineGateFailed, Bronze NEVER entered. This is the shape all 18
#      single-fetch-leg schedules take.
#   If P1 does not show {"status":"ok"} for the green leg, ROLL BACK before the
#   next cron fire: restore this file from git and re-apply the single -target.
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
