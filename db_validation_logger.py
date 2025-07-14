import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class ValidationStatus(Enum):
    """검증 상태 열거형"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    PENDING = "pending"

class ChangeType(Enum):
    """변경 타입 열거형"""
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    VALIDATE = "validate"

@dataclass
class ValidationLog:
    """검증 로그 데이터 클래스"""
    id: Optional[int]
    timestamp: datetime
    operation_type: str  # 'validation', 'update', 'sync'
    status: ValidationStatus
    total_nodes: int
    validated_nodes: int
    failed_nodes: int
    error_messages: List[str]
    metadata: Dict[str, Any]
    ai_model: str
    processing_time: float

@dataclass
class ChangeLog:
    """변경 로그 데이터 클래스"""
    id: Optional[int]
    timestamp: datetime
    node_id: str
    change_type: ChangeType
    old_data: Optional[Dict[str, Any]]
    new_data: Optional[Dict[str, Any]]
    validation_status: ValidationStatus
    error_message: Optional[str]
    ai_suggestion: Optional[str]
    metadata: Dict[str, Any]

class DatabaseValidationLogger:
    """데이터베이스 검증 및 갱신 로그 관리자"""
    
    def __init__(self, db_path: str = "validation_logs.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """데이터베이스 초기화"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 검증 로그 테이블 생성
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS validation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_nodes INTEGER NOT NULL,
                    validated_nodes INTEGER NOT NULL,
                    failed_nodes INTEGER NOT NULL,
                    error_messages TEXT,
                    metadata TEXT,
                    ai_model TEXT NOT NULL,
                    processing_time REAL NOT NULL
                )
            ''')
            
            # 변경 로그 테이블 생성
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS change_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    old_data TEXT,
                    new_data TEXT,
                    validation_status TEXT NOT NULL,
                    error_message TEXT,
                    ai_suggestion TEXT,
                    metadata TEXT
                )
            ''')
            
            # 인덱스 생성
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_validation_timestamp ON validation_logs(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_validation_status ON validation_logs(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_timestamp ON change_logs(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_node_id ON change_logs(node_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_change_type ON change_logs(change_type)')
            
            conn.commit()
    
    def log_validation(self, validation_log: ValidationLog) -> int:
        """검증 로그 저장"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO validation_logs 
                (timestamp, operation_type, status, total_nodes, validated_nodes, 
                 failed_nodes, error_messages, metadata, ai_model, processing_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                validation_log.timestamp.isoformat(),
                validation_log.operation_type,
                validation_log.status.value,
                validation_log.total_nodes,
                validation_log.validated_nodes,
                validation_log.failed_nodes,
                json.dumps(validation_log.error_messages),
                json.dumps(validation_log.metadata, default=str),
                validation_log.ai_model,
                validation_log.processing_time
            ))
            
            log_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"Validation log saved with ID: {log_id}")
            return log_id
    
    def log_change(self, change_log: ChangeLog) -> int:
        """변경 로그 저장"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO change_logs 
                (timestamp, node_id, change_type, old_data, new_data, 
                 validation_status, error_message, ai_suggestion, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                change_log.timestamp.isoformat(),
                change_log.node_id,
                change_log.change_type.value,
                json.dumps(change_log.old_data, default=str) if change_log.old_data else None,
                json.dumps(change_log.new_data, default=str) if change_log.new_data else None,
                change_log.validation_status.value,
                change_log.error_message,
                change_log.ai_suggestion,
                json.dumps(change_log.metadata, default=str)
            ))
            
            log_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"Change log saved with ID: {log_id}")
            return log_id
    
    def get_validation_logs(self, limit: int = 100, status: Optional[ValidationStatus] = None) -> List[ValidationLog]:
        """검증 로그 조회"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM validation_logs"
            params = []
            
            if status:
                query += " WHERE status = ?"
                params.append(status.value)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            logs = []
            for row in rows:
                log = ValidationLog(
                    id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    operation_type=row[2],
                    status=ValidationStatus(row[3]),
                    total_nodes=row[4],
                    validated_nodes=row[5],
                    failed_nodes=row[6],
                    error_messages=json.loads(row[7]) if row[7] else [],
                    metadata=json.loads(row[8]) if row[8] else {},
                    ai_model=row[9],
                    processing_time=row[10]
                )
                logs.append(log)
            
            return logs
    
    def get_change_logs(self, node_id: Optional[str] = None, limit: int = 100) -> List[ChangeLog]:
        """변경 로그 조회"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM change_logs"
            params = []
            
            if node_id:
                query += " WHERE node_id = ?"
                params.append(node_id)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            logs = []
            for row in rows:
                log = ChangeLog(
                    id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    node_id=row[2],
                    change_type=ChangeType(row[3]),
                    old_data=json.loads(row[4]) if row[4] else None,
                    new_data=json.loads(row[5]) if row[5] else None,
                    validation_status=ValidationStatus(row[6]),
                    error_message=row[7],
                    ai_suggestion=row[8],
                    metadata=json.loads(row[9]) if row[9] else {}
                )
                logs.append(log)
            
            return logs
    
    def get_validation_stats(self, days: int = 30) -> Dict[str, Any]:
        """검증 통계 조회"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 최근 N일간의 통계
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_validations,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_validations,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_validations,
                    AVG(processing_time) as avg_processing_time,
                    SUM(total_nodes) as total_nodes_processed,
                    SUM(validated_nodes) as total_validated_nodes,
                    SUM(failed_nodes) as total_failed_nodes
                FROM validation_logs 
                WHERE timestamp >= datetime('now', '-{} days')
            '''.format(days))
            
            row = cursor.fetchone()
            
            return {
                'total_validations': row[0],
                'successful_validations': row[1],
                'failed_validations': row[2],
                'avg_processing_time': row[3],
                'total_nodes_processed': row[4],
                'total_validated_nodes': row[5],
                'total_failed_nodes': row[6]
            }
    
    def cleanup_old_logs(self, days: int = 90):
        """오래된 로그 정리"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 오래된 검증 로그 삭제
            cursor.execute('''
                DELETE FROM validation_logs 
                WHERE timestamp < datetime('now', '-{} days')
            '''.format(days))
            
            validation_deleted = cursor.rowcount
            
            # 오래된 변경 로그 삭제
            cursor.execute('''
                DELETE FROM change_logs 
                WHERE timestamp < datetime('now', '-{} days')
            '''.format(days))
            
            change_deleted = cursor.rowcount
            
            conn.commit()
            
            logger.info(f"Cleaned up {validation_deleted} validation logs and {change_deleted} change logs older than {days} days") 