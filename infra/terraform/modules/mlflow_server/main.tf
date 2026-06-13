# Derive the VPC and its CIDR from the supplied subnet so the security group
# inbound rule can be scoped to the VPC without needing a separate variable.
data "aws_subnet" "mlflow" {
  id = var.subnet_id
}

data "aws_vpc" "main" {
  id = data.aws_subnet.mlflow.vpc_id
}

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
# Security group — port 5000 inbound from the VPC only.
# Use SSM Session Manager port-forwarding for browser access from your laptop:
#   aws ssm start-session --target <instance_id> \
#     --document-name AWS-StartPortForwardingSession \
#     --parameters portNumber=5000,localPortNumber=5000
# Then open http://localhost:5000 in your browser.
# ---------------------------------------------------------------------------
resource "aws_security_group" "mlflow" {
  name        = "${var.project_name}-${var.environment}-mlflow-server"
  description = "MLflow tracking server: port 5000 from VPC only; no inbound SSH."
  vpc_id      = data.aws_vpc.main.id

  ingress {
    description = "MLflow UI and API from within the VPC"
    from_port   = 5000
    to_port     = 5000
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

resource "aws_iam_instance_profile" "mlflow" {
  name = "${var.project_name}-${var.environment}-mlflow-instance-profile"
  role = aws_iam_role.mlflow_instance.name
}

# ---------------------------------------------------------------------------
# EC2 instance — t3.micro.
# User data installs MLflow and starts it as a systemd service on boot.
# The backend store is SQLite (on the local disk of the instance).
# Artifacts (model files, plots) are stored in S3 under mlflow/artifacts/.
# ---------------------------------------------------------------------------
resource "aws_instance" "mlflow" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = "t3.micro"
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.mlflow.id]
  iam_instance_profile   = aws_iam_instance_profile.mlflow.name

  root_block_device {
    volume_type = "gp3"
    volume_size = 10
    encrypted   = true
  }

  # Terraform expands ${var.*} before this reaches the instance.
  # The inner << SERVICE_EOF heredoc is plain bash and is NOT a Terraform heredoc.
  user_data = <<-USER_DATA
#!/bin/bash
set -euo pipefail

dnf update -y
dnf install -y python3 python3-pip
pip3 install "mlflow>=2.9" boto3

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
ExecStart=/usr/local/bin/mlflow server --backend-store-uri sqlite:////home/ec2-user/mlflow/mlflow.db --default-artifact-root s3://${var.bucket_name}/mlflow/artifacts/ --host 0.0.0.0 --port 5000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable mlflow
systemctl start mlflow
USER_DATA

  tags = {
    Name        = "${var.project_name}-${var.environment}-mlflow-server"
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
