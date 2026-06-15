variable "aws_region" {
  description = "AWS region to deploy resources into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment label (e.g. dev, staging, prod)."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "project_name" {
  description = "Short name prefix applied to all resources."
  type        = string
  default     = "drift-agent"
}

variable "instance_type" {
  description = "EC2 instance type for the application server."
  type        = string
  default     = "t3.micro"
}

variable "allowed_cidr_blocks" {
  description = "List of CIDR blocks allowed inbound on port 443."
  type        = list(string)
  default     = ["10.0.0.0/8"]
}
