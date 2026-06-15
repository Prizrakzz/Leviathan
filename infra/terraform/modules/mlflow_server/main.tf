# Derive the VPC and its CIDR from the supplied subnet so the security group
# inbound rule can be scoped to the VPC without needing a separate variable.
data "aws_subnet" "mlflow" {
  id = var.subnet_id
}

data "aws_vpc" "main" {
  id = data.aws_subnet.mlflow.vpc_id
}

data "aws_caller_identity" "current" {}

# Latest Amazon Linux 2023 AMI (x86_64).
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# ---------------------------------------------------------------------------
# Security group — ports 5000 (MLflow) and 8080 (Airflow) from VPC only.
# Use SSM Session Manager port-forwarding for browser access from your laptop:
#   MLflow:
#     aws ssm start-session --target <instance_id> \
#       --document-name AWS-StartPortForwardingSession \
#       --parameters portNumber=5000,localPortNumber=5000
#   Airflow:
#     aws ssm start-session --target <instance_id> \
#       --document-name AWS-StartPortForwardingSession \
#       --parameters portNumber=8080,localPortNumber=8080
# ---------------------------------------------------------------------------
resource "aws_security_group" "mlflow" {
  name        = "${var.project_name}-${var.environment}-mlflow-server"
  description = "MLflow + Airflow server: ports 5000 and 8080 from VPC only; no inbound SSH."
  vpc_id      = data.aws_vpc.main.id

  ingress {
    description = "MLflow UI and API from within the VPC"
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.main.cidr_block]
  }

  ingress {
    description = "Airflow webserver from within the VPC"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.main.cidr_block]
  }

  egress {
    description = "All outbound (S3, SSM endpoints, package mirrors)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-mlflow-server"
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# IAM role — S3 access scoped to the mlflow/ prefix + SSM for shell/port-fwd.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "mlflow_instance" {
  name = "${var.project_name}-${var.environment}-mlflow-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "mlflow_ssm" {
  role       = aws_iam_role.mlflow_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "mlflow_s3" {
  statement {
    sid     = "MLflowListBucket"
    actions = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.bucket_name}"]
  }

  statement {
    sid = "MLflowArtifactsRW"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["arn:aws:s3:::${var.bucket_name}/mlflow/*"]
  }
}

resource "aws_iam_policy" "mlflow_s3" {
  name        = "${var.project_name}-${var.environment}-mlflow-s3"
  description = "MLflow server read/write access to the mlflow/ S3 prefix."
  policy      = data.aws_iam_policy_document.mlflow_s3.json
}

resource "aws_iam_role_policy_attachment" "mlflow_s3" {
  role       = aws_iam_role.mlflow_instance.name
  policy_arn = aws_iam_policy.mlflow_s3.arn
}

