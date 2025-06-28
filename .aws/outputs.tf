output "ec2_public_ip" {
  description = "Public IP of the application server"
  value       = aws_instance.app.public_ip
}

output "rds_endpoint" {
  description = "RDS endpoint (private)"
  value       = aws_db_instance.postgres.endpoint
}

output "rds_port" {
  value = aws_db_instance.postgres.port
}
