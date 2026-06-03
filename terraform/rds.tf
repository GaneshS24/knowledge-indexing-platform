# ─── DB Subnet Group ─────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "main" {
  name       = "knowledge-platform"
  subnet_ids = aws_subnet.private[*].id
}

# ─── Aurora PostgreSQL Cluster ────────────────────────────────────────────────

resource "aws_rds_cluster" "main" {
  cluster_identifier      = "knowledge-platform-${var.environment}"
  engine                  = "aurora-postgresql"
  engine_version          = "15.4"
  database_name           = "knowledge_platform"
  master_username         = "kp_admin"
  master_password         = var.db_password
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]

  # Backup & maintenance
  backup_retention_period   = 7
  preferred_backup_window   = "03:00-04:00"
  preferred_maintenance_window = "sun:04:00-sun:05:00"
  deletion_protection       = var.environment == "prod"
  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "knowledge-platform-final" : null

  # Encryption
  storage_encrypted = true

  enabled_cloudwatch_logs_exports = ["postgresql"]
}

resource "aws_rds_cluster_instance" "writer" {
  identifier           = "knowledge-platform-writer"
  cluster_identifier   = aws_rds_cluster.main.id
  instance_class       = "db.r6g.large"
  engine               = aws_rds_cluster.main.engine
  engine_version       = aws_rds_cluster.main.engine_version
  db_subnet_group_name = aws_db_subnet_group.main.name

  performance_insights_enabled = true
}

resource "aws_rds_cluster_instance" "reader" {
  count                = var.environment == "prod" ? 2 : 0
  identifier           = "knowledge-platform-reader-${count.index + 1}"
  cluster_identifier   = aws_rds_cluster.main.id
  instance_class       = "db.r6g.large"
  engine               = aws_rds_cluster.main.engine
  engine_version       = aws_rds_cluster.main.engine_version
  db_subnet_group_name = aws_db_subnet_group.main.name

  performance_insights_enabled = true
}

# ─── Secrets Manager — DB Connection URL ─────────────────────────────────────

resource "aws_secretsmanager_secret" "db_url" {
  name                    = "knowledge-platform/${var.environment}/database-url"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id = aws_secretsmanager_secret.db_url.id
  secret_string = "postgresql://${aws_rds_cluster.main.master_username}:${var.db_password}@${aws_rds_cluster.main.endpoint}:5432/${aws_rds_cluster.main.database_name}"
}