# ---------------------------------------------------------------------------
# IAM — Airflow: submit/manage Batch jobs + write task logs to CloudWatch.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "airflow_permissions" {
  statement {
    sid = "BatchSubmitAndManage"
    actions = [
      "batch:SubmitJob",
      "batch:DescribeJobs",
      "batch:ListJobs",
      "batch:TerminateJob",
      "batch:DescribeJobDefinitions",
      "batch:DescribeJobQueues",
    ]
    resources = ["*"]
  }

  statement {
    sid = "CloudWatchLogsWrite"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/airflow/*",
    ]
  }
}

resource "aws_iam_policy" "airflow_permissions" {
  name        = "${var.project_name}-${var.environment}-airflow-permissions"
  description = "Airflow scheduler: submit/manage Batch jobs and write task logs to CloudWatch."
  policy      = data.aws_iam_policy_document.airflow_permissions.json
}

resource "aws_iam_role_policy_attachment" "airflow_permissions" {
  role       = aws_iam_role.mlflow_instance.name
  policy_arn = aws_iam_policy.airflow_permissions.arn
}

resource "aws_iam_instance_profile" "mlflow" {
  name = "${var.project_name}-${var.environment}-mlflow-instance-profile"
  role = aws_iam_role.mlflow_instance.name
}

# ---------------------------------------------------------------------------
# EC2 instance — t3.medium (2 vCPU, 4 GB RAM).
# Hosts both MLflow tracking server (port 5000) and Airflow (port 8080).
# Both SQLite backends survive stop/start but NOT termination (dev only).
#
# Start/stop manually to pay only for actual use:
#   aws ec2 start-instances  --instance-ids <id> --region us-east-1
#   aws ec2 stop-instances   --instance-ids <id> --region us-east-1
# ---------------------------------------------------------------------------
resource "aws_instance" "mlflow" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = "t3.medium"
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.mlflow.id]
  iam_instance_profile        = aws_iam_instance_profile.mlflow.name
  user_data_replace_on_change = true

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  # Terraform expands ${var.*} before this reaches the instance.
  # $FERNET_KEY and $(...) are bash — Terraform leaves $VAR (no braces) alone.
  # Inner << SERVICE_EOF heredocs are unquoted so bash expands $FERNET_KEY into them.
  # Inner << 'INIT_EOF' is quoted so bash treats the init script as literal text.
  user_data = <<-USER_DATA
#!/bin/bash
set -euo pipefail

dnf update -y
dnf install -y python3 gcc python3-devel libffi-devel

# ---------------------------------------------------------------------------
# MLflow tracking server (port 5000)
# ---------------------------------------------------------------------------
python3 -m venv /opt/mlflow-venv
/opt/mlflow-venv/bin/pip install --quiet --upgrade pip
/opt/mlflow-venv/bin/pip install --quiet "mlflow>=2.9" boto3

mkdir -p /home/ec2-user/mlflow
chown ec2-user:ec2-user /home/ec2-user/mlflow

cat > /etc/systemd/system/mlflow.service << SERVICE_EOF
[Unit]
Description=MLflow Tracking Server
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/mlflow
Environment=AWS_DEFAULT_REGION=${var.aws_region}
ExecStart=/opt/mlflow-venv/bin/mlflow server \
  --backend-store-uri sqlite:////home/ec2-user/mlflow/mlflow.db \
  --default-artifact-root s3://${var.bucket_name}/mlflow/artifacts/ \
  --host 0.0.0.0 \
  --port 5000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# ---------------------------------------------------------------------------
# Airflow (LocalExecutor, SQLite backend, port 8080)
# ---------------------------------------------------------------------------
python3 -m venv /opt/airflow-venv
/opt/airflow-venv/bin/pip install --quiet --upgrade pip
/opt/airflow-venv/bin/pip install --quiet \
  "apache-airflow[amazon]==2.9.3" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.9.3/constraints-3.9.txt"

mkdir -p /home/ec2-user/airflow/dags \
         /home/ec2-user/airflow/logs \
         /home/ec2-user/airflow/plugins
chown -R ec2-user:ec2-user /home/ec2-user/airflow

# Generate a stable FERNET_KEY and write it to a persistent env file.
# Both systemd services use EnvironmentFile= to pick it up on every start.
FERNET_KEY=$(/opt/airflow-venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

cat > /etc/airflow-env << ENVEOF
AIRFLOW_HOME=/home/ec2-user/airflow
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:////home/ec2-user/airflow/airflow.db
AIRFLOW__CORE__FERNET_KEY=$FERNET_KEY
AIRFLOW__WEBSERVER__SECRET_KEY=$FERNET_KEY
AIRFLOW__CORE__LOAD_EXAMPLES=False
AWS_DEFAULT_REGION=${var.aws_region}
ENVEOF
chmod 600 /etc/airflow-env

# Initialise the Airflow DB and create the admin user.
# Single-quoted heredoc: bash treats content as literal (no variable expansion at write time).
cat > /tmp/airflow_init.sh << 'INIT_EOF'
#!/bin/bash
set -a
source /etc/airflow-env
set +a
/opt/airflow-venv/bin/airflow db migrate
/opt/airflow-venv/bin/airflow users create \
  --username admin --password leviathan \
  --firstname Admin --lastname User \
  --role Admin --email admin@leviathan.dev || true
INIT_EOF
chmod +x /tmp/airflow_init.sh
chown ec2-user:ec2-user /tmp/airflow_init.sh
su -s /bin/bash ec2-user -c "/tmp/airflow_init.sh" || true

cat > /etc/systemd/system/airflow-webserver.service << SERVICE_EOF
[Unit]
Description=Airflow Webserver
After=network.target

[Service]
Type=simple
User=ec2-user
EnvironmentFile=/etc/airflow-env
ExecStart=/opt/airflow-venv/bin/airflow webserver --port 8080
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_EOF

cat > /etc/systemd/system/airflow-scheduler.service << SERVICE_EOF
[Unit]
Description=Airflow Scheduler
After=network.target

[Service]
Type=simple
User=ec2-user
EnvironmentFile=/etc/airflow-env
ExecStart=/opt/airflow-venv/bin/airflow scheduler
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable mlflow airflow-webserver airflow-scheduler
systemctl start mlflow || true
systemctl start airflow-webserver || true
systemctl start airflow-scheduler || true
USER_DATA

  tags = {
    Name        = "${var.project_name}-${var.environment}-mlflow-server"
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
