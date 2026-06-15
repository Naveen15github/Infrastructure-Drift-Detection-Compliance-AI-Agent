output "vpc_id" {
  description = "ID of the created VPC."
  value       = aws_vpc.main.id
}

output "instance_id" {
  description = "ID of the EC2 application instance."
  value       = aws_instance.app.id
}

output "s3_bucket_name" {
  description = "Name of the S3 application bucket."
  value       = aws_s3_bucket.app.bucket
}

output "security_group_id" {
  description = "ID of the application security group."
  value       = aws_security_group.app.id
}
