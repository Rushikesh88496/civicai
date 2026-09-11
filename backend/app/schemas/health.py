from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str


class DatabaseHealth(BaseModel):
    status: str
    postgis: str
    pgvector: str


class ConnectionMeta(BaseModel):
    host: str
    port: int
    database: str


class SystemHealthResponse(BaseModel):
    status: str
    version: str
    api: str
    database: DatabaseHealth
    redis: str
    connection: ConnectionMeta
