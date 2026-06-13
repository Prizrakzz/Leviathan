output "instance_id" {
  value       = aws_instance.mlflow.id
  description = "EC2 instance ID of the MLflow tracking server."
}

output "private_ip" {
  value       = aws_instance.mlflow.private_ip
  description = "Private IP of the MLflow server — reachable from within the VPC."
}

output "tracking_uri" {
  value       = "http://${aws_instance.mlflow.private_ip}:5000"
  description = "MLFLOW_TRACKING_URI to set in SageMaker Training Jobs and Batch containers."
}
