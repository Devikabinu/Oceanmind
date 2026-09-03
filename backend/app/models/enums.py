import enum


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    RESEARCHER = "RESEARCHER"
    USER = "USER"


class DataSourceStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEPRECATED = "DEPRECATED"


class IngestionJobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DatasetKind(str, enum.Enum):
    ENVIRONMENTAL = "ENVIRONMENTAL"
    BIODIVERSITY = "BIODIVERSITY"
